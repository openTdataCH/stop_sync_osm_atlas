"""The migrations build exactly the schema of backend/models.py."""
import importlib

from sqlalchemy import text


def _model_objects_only(obj, name, type_, reflected, compare_to):
    # Tables only the database has belong to PostGIS and its extensions.
    from geoalchemy2 import alembic_helpers

    if type_ == 'table' and reflected and compare_to is None:
        return False
    return alembic_helpers.include_object(obj, name, type_, reflected, compare_to)


def test_upgrading_an_empty_database_gives_the_model_schema(postgres):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from backend.extensions import db

    schema = importlib.import_module('migrations.versions.0001_schema')
    with postgres.begin() as connection:
        connection.execute(text('DROP SCHEMA public CASCADE'))
        connection.execute(text('CREATE SCHEMA public'))
        with Operations.context(MigrationContext.configure(connection)):
            schema.upgrade()
        context = MigrationContext.configure(
            connection, opts={'include_object': _model_objects_only, 'compare_type': True})
        assert compare_metadata(context, db.Model.metadata) == []
