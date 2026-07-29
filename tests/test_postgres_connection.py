from storage.postgres import connection


class _Cursor:
    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchone(self):
        return {"value": 1}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _DirectConnection:
    def cursor(self):
        return _Cursor()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_windows_cli_uses_direct_connection_when_pool_workers_are_unavailable(
    monkeypatch,
):
    connection.Singleton._instances.clear()
    calls = []

    def connect(*args, **kwargs):
        calls.append((args, kwargs))
        return _DirectConnection()

    monkeypatch.setattr(connection.os, "name", "nt")
    monkeypatch.setattr(connection.psycopg, "connect", connect)
    try:
        db = connection.PostgreDB(
            {
                "host": "localhost",
                "port": 5433,
                "user": "admin",
                "password": "test-password",
                "database": "quantpilot_db",
            }
        )

        assert db.pool is None
        assert db.fetch_one("SELECT 1 AS value") == {"value": 1}
        assert calls[0][1]["autocommit"] is True
        assert calls[0][1]["row_factory"] is connection.dict_row
    finally:
        connection.Singleton._instances.clear()
