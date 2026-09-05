"""Свободный текст и всё, что не попало в другие хендлеры.

Бот работает кнопками. Если человек пишет текстом, ищем в сообщении слова
из replies.yaml — сверху вниз, первое совпадение выигрывает — и отвечаем
готовой фразой. Никакой генерации в рантайме.

Текст сообщения нигде не сохраняется: он не пишется ни в базу, ни в логи,
ни в события. В events уходит только идентификатор сработавшего правила.

Роутер подключается последним, поэтому не перехватывает сценарии, где
сообщение ожидается (например, ввод даты в астропрогнозе).
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import CallbackQuery, Message

from bot.content.schemas import Replies
from bot.content.store import ContentStore
from bot.db.repo import Repository
from bot.handlers.common import render, show_main_menu, user_id_of

logger = logging.getLogger(__name__)

router = Router(name="fallback")


def match_rule(replies: Replies, raw: str) -> str | None:
    """id первого правила, чьё ключевое слово встретилось в сообщении."""
    lowered = raw.casefold()
    for rule in replies.rules:
        if any(keyword.casefold() in lowered for keyword in rule.keywords):
            return rule.id
    return None


@router.message()
async def handle_free_text(
    message: Message, content_store: ContentStore, repo: Repository
) -> None:
    content = content_store.current
    texts = content.texts
    replies = content.replies

    rule_id = match_rule(replies, message.text or "")
    if rule_id is None:
        await repo.log_event(user_id_of(message), "free_text", {"rule": "fallback"})
        await show_main_menu(message, texts, prefix=replies.fallback.strip())
        return

    rule = next(item for item in replies.rules if item.id == rule_id)
    await repo.log_event(user_id_of(message), "free_text", {"rule": rule.id})
    answer = render(rule.answer, contacts=texts.about_contacts).strip()
    await show_main_menu(message, texts, prefix=answer)


@router.callback_query()
async def handle_stale_callback(
    callback: CallbackQuery, content_store: ContentStore
) -> None:
    """Кнопка из старого сообщения, которое уже не вписывается в сценарий."""
    await callback.answer()
    logger.info("stale_callback", extra={"data": callback.data})
    await show_main_menu(callback, content_store.current.texts)
