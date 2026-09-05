"""Выбор предсказания: одно в календарные сутки по московскому времени.

Порядок (ТЗ, раздел 7):
  1. Если на сегодня предсказание уже выдано — показываем то же самое.
  2. Иначе берём активные карточки минус показанные за 30 дней.
  3. Если пул пуст — разрешаем повтор самой давней и пишем warning.
  4. Выбор детерминированный: seed = hash(user_id + дата).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from bot.content.schemas import Card
from bot.content.store import ContentSnapshot
from bot.db.repo import Repository

logger = logging.getLogger(__name__)

MOSCOW = ZoneInfo("Europe/Moscow")
HISTORY_WINDOW_DAYS = 30


class NoCardsAvailable(RuntimeError):
    """В cards.yaml нет ни одной активной карточки."""


@dataclass(frozen=True, slots=True)
class PredictionResult:
    card: Card
    repeated_today: bool


def today_msk() -> date:
    """Календарная дата в Europe/Moscow. Сброс предсказания в 00:00 МСК."""
    return datetime.now(tz=MOSCOW).date()


def pick_card(cards: tuple[Card, ...], user_id: int, day: date) -> Card:
    """Детерминированный выбор: одинаковый user_id и дата дают одну карточку.

    Пул сортируется по id, чтобы порядок строк в файле не влиял на выбор.
    """
    if not cards:
        raise NoCardsAvailable("no active cards to choose from")
    pool = sorted(cards, key=lambda card: card.id)
    digest = hashlib.sha256(f"{user_id}:{day.isoformat()}".encode()).digest()
    return pool[int.from_bytes(digest[:8], "big") % len(pool)]


async def get_prediction(
    repo: Repository, content: ContentSnapshot, user_id: int
) -> PredictionResult:
    day = today_msk()
    active = content.active_cards
    if not active:
        raise NoCardsAvailable("cards file has no active entries")

    # 1. Уже получал сегодня — отдаём ровно ту же карточку.
    shown_id = await repo.card_shown_on(user_id, day)
    if shown_id is not None:
        card = content.card(shown_id)
        if card is not None:
            return PredictionResult(card=card, repeated_today=True)
        # Карточку удалили из файла после выдачи — выбираем заново на тот же день.
        logger.warning("shown_card_missing_in_content", extra={"card_id": shown_id})

    # 2. Исключаем показанное за последние 30 дней.
    recent = await repo.recent_card_ids(user_id, day, HISTORY_WINDOW_DAYS)
    pool = tuple(card for card in active if card.id not in recent)

    # 3. Пул опустел — разрешаем повтор самого давнего.
    if not pool:
        logger.warning(
            "prediction_pool_empty",
            extra={"user_id": user_id, "active_cards": len(active)},
        )
        pool = await _oldest_first(repo, active, user_id)

    card = pick_card(pool, user_id, day)
    await repo.remember_card(user_id, card.id, day)
    return PredictionResult(card=card, repeated_today=False)


async def _oldest_first(
    repo: Repository, active: tuple[Card, ...], user_id: int
) -> tuple[Card, ...]:
    """Карточки, показанные дальше всего в прошлом, — кандидаты на повтор."""
    history = await repo.card_history(user_id)
    last_shown: dict[str, date] = {}
    for entry in history:
        # История отсортирована по возрастанию, поэтому в итоге останется последняя дата.
        last_shown[entry.card_id] = entry.shown_on
    if not last_shown:
        return active

    oldest = min(last_shown[card.id] for card in active if card.id in last_shown)
    candidates = tuple(
        card for card in active if card.id in last_shown and last_shown[card.id] == oldest
    )
    return candidates or active
