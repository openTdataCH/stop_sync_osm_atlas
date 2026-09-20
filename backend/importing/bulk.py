"""COPY complete snapshot rows using the staging connection's transaction."""
from collections import defaultdict

from psycopg import sql
from psycopg.types.json import Jsonb
from sqlalchemy import JSON


def copy_rows(session, model, rows):
    schema = session.info.get('snapshot_schema')
    if not schema:
        raise ValueError('COPY requires an isolated snapshot schema')
    table = model.__table__
    columns = {column.key: column for column in table.columns}
    # Preserve server defaults for omitted values, including nullable booleans.
    # Group rows by supplied columns rather than turning omissions into NULL.
    groups = defaultdict(list)
    for row in rows:
        unknown = row.keys() - columns.keys()
        if unknown:
            raise ValueError(f'Unknown columns for {table.name}: {sorted(unknown)}')
        keys = tuple(key for key in columns if key in row and not (
            row[key] is None and (columns[key].server_default is not None or columns[key].default is not None)))
        groups[keys].append(row)
    connection = session.connection().connection.driver_connection
    with connection.cursor() as cursor:
        for keys, group in groups.items():
            statement = sql.SQL('COPY {}.{} ({}) FROM STDIN').format(
                sql.Identifier(schema), sql.Identifier(table.name),
                sql.SQL(', ').join(map(sql.Identifier, keys)))
            json_keys = {key for key in keys if isinstance(columns[key].type, JSON)}
            with cursor.copy(statement) as copier:
                for row in group:
                    copier.write_row(tuple(Jsonb(row[key]) if key in json_keys else row[key] for key in keys))
