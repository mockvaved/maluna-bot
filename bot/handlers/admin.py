"""Служебные команды: /reload для админов и /delete для всех."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from bot.config import Config
from bot.content.loader import ContentError
from bot.content.store import ContentStore
from bot.db.repo import Repository
from bot.handlers.common import render, reset_flow, show_main_menu, show_screen, user_id_of
from bot.keyboards.builders import delete_confirm
from bot.keyboards.callbacks import DeleteCB
from bot.states import DeleteFlow

logger = logging.getLogger(__name__)

# Сколько последних отзывов показывает /reviews за один раз.
REVIEWS_LIMIT = 10

router = Router(name="admin")


@router.message(Command("reload"))
async def handle_reload(message: Message, content_store: ContentStore, config: Config) -> None:
    """Перечитывает контент без рестарта. При ошибке остаётся прежняя версия."""
    user_id = user_id_of(message)
    if not config.is_admin(user_id):
        # Не подтверждаем существование команды посторонним.
        return

    texts = content_store.current.texts
    try:
        snapshot = content_store.reload()
    except ContentError as exc:
        logger.warning("content_reload_failed", extra={"user_id": user_id, "reason": str(exc)})
        await message.answer(render(texts.admin.reload_failed, error=str(exc)).strip())
        return

    stats = ", ".join(f"{key}: {value}" for key, value in snapshot.stats().items())
    await message.answer(f"{snapshot.texts.admin.reload_ok}\n{stats}")


@router.message(Command("reviews"))
async def handle_reviews(
    message: Message, content_store: ContentStore, repo: Repository, config: Config
) -> None:
    """Последние присланные отзывы — картинками, прямо в переписку."""
    if not config.is_admin(user_id_of(message)):
        return

    texts = content_store.current.texts
    reviews = await repo.recent_reviews(REVIEWS_LIMIT)
    if not reviews:
        await message.answer(texts.admin.reviews_empty)
        return

    total = await repo.review_count()
    for shown, review in enumerate(reviews, start=1):
        caption = render(
            texts.admin.reviews_caption,
            date=review.created_at[:10],
            user_id=review.user_id,
            shown=shown,
            total=total,
        )
        # Сначала пробуем file_id: так Telegram отдаёт картинку сам, без
        # чтения диска. Если он протух, отправляем файл.
        try:
            await message.answer_photo(review.file_id, caption=caption)
            continue
        except TelegramAPIError as exc:
            logger.info("review_file_id_stale", extra={"reason": str(exc)})

        path = config.db_path.parent / review.file_path
        if not path.is_file():
            await message.answer(f"{caption}\n{review.file_path}")
            continue
        try:
            await message.answer_photo(FSInputFile(path), caption=caption)
        except TelegramAPIError:
            logger.exception("review_send_failed")
            await message.answer(f"{caption}\n{review.file_path}")


@router.message(Command("delete"))
async def handle_delete(
    message: Message, state: FSMContext, content_store: ContentStore
) -> None:
    texts = content_store.current.texts
    await reset_flow(state)
    await state.set_state(DeleteFlow.confirming)
    await show_screen(message, texts.delete.confirm.strip(), delete_confirm(texts))


@router.callback_query(DeleteCB.filter(F.action == "confirm"))
async def confirm_delete(
    callback: CallbackQuery,
    state: FSMContext,
    content_store: ContentStore,
    repo: Repository,
    config: Config,
) -> None:
    await callback.answer()
    texts = content_store.current.texts
    # media_root нужен, чтобы удалить и фото отзывов с диска, а не только
    # строки в базе.
    await repo.delete_user(user_id_of(callback), media_root=config.db_path.parent)
    # Состояние стираем полностью: сессию тоже нечего помнить.
    await state.clear()
    await show_main_menu(callback, texts, prefix=texts.delete.done)


@router.callback_query(DeleteCB.filter(F.action == "cancel"))
async def cancel_delete(
    callback: CallbackQuery, state: FSMContext, content_store: ContentStore
) -> None:
    await callback.answer()
    texts = content_store.current.texts
    await reset_flow(state)
    await show_main_menu(callback, texts, prefix=texts.delete.cancelled)
