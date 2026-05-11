import re

from backend.extensions import db
from backend.models import Problem, StopsMatched
from backend.services.stats_export import compute_db_stats


def test_compute_db_stats_includes_contradicts_route_matching(app, monkeypatch):
    import sqlalchemy.dialects.sqlite.base as sqlite_base

    orig_do_execute = sqlite_base.SQLiteDialect.do_execute

    def mock_do_execute(self, cursor, statement, parameters=None, context=None):
        spatial_cmds = [
            'RecoverGeometryColumn',
            'CreateSpatialIndex',
            'CheckSpatialMetaData',
            'InitSpatialMetaData',
            'CheckSpatialIndex',
        ]
        if any(cmd in statement for cmd in spatial_cmds) or statement.startswith('TRUNCATE TABLE'):
            return
        if 'AddGeometryColumn' in statement:
            match = re.search(r"AddGeometryColumn\s*\('(\w+)',\s*'(\w+)'", statement)
            if match:
                table, column = match.groups()
                try:
                    orig_do_execute(self, cursor, f'ALTER TABLE {table} ADD COLUMN {column} TEXT', None, context)
                except Exception:
                    pass
            return
        if 'GeomFromEWKT(?)' in statement:
            statement = statement.replace('GeomFromEWKT(?)', '?')
        orig_do_execute(self, cursor, statement, parameters, context)

    monkeypatch.setattr(sqlite_base.SQLiteDialect, 'do_execute', mock_do_execute)

    with app.app_context():
        StopsMatched.__table__.create(bind=db.engine, checkfirst=True)
        Problem.__table__.create(bind=db.engine, checkfirst=True)

        stop = StopsMatched(
            sloid='s1',
            stop_type='matched',
            match_type='route_gtfs_tokens',
            atlas_lat=47.0,
            atlas_lon=8.0,
            osm_node_id='n1',
            osm_lat=47.0001,
            osm_lon=8.0001,
            distance_m=8.0,
            matching_notes='test',
        )
        db.session.add(stop)
        db.session.flush()
        db.session.add(Problem(stop_id=stop.id, problem_type='contradicts_route_matching', priority=2))
        db.session.commit()

        stats = compute_db_stats(db.session)

        assert stats['contradicts_route_matching'] == 1
        assert stats['stops_with_problems'] == 1
        assert stats['clean_entries'] == 0
        assert stats['by_priority'][2]['contradicts_route_matching'] == 1

        db.session.query(Problem).delete()
        db.session.query(StopsMatched).delete()
        db.session.commit()