import os
from contextlib import contextmanager

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from psycopg_pool import PoolTimeout


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(
                *args, **kwargs
            )
        return cls._instances[cls]


class PostgreDB(metaclass=Singleton):
    def __init__(self, DB_CONFIG: dict):
        self._connection_kwargs = {
            "host": DB_CONFIG["host"],
            "port": DB_CONFIG["port"],
            "user": DB_CONFIG["user"],
            "password": DB_CONFIG["password"],
            "dbname": DB_CONFIG["database"],
            "connect_timeout": 5,
        }
        # Build a quoted conninfo string instead of interpolating a password.
        # PostgreSQL passwords commonly contain @, :, /, or #, each of which
        # changes the meaning of a hand-built URI.
        self.db_uri = make_conninfo(**self._connection_kwargs)

        # autocommit=True: psycopg3에서 conn.transaction() 블록을 BEGIN/COMMIT으로
        # 동작시키려면 연결이 autocommit 모드여야 한다. autocommit=False이면
        # conn.transaction()이 SAVEPOINT를 생성(중첩 트랜잭션)하므로 의도와 다르게 동작한다.
        # 단일 DML(execute/fetch_*)은 각각 자동 커밋된다.
        # 여러 DML을 원자적으로 처리해야 할 때는 반드시 db.transaction()을 사용한다.
        self.pool: ConnectionPool | None = None
        # psycopg_pool worker threads can fail to establish connections on the
        # Windows host runtime even though a direct psycopg connection succeeds.
        # Linux containers retain pooling; Windows CLI jobs use the same direct
        # autocommit and dict-row semantics.
        if os.name != "nt":
            candidate = ConnectionPool(
                conninfo=self.db_uri,
                min_size=1,
                max_size=10,
                kwargs={
                    "autocommit": True,
                    "row_factory": dict_row,
                },
                open=False,
            )
            try:
                candidate.open(wait=True, timeout=5)
            except (OSError, psycopg.Error, PoolTimeout):
                candidate.close(timeout=1)
            else:
                self.pool = candidate

    @contextmanager
    def _connection(self):
        """Yield a pooled connection when healthy, otherwise a direct one."""
        if self.pool is not None:
            try:
                with self.pool.connection() as conn:
                    yield conn
                    return
            except PoolTimeout:
                self.pool.close(timeout=1)
                self.pool = None
        with psycopg.connect(
            **self._connection_kwargs,
            autocommit=True,
            row_factory=dict_row,
        ) as conn:
            yield conn

    def execute(self, query: str, params: tuple = None) -> int:
        """
        INSERT, UPDATE, DELETE
        반환값: 영향받은 row 수
        """
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.rowcount

    def fetch_one(self, query: str, params: tuple = None):
        """
        단건 조회
        """
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchone()

    def fetch_all(self, query: str, params: tuple = None):
        """
        다건 조회
        """
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchall()

    def execute_many(self, query: str, params_list: list[tuple]) -> None:
        """
        배치 INSERT / UPDATE. 전체 배치를 하나의 트랜잭션으로 처리한다.
        """
        with self._connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.executemany(query, params_list)

    @contextmanager
    def transaction(self):
        """
        멀티 스텝 원자 처리 (INSERT + UPDATE 등)
        with db.transaction() as conn:
            conn.execute(sql1, params1)
            conn.execute(sql2, params2)
        """
        with self._connection() as conn:
            with conn.transaction():
                yield conn

    def close(self):
        """
        애플리케이션 종료 시 호출
        """
        if self.pool:
            self.pool.close()
            self.pool = None
