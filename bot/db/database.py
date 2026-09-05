"""Подключение к SQLite и применение миграций."""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from bot.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


class Database:
    """Одно соединение на процесс: у SQLite так меньше поводов для блокировок."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._connection: aiosqlite.Connection | None = None

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("Database is not connected. Call connect() first.")
        return self._connection

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self._path)
        self._connection.row_factory = aiosqlite.Row
        # WAL спокойнее переносит одновременные чтение и запись.
        await self._connection.execute("PRAGMA journal_mode=WAL")
        await self._connection.execute("PRAGMA foreign_keys=ON")
        await self._connection.commit()
        await self.migrate()
        logger.info("db_connected", extra={"db_path": str(self._path)})

    async def migrate(self) -> None:
        """Прогоняет все .sql из migrations/ по возрастанию имени.

        Файлы пишутся идемпотентно (CREATE TABLE IF NOT EXISTS), поэтому
        отдельная таблица версий не нужна.
        """
        if not MIGRATIONS_DIR.is_dir():
            logger.warning("migrations_dir_missing", extra={"path": str(MIGRATIONS_DIR)})
            return
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            await self.connection.executescript(migration.read_text(encoding="utf-8"))
            await self.connection.commit()
            logger.info("migration_applied", extra={"migration": migration.name})

    async def healthy(self) -> bool:
        try:
            await self.connection.execute("SELECT 1")
            return True
        except Exception:  # noqa: BLE001 — health-check не должен падать сам
            logger.exception("db_health_check_failed")
            return False

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
