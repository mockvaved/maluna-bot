"""Одно предсказание в сутки, детерминированный выбор, повтор при пустом пуле."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from bot.content.schemas import Card
from bot.content.store import ContentSnapshot, load_snapshot
from bot.db.database import Database
from bot.db.repo import Repository
from bot.services.prediction import NoCardsAvailable, get_prediction, pick_card, today_msk


@pytest.fixture
async def repo(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        yield Repository(db)
    finally:
        await db.close()


def cards(count: int) -> tuple[Card, ...]:
    return tuple(
        Card(id=f"card_{index:03d}", title=f"Заголовок {index}", text="Текст")
        for index in range(1, count + 1)
    )


# ── Детерминизм ─────────────────────────────────────────────────────
def test_same_user_and_day_give_same_card() -> None:
    pool = cards(60)
    day = date(2027, 3, 14)
    assert pick_card(pool, 42, day).id == pick_card(pool, 42, day).id


def test_file_order_does_not_affect_choice() -> None:
    """Пул сортируется по id, поэтому перестановка строк ничего не меняет."""
    pool = cards(20)
    day = date(2027, 3, 14)
    assert pick_card(pool, 42, day).id == pick_card(tuple(reversed(pool)), 42, day).id


def test_different_days_usually_differ() -> None:
    pool = cards(60)
    picked = {pick_card(pool, 7, date(2027, 1, 1) + timedelta(days=offset)).id for offset in range(30)}
    assert len(picked) > 10


def test_different_users_usually_differ() -> None:
    pool = cards(60)
    day = date(2027, 3, 14)
    picked = {pick_card(pool, user_id, day).id for user_id in range(50)}
    assert len(picked) > 10


def test_empty_pool_raises() -> None:
    with pytest.raises(NoCardsAvailable):
        pick_card((), 1, date(2027, 1, 1))


# ── Одно предсказание в сутки ───────────────────────────────────────
async def test_second_press_returns_the_same_card(repo: Repository, content: ContentSnapshot) -> None:
    first = await get_prediction(repo, content, user_id=1)
    second = await get_prediction(repo, content, user_id=1)

    assert first.repeated_today is False
    assert second.repeated_today is True
    assert first.card.id == second.card.id


async def test_history_is_written_once(repo: Repository, content: ContentSnapshot) -> None:
    await get_prediction(repo, content, user_id=2)
    await get_prediction(repo, content, user_id=2)

    history = await repo.card_history(user_id=2)
    assert len(history) == 1
    assert history[0].shown_on == today_msk()


async def test_recent_cards_are_excluded(repo: Repository) -> None:
    """Показанное за последние 30 дней не выпадает повторно."""
    pool = cards(3)
    snapshot = _snapshot_with(pool)
    today = today_msk()

    await repo.remember_card(3, "card_001", today - timedelta(days=1))
    await repo.remember_card(3, "card_002", today - timedelta(days=2))

    result = await get_prediction(repo, snapshot, user_id=3)
    assert result.card.id == "card_003"


async def test_pool_exhausted_repeats_the_oldest(repo: Repository) -> None:
    """Когда всё показано за 30 дней, повторяем самое давнее."""
    pool = cards(2)
    snapshot = _snapshot_with(pool)
    today = today_msk()

    await repo.remember_card(4, "card_001", today - timedelta(days=20))
    await repo.remember_card(4, "card_002", today - timedelta(days=3))

    result = await get_prediction(repo, snapshot, user_id=4)
    assert result.card.id == "card_001"


async def test_delete_removes_everything(repo: Repository, content: ContentSnapshot) -> None:
    await repo.touch_user(9)
    await get_prediction(repo, content, user_id=9)
    await repo.log_event(9, "prediction_shown", {"card_id": "card_001"})

    await repo.delete_user(9)

    assert await repo.card_history(9) == []
    assert await repo.card_shown_on(9, today_msk()) is None


async def test_events_reject_personal_data(repo: Repository) -> None:
    """Дату рождения в статистику записать нельзя даже случайно."""
    with pytest.raises(ValueError):
        await repo.log_event(1, "astro_sign_shown", {"birth_date": "14.03"})


def _snapshot_with(pool: tuple[Card, ...]) -> ContentSnapshot:
    from bot.config import PROJECT_ROOT

    base = load_snapshot(PROJECT_ROOT / "content")
    return ContentSnapshot(
        texts=base.texts,
        replies=base.replies,
        cards=pool,
        rituals=base.rituals,
        products=base.products,
        astro=base.astro,
        faq=base.faq,
        practices=base.practices,
    )
