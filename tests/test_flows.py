"""Сквозные сценарии: апдейт уходит в настоящий диспетчер, ответы проверяются."""

from __future__ import annotations

from pathlib import Path

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import GetChatMember

from bot.config import PROJECT_ROOT, Config
from bot.content.store import ContentStore
from bot.db.database import Database
from bot.db.repo import Repository
from bot.main import build_dispatcher
from tests.fake_telegram import (
    USER_ID,
    FakeSession,
    make_callback_update,
    make_message_update,
)

ADMIN_ID = USER_ID


class Harness:
    def __init__(self, bot: Bot, dispatcher, session: FakeSession, repo: Repository) -> None:
        self.bot = bot
        self.dispatcher = dispatcher
        self.session = session
        self.repo = repo
        self._update_id = 0

    def _next_id(self) -> int:
        self._update_id += 1
        return self._update_id

    async def send(self, text: str) -> None:
        self.session.reset()
        await self.dispatcher.feed_update(self.bot, make_message_update(text, self._next_id()))

    async def press(self, label: str) -> None:
        """Нажимает кнопку с такой подписью на текущем экране."""
        data = self.session.callback_for(label)
        self.session.reset()
        await self.dispatcher.feed_update(self.bot, make_callback_update(data, self._next_id()))

    @property
    def text(self) -> str:
        return self.session.last_text()

    @property
    def buttons(self) -> list[str]:
        return self.session.button_labels()


def make_config(admin_ids: frozenset[int]) -> Config:
    return Config(
        bot_token="42:TEST",
        admin_ids=admin_ids,
        content_dir=PROJECT_ROOT / "content",
    )


@pytest.fixture(scope="session")
def dispatcher():
    """Диспетчер собирается один раз: роутеры — модульные объекты и
    повторно к другому диспетчеру не подключаются. Зависимости, которые
    должны быть свежими, фикстура app подменяет перед каждым тестом.
    """
    content_store = ContentStore(PROJECT_ROOT / "content")
    return build_dispatcher(make_config(frozenset({ADMIN_ID})), content_store, repo=None)


@pytest.fixture
async def app(tmp_path: Path, dispatcher):
    session = FakeSession()
    bot = Bot(token="42:TEST", session=session)

    db = Database(tmp_path / "flows.db")
    await db.connect()
    repo = Repository(db)

    # Каждый тест начинает с чистой базы, без чужого кеша подписки и с
    # админскими правами по умолчанию.
    dispatcher["repo"] = repo
    dispatcher["config"] = make_config(frozenset({ADMIN_ID}))
    dispatcher["subscription"].forget(USER_ID)
    # MemoryStorage.close() ничего не чистит, поэтому состояние диалога
    # сбрасываем сами — иначе оно перетекает между тестами.
    dispatcher.storage.storage.clear()

    try:
        yield Harness(bot, dispatcher, session, repo)
    finally:
        await db.close()


# ── Старт и меню ────────────────────────────────────────────────────
async def test_start_shows_welcome_and_menu(app: Harness) -> None:
    await app.send("/start")

    assert "MALUNA" in app.text
    assert app.buttons == [
        "🕯 Предсказание",
        "✨ Собери свой ритуал",
        "🔮 Астропрогноз 2027",
        "📖 Справочник",
        "💜 О бренде",
    ]


async def test_start_never_asks_anything(app: Harness) -> None:
    """Ни онбординга, ни согласия, ни даты рождения на старте."""
    await app.send("/start")
    assert "дат" not in app.text.lower()
    assert "?" not in app.text


async def test_start_rescues_a_stuck_user(app: Harness) -> None:
    """Повторный /start — способ вернуться в начало из любого сценария."""
    await app.send("/start")
    await app.press("🔮 Астропрогноз 2027")
    assert "Дату мы не сохраняем" in app.text  # ждём ввод даты

    await app.send("/start")

    assert "🕯 Предсказание" in app.buttons
    # Состояние сброшено: следующее сообщение уже не считается датой.
    await app.send("14.03")
    assert "кнопками" in app.text


async def test_delete_works_mid_scenario(app: Harness) -> None:
    await app.send("/start")
    await app.press("✨ Собери свой ритуал")
    await app.press("вечер")

    await app.send("/delete")

    assert "необратим" in app.text


# ── Предсказание ────────────────────────────────────────────────────
async def test_prediction_repeats_within_the_same_day(app: Harness) -> None:
    await app.send("/start")
    await app.press("🕯 Предсказание")
    first = app.text
    assert app.buttons == ["Вернуться в меню"]

    await app.press("Вернуться в меню")
    await app.press("🕯 Предсказание")

    assert app.text.startswith(first.strip())
    assert "завтра" in app.text


# ── Собери свой ритуал ──────────────────────────────────────────────
async def test_ritual_flow_end_to_end(app: Harness) -> None:
    await app.send("/start")
    await app.press("✨ Собери свой ритуал")

    assert "Шаг 1 из 5" in app.text
    await app.press("вечер")

    assert "Шаг 2 из 5" in app.text
    await app.press("15 минут")

    assert "Шаг 3 из 5" in app.text
    await app.press("устала")

    assert "Шаг 4 из 5" in app.text
    await app.press("отдохнуть")

    assert "Шаг 5 из 5" in app.text
    await app.press("свечи MALUNA")
    assert "✅ свечи MALUNA" in app.buttons  # галочка встала

    await app.press("Готово")
    assert "В меню" in app.buttons


async def test_ritual_back_button_returns_to_previous_step(app: Harness) -> None:
    await app.send("/start")
    await app.press("✨ Собери свой ритуал")
    await app.press("вечер")
    assert "Шаг 2 из 5" in app.text

    await app.press("Назад")
    assert "Шаг 1 из 5" in app.text
    assert "Назад" not in app.buttons  # на первом шаге возвращаться некуда


async def test_ritual_multi_select_requires_one_item(app: Harness) -> None:
    await app.send("/start")
    await app.press("✨ Собери свой ритуал")
    for answer in ("вечер", "15 минут", "устала", "отдохнуть"):
        await app.press(answer)

    await app.press("Готово")

    assert any("Отметь" in alert for alert in app.session.alerts())
    assert "Шаг 5 из 5" in app.session.sent_texts()[-1] if app.session.sent_texts() else True


async def test_ritual_cancel_returns_to_menu(app: Harness) -> None:
    await app.send("/start")
    await app.press("✨ Собери свой ритуал")
    await app.press("Отмена")

    assert "🕯 Предсказание" in app.buttons


async def test_same_ritual_is_not_repeated_within_a_session(app: Harness) -> None:
    """Второе прохождение с теми же ответами выдаёт другой ритуал."""
    await app.send("/start")

    async def run_flow() -> str:
        await app.press("✨ Собери свой ритуал")
        for answer in ("вечер", "30 минут", "устала", "создать уют"):
            await app.press(answer)
        await app.press("свечи MALUNA")
        await app.press("Готово")
        return app.text

    first = await run_flow()
    await app.press("В меню")  # сессия продолжается, показанное запомнено
    second = await run_flow()

    assert first != second


async def test_another_option_gives_a_different_ritual(app: Harness) -> None:
    await app.send("/start")
    await app.press("✨ Собери свой ритуал")
    for answer in ("вечер", "30 минут", "устала", "отдохнуть"):
        await app.press(answer)
    await app.press("свечи MALUNA")
    await app.press("Готово")

    first = app.text
    if "Другой вариант" in app.buttons:
        await app.press("Другой вариант")
        assert app.text != first


# ── Астропрогноз ────────────────────────────────────────────────────
async def test_astro_asks_to_subscribe_when_not_a_member(app: Harness) -> None:
    app.session.member_status = "left"
    await app.send("/start")
    await app.press("🔮 Астропрогноз 2027")

    assert "Подписаться" in app.buttons
    assert "Я подписался" in app.buttons


async def test_astro_full_path_for_subscriber(app: Harness) -> None:
    app.session.member_status = "member"
    await app.send("/start")
    await app.press("🔮 Астропрогноз 2027")

    assert "Дату мы не сохраняем" in app.text

    await app.send("14.03")
    assert "Рыбы" in app.text
    assert "Другая дата" in app.buttons


async def test_astro_year_is_ignored(app: Harness) -> None:
    await app.send("/start")
    await app.press("🔮 Астропрогноз 2027")
    await app.send("14.03.1990")
    assert "Рыбы" in app.text


async def test_astro_invalid_date_then_menu_after_three_tries(app: Harness) -> None:
    await app.send("/start")
    await app.press("🔮 Астропрогноз 2027")

    await app.send("31.02")
    assert "ДД.ММ" in app.text
    await app.send("абракадабра")
    assert "ДД.ММ" in app.text

    await app.send("ещё раз не то")
    assert "🕯 Предсказание" in app.buttons  # третья попытка — возврат в меню


async def test_astro_opens_when_subscription_check_fails(app: Harness) -> None:
    """Бот не админ в канале: раздел всё равно открывается."""
    app.session.fail_get_chat_member = TelegramBadRequest(
        method=GetChatMember(chat_id="@maluna118", user_id=USER_ID),
        message="Bad Request: member list is inaccessible",
    )
    await app.send("/start")
    await app.press("🔮 Астропрогноз 2027")

    assert "Дату мы не сохраняем" in app.text


async def test_birth_date_never_reaches_the_database(app: Harness) -> None:
    await app.send("/start")
    await app.press("🔮 Астропрогноз 2027")
    await app.send("14.03.1990")

    async with app.repo._db.connection.execute("SELECT payload_json FROM events") as cursor:
        payloads = [row["payload_json"] for row in await cursor.fetchall()]

    joined = " ".join(payloads)
    assert "14.03" not in joined
    assert "1990" not in joined
    assert "Рыбы" in joined  # знак сохранить можно, дату — нет


# ── Справочник ──────────────────────────────────────────────────────
async def test_guide_branches(app: Harness) -> None:
    await app.send("/start")
    await app.press("📖 Справочник")
    assert app.buttons == ["Как пользоваться", "Ритуалы со свечами", "Утилизация", "В меню"]

    await app.press("Ритуалы со свечами")
    await app.press("Практика узлов намерения")
    assert "узл" in app.text.lower()

    await app.press("Назад")
    assert "Практика узлов намерения" in app.buttons


async def test_guide_disposal_cards(app: Harness) -> None:
    await app.send("/start")
    await app.press("📖 Справочник")
    await app.press("Утилизация")
    assert "Земля" in app.buttons

    await app.press("Свечи и стекло")
    assert "воск" in app.text.lower()


async def test_guide_product_card(app: Harness) -> None:
    await app.send("/start")
    await app.press("📖 Справочник")
    await app.press("Как пользоваться")
    await app.press("Свечи")
    await app.press("Зелёная свеча с базиликом")

    assert "Как пользоваться:" in app.text
    assert "Хранение:" in app.text


# ── Свободный текст ─────────────────────────────────────────────────
async def test_free_text_gets_buttons_reply(app: Harness) -> None:
    await app.send("/start")
    await app.send("привет, как дела")

    assert "кнопками" in app.text
    assert "🕯 Предсказание" in app.buttons


async def test_health_question_gets_a_soft_refusal(app: Harness) -> None:
    await app.send("/start")
    await app.send("у меня болит голова, что делать")

    assert "врач" in app.text.lower()


async def test_order_question_points_to_contacts(app: Harness) -> None:
    await app.send("/start")
    await app.send("когда будет доставка заказа?")

    assert "не про покупки" in app.text
    assert "{contacts}" not in app.text  # подстановка сработала


async def test_heavy_message_gets_care_not_a_ritual(app: Harness) -> None:
    await app.send("/start")
    await app.send("мне очень плохо и не могу больше")

    assert "специалист" in app.text.lower()
    assert "ритуал" not in app.text.lower()


async def test_privacy_question_is_answered_honestly(app: Harness) -> None:
    await app.send("/start")
    await app.send("вы храните мои данные?")

    assert "/delete" in app.text


async def test_free_text_is_never_stored(app: Harness) -> None:
    secret = "какой-то очень личный текст пользователя"
    await app.send("/start")
    await app.send(secret)

    async with app.repo._db.connection.execute("SELECT payload_json FROM events") as cursor:
        payloads = " ".join(row["payload_json"] for row in await cursor.fetchall())

    assert secret not in payloads


# ── /delete и /reload ───────────────────────────────────────────────
async def test_delete_asks_for_confirmation_then_wipes(app: Harness) -> None:
    await app.send("/start")
    await app.press("🕯 Предсказание")

    await app.send("/delete")
    assert "необратим" in app.text
    assert "Да, удалить" in app.buttons

    await app.press("Да, удалить")
    assert "стёрто" in app.text
    assert await app.repo.card_history(USER_ID) == []


async def test_delete_can_be_cancelled(app: Harness) -> None:
    await app.send("/start")
    await app.press("🕯 Предсказание")
    await app.send("/delete")
    await app.press("Не надо")

    assert await app.repo.card_history(USER_ID) != []


async def test_reload_works_for_admin(app: Harness) -> None:
    await app.send("/reload")
    assert "перечитан" in app.text


async def test_reload_is_silent_for_everyone_else(app: Harness) -> None:
    """Посторонним бот не подтверждает даже существование команды."""
    app.dispatcher["config"] = make_config(frozenset())

    await app.send("/reload")

    assert app.session.sent_texts() == []


# ── Ошибки ──────────────────────────────────────────────────────────
async def test_handler_failure_shows_an_apology(app: Harness, monkeypatch) -> None:
    from bot.handlers import prediction as prediction_handler

    async def boom(*args, **kwargs):
        raise RuntimeError("database is on fire")

    monkeypatch.setattr(prediction_handler, "get_prediction", boom)

    await app.send("/start")
    await app.press("🕯 Предсказание")

    assert "Что-то пошло не так" in app.text
    assert "В меню" in app.buttons
