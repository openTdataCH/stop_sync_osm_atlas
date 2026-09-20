"""Preserve external source identifiers without legacy ATLAS length limits."""

from alembic import op
import sqlalchemy as sa

revision = '20260911_000006'
down_revision = '20260911_000005'
branch_labels = None
depends_on = None

# Retain ordinary names, statuses, numeric OSM IDs and generated run IDs at
# their existing sizes. Selected display fields also hold raw-ID fallbacks.
COLUMNS = {
    'stops_matched': {'sloid': 100},
    'atlas_stops': {'sloid': 100, 'representative_sloid': 100, 'uic_ref': 100},
    'gtfs_stops_raw': {'stop_id': 255, 'original_stop_id': 255, 'parent_station': 255},
    'gtfs_stop_identity_resolution': {'stop_id': 255, 'resolved_sloid': 100},
    'atlas_line_families': {'atlas_line_id': 100, 'route_id_normalized': 100, 'agency_id': 100},
    'osm_route_relations': {
        'gtfs_route_id': 255, 'gtfs_trip_id': 255, 'gtfs_trip_id_sample': 255,
        'gtfs_shape_id': 255, 'synthetic_family_key': 255,
    },
    'line_families': {
        'source_family_id': 255, 'display_route_id': 255, 'gtfs_route_id': 255,
        'normalized_route_id': 255, 'atlas_line_id': 100, 'public_name': 255, 'operator': 255,
    },
    'itineraries': {'source_itinerary_id': 255, 'display_name': 255},
    'stop_calls': {'source_stop_id': 255, 'source_sloid': 100, 'canonical_stop_key': 255, 'uic_ref': 100, 'stop_label': 255},
}


def upgrade(engine_name=None):
    if engine_name not in ('', None):
        return
    for table, columns in COLUMNS.items():
        for column, old_length in columns.items():
            op.alter_column(table, column, existing_type=sa.String(old_length), type_=sa.Text())


def downgrade(engine_name=None):
    if engine_name not in ('', None):
        return
    # Never shorten identifiers silently. A downgrade is only safe when all
    # existing values fit the previous schema, including every FK reference.
    connection = op.get_bind()
    for table, columns in COLUMNS.items():
        for column, old_length in columns.items():
            if connection.execute(sa.text(
                f'SELECT EXISTS (SELECT 1 FROM "{table}" WHERE length("{column}") > :limit)'
            ), {'limit': old_length}).scalar():
                raise RuntimeError(f'Cannot downgrade: {table}.{column} contains identifiers longer than {old_length}')
    for table, columns in reversed(list(COLUMNS.items())):
        for column, old_length in columns.items():
            op.alter_column(table, column, existing_type=sa.Text(), type_=sa.String(old_length))
