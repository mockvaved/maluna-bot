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

    # ── /delete ─────────────────────────────────────────────────────
    async def delete_user(self, user_id: int) -> None:
        """Стирает всё, что связано с пользователем. Необратимо."""
        connection = self._db.connection
        await connection.execute("DELETE FROM user_card_history WHERE user_id = ?", (user_id,))
        await connection.execute("DELETE FROM events WHERE user_id = ?", (user_id,))
        await connection.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        await connection.commit()
        logger.info("user_data_deleted", extra={"user_id": user_id})
