"""🔮 Астропрогноз 2027 — единственный раздел, где спрашивается дата рождения.

Порядок: проверка подписки на канал → ввод даты → прогноз.

Дата живёт только в аргументе функции: она приходит сообщением, из неё
считается знак, и дальше в состоянии хранится строка-знак. Ни в FSM, ни в
базу, ни в логи дата не попадает (ТЗ, раздел 9).
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.content.store import ContentSnapshot, ContentStore
from bot.db.repo import Repository
from bot.handlers.common import render, reset_flow, show_main_menu, show_screen, user_id_of
from bot.keyboards.builders import astro_cancel, astro_result, only_menu, subscribe_gate
from bot.keyboards.callbacks import AstroCB, MenuCB
from bot.services.subscription import SubscriptionChecker
from bot.services.zodiac import InvalidDate, find_sign, parse_day_month
from bot.states import KEY_ATTEMPTS, AstroFlow

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

router = Router(name="astro")


@router.callback_query(MenuCB.filter(F.section == "astro"))
async def enter_section(
    callback: CallbackQuery,
    state: FSMContext,
    content_store: ContentStore,
    repo: Repository,
    config: Config,
    subscription: SubscriptionChecker,
) -> None:
    await callback.answer()
    await repo.log_event(user_id_of(callback), "astro_opened")
    await _gate(callback, state, content_store.current, config, subscription, use_cache=True)


@router.callback_query(AstroCB.filter(F.action == "check"))
async def recheck_subscription(
    callback: CallbackQuery,
    state: FSMContext,
    content_store: ContentStore,
    config: Config,
    subscription: SubscriptionChecker,
) -> None:
    """Кнопка «Я подписался»: спрашиваем Telegram заново, минуя кеш."""
    await callback.answer()
    subscription.forget(user_id_of(callback))
    await _gate(callback, state, content_store.current, config, subscription, use_cache=False)


@router.callback_query(AstroCB.filter(F.action == "again"))
async def another_date(
    callback: CallbackQuery, state: FSMContext, content_store: ContentStore
) -> None:
    await callback.answer()
    await _ask_date(callback, state, content_store.current)


@router.message(AstroFlow.waiting_for_date)
async def receive_date(
    message: Message, state: FSMContext, content_store: ContentStore, repo: Repository
) -> None:
    content = content_store.current
    texts = content.texts
    raw = message.text or ""

    try:
        day_month = parse_day_month(raw)
    except InvalidDate:
        await _handle_bad_date(message, state, content)
        return

    sign = find_sign(content.astro, day_month)
    # Дальше day_month больше не нужен и никуда не сохраняется.
    del day_month

    if sign is None:
        logger.warning("zodiac_sign_not_found")
        await _handle_bad_date(message, state, content)
        return

    await reset_flow(state)
    # В логи и события уходит только вычисленный знак, никогда не дата.
    await repo.log_event(user_id_of(message), "astro_sign_shown", {"sign": sign.sign})
    logger.info("astro_sign_shown", extra={"user_id": user_id_of(message), "sign": sign.sign})

    body = render(texts.astro.forecast, title=sign.title, text=sign.text.strip()).strip()
    products = [pid for pid in sign.product_ids if content.product(pid) is not None]
    if products:
        body = f"{body}\n\n{texts.astro.product_header}"
    await show_screen(message, body, astro_result(texts, content, products))


# ── Внутренняя механика ─────────────────────────────────────────────
async def _gate(
    callback: CallbackQuery,
    state: FSMContext,
    content: ContentSnapshot,
    config: Config,
    subscription: SubscriptionChecker,
    *,
    use_cache: bool,
) -> None:
    texts = content.texts
    if callback.bot is None:
        return

    state_result = await subscription.check(
        callback.bot, user_id_of(callback), use_cache=use_cache
    )
    if state_result.allowed:
        if state_result.check_failed:
            # Бот не админ в канале: не ломаем раздел, но помечаем в логах.
            logger.warning("astro_opened_without_check", extra={"user_id": user_id_of(callback)})
        await _ask_date(callback, state, content)
        return

    text = texts.astro.subscribe_required if use_cache else texts.astro.not_subscribed_yet
    await show_screen(callback, text.strip(), subscribe_gate(texts, config.channel_url))


async def _ask_date(
    callback: CallbackQuery, state: FSMContext, content: ContentSnapshot
) -> None:
    texts = content.texts
    if not content.astro:
        await show_screen(callback, texts.guide.empty_section, only_menu(texts))
        return

    await state.set_state(AstroFlow.waiting_for_date)
    await state.update_data({KEY_ATTEMPTS: 0})
    body = f"{texts.astro.ask_date.strip()}\n\n{texts.astro.privacy_note}"
    await show_screen(callback, body, astro_cancel(texts))


async def _handle_bad_date(
    message: Message, state: FSMContext, content: ContentSnapshot
) -> None:
    texts = content.texts
    data = await state.get_data()
    attempts = int(data.get(KEY_ATTEMPTS, 0)) + 1

    if attempts >= MAX_ATTEMPTS:
        await reset_flow(state)
        await show_main_menu(message, texts, prefix=texts.astro.too_many_attempts)
        return

    await state.update_data({KEY_ATTEMPTS: attempts})
    await show_screen(message, texts.astro.invalid_date, astro_cancel(texts))
