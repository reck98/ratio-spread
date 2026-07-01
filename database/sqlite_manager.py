import sqlite3
from pathlib import Path
from threading import Lock


class SQLiteManager:
    _instance: "SQLiteManager | None" = None
    _connection: sqlite3.Connection | None = None
    _lock: Lock = Lock()

    def __new__(cls) -> "SQLiteManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def initialize(self, db_path: str, schema_path: str = "database/schema.sql") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL;")
        self._connection.execute("PRAGMA foreign_keys = ON;")

        schema_file = Path(schema_path)
        if schema_file.exists():
            with open(schema_file, "r") as f:
                self._connection.executescript(f.read())

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._connection

    def execute(self, query: str, params: tuple[object, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.connection.execute(query, params)

    def executemany(self, query: str, params: list[tuple[object, ...]]) -> sqlite3.Cursor:
        with self._lock:
            return self.connection.executemany(query, params)

    def commit(self) -> None:
        with self._lock:
            self.connection.commit()

    def close(self) -> None:
        if self._connection:
            self._connection.close()
            self._connection = None
