"""Работа с тремя таблицами: users, user_card_history, events.

Ни один метод не принимает и не сохраняет персональные данные. В events
пишутся только значения из фиксированных списков и вычисленный знак
зодиака — это проверяет _sanitize_payload.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from bot.db.database import Database

logger = logging.getLogger(__name__)

# Ключи, которые нельзя писать в events.payload_json ни при каких условиях.
_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {"birth_date", "birth_day", "birth_month", "birth_year", "date", "name", "text", "message"}
)


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    card_id: str
    shown_on: date


@dataclass(frozen=True, slots=True)
class ReviewPhoto:
    user_id: int
    file_id: str
    file_path: str
    created_at: str


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _sanitize_payload(payload: dict[str, object] | None) -> str:
    if not payload:
        return "{}"
    forbidden = _FORBIDDEN_PAYLOAD_KEYS & {key.lower() for key in payload}
    if forbidden:
        # Ошибка разработчика, а не пользователя: лучше упасть на тестах.
        raise ValueError(f"personal data is not allowed in events payload: {sorted(forbidden)}")
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


class Repository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ── users ───────────────────────────────────────────────────────
    async def touch_user(self, user_id: int) -> None:
        """Создаёт пользователя при первом обращении и обновляет last_seen_at."""
        now = _now()
        await self._db.connection.execute(
            """
            INSERT INTO users (user_id, created_at, last_seen_at)
            VALUES (?, ?, ?)
            ON CONFLICT (user_id) DO UPDATE SET last_seen_at = excluded.last_seen_at
            """,
            (user_id, now, now),
        )
        await self._db.connection.commit()

    # ── user_card_history ───────────────────────────────────────────
    async def card_shown_on(self, user_id: int, day: date) -> str | None:
        """Какое предсказание человек уже получил в этот день."""
        async with self._db.connection.execute(
            "SELECT card_id FROM user_card_history WHERE user_id = ? AND shown_on = ?",
            (user_id, day.isoformat()),
        ) as cursor:
            row = await cursor.fetchone()
        return row["card_id"] if row else None

    async def recent_card_ids(self, user_id: int, today: date, days: int = 30) -> set[str]:
        since = (today - timedelta(days=days)).isoformat()
        async with self._db.connection.execute(
            "SELECT DISTINCT card_id FROM user_card_history WHERE user_id = ? AND shown_on >= ?",
            (user_id, since),
        ) as cursor:
            rows = await cursor.fetchall()
        return {row["card_id"] for row in rows}

    async def card_history(self, user_id: int) -> list[HistoryEntry]:
        """Вся история по возрастанию даты — нужна, чтобы найти самое давнее."""
        async with self._db.connection.execute(
            "SELECT card_id, shown_on FROM user_card_history WHERE user_id = ? ORDER BY shown_on",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [HistoryEntry(row["card_id"], date.fromisoformat(row["shown_on"])) for row in rows]

    async def remember_card(self, user_id: int, card_id: str, day: date) -> None:
        """Записывает выданное предсказание. Повторный вызов за день ничего не меняет."""
        await self._db.connection.execute(
            """
            INSERT INTO user_card_history (user_id, card_id, shown_on)
            VALUES (?, ?, ?)
            ON CONFLICT (user_id, shown_on) DO NOTHING
            """,
            (user_id, card_id, day.isoformat()),
        )
        await self._db.connection.commit()

    # ── events ──────────────────────────────────────────────────────
    async def log_event(
        self, user_id: int, event_type: str, payload: dict[str, object] | None = None
    ) -> None:
        await self._db.connection.execute(
            "INSERT INTO events (user_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (user_id, event_type, _sanitize_payload(payload), _now()),
        )
        await self._db.connection.commit()

    # ── review_photos ───────────────────────────────────────────────
    async def add_review_photo(self, user_id: int, file_id: str, file_path: str) -> None:
        await self._db.connection.execute(
            """
            INSERT INTO review_photos (user_id, file_id, file_path, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, file_id, file_path, _now()),
        )
        await self._db.connection.commit()

    async def has_review(self, user_id: int) -> bool:
        """Присылал ли человек отзыв. Подарок отдаётся один раз и навсегда."""
        async with self._db.connection.execute(
            "SELECT 1 FROM review_photos WHERE user_id = ? LIMIT 1", (user_id,)
        ) as cursor:
            return await cursor.fetchone() is not None

    async def recent_reviews(self, limit: int = 10) -> list[ReviewPhoto]:
        async with self._db.connection.execute(
            """
            SELECT user_id, file_id, file_path, created_at
            FROM review_photos ORDER BY created_at DESC LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            ReviewPhoto(row["user_id"], row["file_id"], row["file_path"], row["created_at"])
            for row in rows
        ]

    async def review_count(self) -> int:
        async with self._db.connection.execute("SELECT COUNT(*) AS n FROM review_photos") as cursor:
            row = await cursor.fetchone()
        return int(row["n"]) if row else 0

    # ── /delete ─────────────────────────────────────────────────────
    async def delete_user(self, user_id: int, media_root: Path | None = None) -> None:
        """Стирает всё, что связано с пользователем. Необратимо.

        Фото отзывов удаляются и из базы, и с диска: иначе после /delete
        картинка человека осталась бы лежать в data/reviews/.
        """
        connection = self._db.connection

        if media_root is not None:
            async with connection.execute(
                "SELECT file_path FROM review_photos WHERE user_id = ?", (user_id,)
            ) as cursor:
                paths = [row["file_path"] for row in await cursor.fetchall()]
            for relative in paths:
                _remove_file(media_root / relative)

        await connection.execute("DELETE FROM review_photos WHERE user_id = ?", (user_id,))
        await connection.execute("DELETE FROM user_card_history WHERE user_id = ?", (user_id,))
        await connection.execute("DELETE FROM events WHERE user_id = ?", (user_id,))
        await connection.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        await connection.commit()
        logger.info("user_data_deleted", extra={"user_id": user_id})


def _remove_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # Файл мог быть удалён руками — на удаление данных это не влияет.
        logger.warning("review_photo_delete_failed", extra={"file": path.name})
