"""/start и главное меню.

Никакого онбординга и экрана согласия: собирать нечего, поэтому после
приветствия сразу показывается меню. Повторный /start в любой момент
возвращает в начало.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.content.store import ContentStore
from bot.db.repo import Repository
from bot.handlers.common import reset_flow, show_main_menu, user_id_of
from bot.keyboards.callbacks import MenuCB

router = Router(name="start")


@router.message(CommandStart())
async def handle_start(
    message: Message, state: FSMContext, content_store: ContentStore, repo: Repository
) -> None:
    await state.clear()
    texts = content_store.current.texts
    await repo.touch_user(user_id_of(message))
    await repo.log_event(user_id_of(message), "start")
    await show_main_menu(message, texts, prefix=texts.welcome.strip())


@router.callback_query(MenuCB.filter(F.section == "main"))
async def handle_menu(
    callback: CallbackQuery, state: FSMContext, content_store: ContentStore
) -> None:
    """Кнопка «В меню» с любого экрана: сценарий обрывается, ответы стираются."""
    await reset_flow(state)
    await callback.answer()
    await show_main_menu(callback, content_store.current.texts)
