"""🎁 Подарок за отзыв — нумерологический прогноз на 2027 год.

Порядок: фото отзыва → дата рождения → прогноз.

Подлинность отзыва не проверяется: засчитывается любая присланная
картинка. Фото просим один раз — дальше человек заходит сразу к дате.

Дата рождения, как и в астропрогнозе, живёт только в аргументе функции:
из неё считается цифра года, и дальше в состоянии остаётся только
результат. В базу и логи дата не попадает.
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
from bot.keyboards.builders import astro_cancel, gift_result, only_menu
from bot.keyboards.callbacks import GiftCB, MenuCB
from bot.services.numerology import personal_year
from bot.services.reviews import ReviewSaveError, save_review_photo
from bot.services.zodiac import InvalidDate, parse_day_month
from bot.states import KEY_ATTEMPTS, GiftFlow

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

router = Router(name="gift")


@router.callback_query(MenuCB.filter(F.section == "gift"))
async def enter_section(
    callback: CallbackQuery, state: FSMContext, content_store: ContentStore, repo: Repository
) -> None:
    await callback.answer()
    content = content_store.current
    user_id = user_id_of(callback)
    await repo.log_event(user_id, "gift_opened")

    if not content.numerology:
        await show_screen(callback, content.texts.guide.empty_section, only_menu(content.texts))
        return

    # Подарок отдаётся один раз: прислал отзыв — заходи сколько угодно.
    if await repo.has_review(user_id):
        await _ask_date(callback, state, content)
        return

    await state.set_state(GiftFlow.waiting_for_photo)
    await state.update_data({KEY_ATTEMPTS: 0})
    texts = content.texts
    body = f"{texts.gift.ask_photo.strip()}\n\n{texts.gift.photo_note}"
    await show_screen(callback, body, astro_cancel(texts))


@router.callback_query(GiftCB.filter(F.action == "again"))
async def another_date(
    callback: CallbackQuery, state: FSMContext, content_store: ContentStore
) -> None:
    await callback.answer()
    await _ask_date(callback, state, content_store.current)


# ── Шаг 1: фото отзыва ──────────────────────────────────────────────
@router.message(GiftFlow.waiting_for_photo, F.photo | F.document)
async def receive_photo(
    message: Message,
    state: FSMContext,
    content_store: ContentStore,
    repo: Repository,
    config: Config,
) -> None:
    content = content_store.current
    texts = content.texts
    user_id = user_id_of(message)

    # Картинку присылают и фотографией, и файлом — принимаем оба варианта.
    media = message.photo[-1] if message.photo else message.document
    if media is None or (
        message.document is not None
        and not (message.document.mime_type or "").startswith("image/")
    ):
        await _handle_wrong_photo(message, state, content)
        return

    if message.bot is None:
        return

    try:
        file_path = await save_review_photo(message.bot, config.db_path.parent, user_id, media)
    except ReviewSaveError as exc:
        logger.warning("review_save_failed", extra={"user_id": user_id, "reason": str(exc)})
        await show_screen(message, texts.gift.save_failed, astro_cancel(texts))
        return

    await repo.add_review_photo(user_id, media.file_id, file_path)
    await repo.log_event(user_id, "review_photo_saved")
    await show_screen(message, texts.gift.photo_saved, astro_cancel(texts))
    await _ask_date(message, state, content)


@router.message(GiftFlow.waiting_for_photo)
async def receive_not_a_photo(
    message: Message, state: FSMContext, content_store: ContentStore
) -> None:
    await _handle_wrong_photo(message, state, content_store.current)


# ── Шаг 2: дата рождения ────────────────────────────────────────────
@router.message(GiftFlow.waiting_for_date)
async def receive_date(
    message: Message, state: FSMContext, content_store: ContentStore, repo: Repository
) -> None:
    content = content_store.current
    texts = content.texts

    try:
        day_month = parse_day_month(message.text or "")
    except InvalidDate:
        await _handle_bad_date(message, state, content)
        return

    number = personal_year(day_month.day, day_month.month)
    # Дальше день и месяц не нужны: остаётся только вычисленная цифра.
    del day_month

    year = content.personal_year(number)
    if year is None:
        logger.warning("numerology_entry_missing", extra={"number": number})
        await _handle_bad_date(message, state, content)
        return

    await reset_flow(state)
    # В статистику уходит только цифра года, никогда не дата рождения.
    await repo.log_event(user_id_of(message), "numerology_shown", {"number": number})
    logger.info("numerology_shown", extra={"user_id": user_id_of(message), "number": number})

    body = render(texts.gift.forecast, title=year.title, text=year.text.strip()).strip()
    products = [pid for pid in year.product_ids if content.product(pid) is not None]
    if products:
        body = f"{body}\n\n{texts.astro.product_header}"
    await show_screen(message, body, gift_result(texts, content, products))


# ── Внутренняя механика ─────────────────────────────────────────────
async def _ask_date(
    event: Message | CallbackQuery, state: FSMContext, content: ContentSnapshot
) -> None:
    texts = content.texts
    await state.set_state(GiftFlow.waiting_for_date)
    await state.update_data({KEY_ATTEMPTS: 0})
    body = f"{texts.gift.ask_date.strip()}\n\n{texts.astro.privacy_note}"
    await show_screen(event, body, astro_cancel(texts))


async def _handle_wrong_photo(
    message: Message, state: FSMContext, content: ContentSnapshot
) -> None:
    texts = content.texts
    attempts = int((await state.get_data()).get(KEY_ATTEMPTS, 0)) + 1

    if attempts >= MAX_ATTEMPTS:
        await reset_flow(state)
        await show_main_menu(message, texts, prefix=texts.gift.too_many_attempts)
        return

    await state.update_data({KEY_ATTEMPTS: attempts})
    await show_screen(message, texts.gift.not_a_photo, astro_cancel(texts))


async def _handle_bad_date(
    message: Message, state: FSMContext, content: ContentSnapshot
) -> None:
    texts = content.texts
    attempts = int((await state.get_data()).get(KEY_ATTEMPTS, 0)) + 1

    if attempts >= MAX_ATTEMPTS:
        await reset_flow(state)
        await show_main_menu(message, texts, prefix=texts.astro.too_many_attempts)
        return

    await state.update_data({KEY_ATTEMPTS: attempts})
    await show_screen(message, texts.astro.invalid_date, astro_cancel(texts))
