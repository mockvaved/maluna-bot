"""💜 О бренде — единственный экран со ссылкой на сайт."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.content.store import ContentStore
from bot.db.repo import Repository
from bot.handlers.common import show_screen, user_id_of
from bot.keyboards.builders import about_menu
from bot.keyboards.callbacks import MenuCB

router = Router(name="about")


@router.callback_query(MenuCB.filter(F.section == "about"))
async def show_about(
    callback: CallbackQuery, content_store: ContentStore, repo: Repository
) -> None:
    await callback.answer()
    texts = content_store.current.texts
    await repo.log_event(user_id_of(callback), "about_opened")
    await show_screen(callback, texts.about.strip(), about_menu(texts))
