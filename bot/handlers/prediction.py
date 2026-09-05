"""🕯 Предсказание — одно в календарные сутки по московскому времени."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.content.store import ContentStore
from bot.db.repo import Repository
from bot.handlers.common import render, show_screen, user_id_of
from bot.keyboards.builders import only_menu
from bot.keyboards.callbacks import MenuCB
from bot.services.prediction import NoCardsAvailable, get_prediction

logger = logging.getLogger(__name__)

router = Router(name="prediction")


@router.callback_query(MenuCB.filter(F.section == "prediction"))
async def handle_prediction(
    callback: CallbackQuery, content_store: ContentStore, repo: Repository
) -> None:
    await callback.answer()
    content = content_store.current
    texts = content.texts
    user_id = user_id_of(callback)

    try:
        result = await get_prediction(repo, content, user_id)
    except NoCardsAvailable:
        logger.warning("no_active_cards", extra={"user_id": user_id})
        await show_screen(callback, texts.guide.empty_section, only_menu(texts))
        return

    body = render(texts.prediction.card, title=result.card.title, text=result.card.text.strip())
    if result.repeated_today:
        body = f"{body.rstrip()}\n\n{texts.prediction.already_today}"
    else:
        await repo.log_event(user_id, "prediction_shown", {"card_id": result.card.id})

    await show_screen(callback, body.strip(), only_menu(texts, texts.common.back_to_menu))
