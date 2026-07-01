from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row


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
        self.db_uri = (
            f"postgresql://{DB_CONFIG['user']}:"
            f"{DB_CONFIG['password']}@"
            f"{DB_CONFIG['host']}:"
            f"{DB_CONFIG['port']}/"
            f"{DB_CONFIG['database']}"
        )

        # autocommit=True: psycopg3에서 conn.transaction() 블록을 BEGIN/COMMIT으로
        # 동작시키려면 연결이 autocommit 모드여야 한다. autocommit=False이면
        # conn.transaction()이 SAVEPOINT를 생성(중첩 트랜잭션)하므로 의도와 다르게 동작한다.
        # 단일 DML(execute/fetch_*)은 각각 자동 커밋된다.
        # 여러 DML을 원자적으로 처리해야 할 때는 반드시 db.transaction()을 사용한다.
        self.pool = ConnectionPool(
            conninfo=self.db_uri,
            min_size=1,
            max_size=10,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
            },
            open=True,
        )

    def execute(self, query: str, params: tuple = None) -> int:
        """
        INSERT, UPDATE, DELETE
        반환값: 영향받은 row 수
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.rowcount

    def fetch_one(self, query: str, params: tuple = None):
        """
        단건 조회
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchone()

    def fetch_all(self, query: str, params: tuple = None):
        """
        다건 조회
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchall()

    def execute_many(self, query: str, params_list: list[tuple]) -> None:
        """
        배치 INSERT / UPDATE
        """
        with self.pool.connection() as conn:
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
        with self.pool.connection() as conn:
            with conn.transaction():
                yield conn

    def close(self):
        """
        애플리케이션 종료 시 호출
        """
        if self.pool:
            self.pool.close()