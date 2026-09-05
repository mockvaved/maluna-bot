"""Служебные команды: /reload для админов и /delete для всех."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.content.loader import ContentError
from bot.content.store import ContentStore
from bot.db.repo import Repository
from bot.handlers.common import render, reset_flow, show_main_menu, show_screen, user_id_of
from bot.keyboards.builders import delete_confirm
from bot.keyboards.callbacks import DeleteCB
from bot.states import DeleteFlow

logger = logging.getLogger(__name__)

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
    callback: CallbackQuery, state: FSMContext, content_store: ContentStore, repo: Repository
) -> None:
    await callback.answer()
    texts = content_store.current.texts
    await repo.delete_user(user_id_of(callback))
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
