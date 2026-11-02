from backend.app import _database_engine_options
from backend.db_errors import is_database_timeout_error


def test_postgresql_web_connections_have_bounded_waits(monkeypatch):
    monkeypatch.setenv('WEB_DB_CONNECT_TIMEOUT_SECONDS', '7')
    monkeypatch.setenv('WEB_DB_LOCK_TIMEOUT_MS', '2500')
    monkeypatch.setenv('WEB_DB_STATEMENT_TIMEOUT_MS', '24000')

    options = _database_engine_options(
        'postgresql+psycopg://user:password@db:5432/import_db'
    )

    assert options == {
        'pool_pre_ping': True,
        'connect_args': {
            'connect_timeout': 7,
            'options': '-c lock_timeout=2500 -c statement_timeout=24000',
        },
    }


def test_non_postgresql_connections_do_not_receive_postgres_options():
    assert _database_engine_options('sqlite:///:memory:') == {}


def test_database_timeout_detection_follows_wrapped_driver_error():
    class _DriverTimeout(Exception):
        sqlstate = '57014'

    class _WrappedError(Exception):
        def __init__(self):
            super().__init__('query failed')
            self.orig = _DriverTimeout('statement canceled')

    assert is_database_timeout_error(_WrappedError()) is True
    assert is_database_timeout_error(RuntimeError('ordinary database failure')) is False
