"""Name matching methods and OSM stop units after the evidence they use.

Match types name their rule and branch (``uic_reference_one_osm``,
``gtfs_shared_route``, ``local_ref_distance``), and OSM stop units name their
PTv2 layout (``ptv2_two_sided_stop`` with ``middle`` and ``side`` members).
Stored rows are rewritten in place; the reference and name branches are read
from the stored matching notes.
"""

from alembic import op
import sqlalchemy as sa

revision = '20261106_000010'
down_revision = '20261102_000009'
branch_labels = None
depends_on = None

MATCH_TYPES = {
    'distance_matching_trio': 'uic_two_sided_stop',
    'distance_matching_1_uic_ref': 'uic_ref_group_distance',
    'distance_matching_1_uic_name': 'uic_name_group_distance',
    'distance_matching_1_name': 'name_group_distance',
    'long_distance_group_proximity_uic_ref': 'uic_ref_group_long_distance',
    'long_distance_group_proximity_uic_name': 'uic_name_group_long_distance',
    'long_distance_group_proximity_name': 'name_group_long_distance',
    'distance_matching_2': 'local_ref_distance',
    'distance_matching_3a': 'distance_only_candidate',
    'distance_matching_3a_second_pass': 'distance_only_candidate_second_pass',
    'distance_matching_3b': 'distance_ratio',
    'route_gtfs_tokens': 'gtfs_shared_route',
    'route_gtfs_direction': 'gtfs_shared_direction',
    'duplicate_propagation': 'source_duplicate_propagation',
    'osm_group_propagation': 'osm_pair_propagation',
}
REFERENCE_NOTES = {
    'Single OSM element for station reference': ('uic_reference_one_osm', 'One OSM element carries the station reference'),
    'Single source stop matched to multiple OSM elements': ('uic_reference_one_source', 'One source stop carries the station reference'),
    'Exact compatible reference and platform code': ('uic_reference_local_ref', 'Reference and platform code equal to local_ref'),
}
STOP_KINDS = {'trio': 'two_sided_stop'}
GROUP_KINDS = {
    'osm_pair_uic': 'ptv2_pair_uic_ref',
    'osm_pair_uic_equal_15m': 'ptv2_pair_uic_ref_equal_count',
    'osm_pair_name': 'ptv2_pair_name',
    'osm_pair_name_equal_15m': 'ptv2_pair_name_equal_count',
    'osm_pair_tram': 'tram_stop_pair',
    'osm_pair_tram_equal_15m': 'tram_stop_pair_equal_count',
    'osm_trio': 'ptv2_two_sided_stop',
}
MEMBER_ROLES = {'trio_middle': 'middle', 'trio_side': 'side'}

CONSTRAINTS = {
    'old': (
        "stop_kind IN ('single', 'pair', 'trio')",
        "group_kind IS NULL OR group_kind IN ('osm_pair_uic', 'osm_pair_name', 'osm_pair_tram', "
        "'osm_pair_uic_equal_15m', 'osm_pair_name_equal_15m', 'osm_pair_tram_equal_15m', 'osm_trio')",
        "member_role IN ('single', 'pair_a', 'pair_b', 'trio_middle', 'trio_side')",
    ),
    'new': (
        "stop_kind IN ('single', 'pair', 'two_sided_stop')",
        "group_kind IS NULL OR group_kind IN ('ptv2_pair_uic_ref', 'ptv2_pair_name', 'tram_stop_pair', "
        "'ptv2_pair_uic_ref_equal_count', 'ptv2_pair_name_equal_count', 'tram_stop_pair_equal_count', 'ptv2_two_sided_stop')",
        "member_role IN ('single', 'pair_a', 'pair_b', 'middle', 'side')",
    ),
}


def _sql_text(value):
    return "'" + value.replace("'", "''") + "'"


def _rename(table, column, mapping):
    for old, new in mapping.items():
        op.execute(f"UPDATE {table} SET {column} = {_sql_text(new)} WHERE {column} = {_sql_text(old)}")


def _drop_constraints():
    op.drop_constraint('ck_osm_stops_stop_kind', 'osm_stops', type_='check')
    op.drop_constraint('ck_osm_stops_group_kind', 'osm_stops', type_='check')
    op.drop_constraint('ck_osm_stop_members_member_role', 'osm_stop_members', type_='check')


def _create_constraints(stop_kind, group_kind, member_role):
    op.create_check_constraint('ck_osm_stops_stop_kind', 'osm_stops', stop_kind)
    op.create_check_constraint('ck_osm_stops_group_kind', 'osm_stops', group_kind)
    op.create_check_constraint('ck_osm_stop_members_member_role', 'osm_stop_members', member_role)


def upgrade(engine_name=None):
    if engine_name not in ('', None):
        return
    _drop_constraints()
    _rename('osm_stops', 'stop_kind', STOP_KINDS)
    _rename('osm_stops', 'group_kind', GROUP_KINDS)
    _rename('osm_stop_members', 'member_role', MEMBER_ROLES)
    _create_constraints(*CONSTRAINTS['new'])
    _rename('stops_matched', 'match_type', MATCH_TYPES)
    # The baseline builds tables from the current models, which no longer have
    # matching_notes (dropped in 000011). Such fresh databases are empty, so
    # the note-based renames have nothing to rewrite.
    existing = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('stops_matched')}
    if 'matching_notes' in existing:
        for old_notes, (match_type, notes) in REFERENCE_NOTES.items():
            op.execute(
                f"UPDATE stops_matched SET match_type = {_sql_text(match_type)}, matching_notes = {_sql_text(notes)} "
                f"WHERE match_type = 'exact' AND matching_notes = {_sql_text(old_notes)}"
            )
        op.execute("UPDATE stops_matched SET match_type = 'name_one_osm' "
                   "WHERE match_type = 'name' AND matching_notes = 'Name index match (1 candidates)'")
    op.execute("UPDATE stops_matched SET match_type = 'name_local_ref' WHERE match_type = 'name'")


def downgrade(engine_name=None):
    if engine_name not in ('', None):
        return
    _drop_constraints()
    _rename('osm_stops', 'stop_kind', {new: old for old, new in STOP_KINDS.items()})
    _rename('osm_stops', 'group_kind', {new: old for old, new in GROUP_KINDS.items()})
    _rename('osm_stop_members', 'member_role', {new: old for old, new in MEMBER_ROLES.items()})
    _create_constraints(*CONSTRAINTS['old'])
    _rename('stops_matched', 'match_type', {new: old for old, new in MATCH_TYPES.items()})
    for old_notes, (match_type, notes) in REFERENCE_NOTES.items():
        op.execute(
            f"UPDATE stops_matched SET match_type = 'exact', matching_notes = {_sql_text(old_notes)} "
            f"WHERE match_type = {_sql_text(match_type)}"
        )
    op.execute("UPDATE stops_matched SET match_type = 'name' WHERE match_type IN ('name_one_osm', 'name_local_ref')")
