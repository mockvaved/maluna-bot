"""Перехват исключений: пользователю — извинение и кнопка «В меню», в лог — стек."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.content.store import ContentStore
from bot.keyboards.builders import only_menu

logger = logging.getLogger(__name__)


class ErrorMiddleware(BaseMiddleware):
    def __init__(self, content_store: ContentStore) -> None:
        self._content_store = content_store

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception:  # noqa: BLE001 — последний рубеж, дальше падать некуда
            user = getattr(event, "from_user", None)
            # В лог уходит полный стек и user_id, но не содержимое сообщения.
            logger.exception(
                "handler_failed",
                extra={
                    "user_id": getattr(user, "id", None),
                    "event": type(event).__name__,
                },
            )
            await self._apologise(event)
            return None

    async def _apologise(self, event: TelegramObject) -> None:
        texts = self._content_store.current.texts
        try:
            if isinstance(event, CallbackQuery):
                await event.answer()
                if event.message is not None:
                    await event.message.answer(
                        texts.common.error, reply_markup=only_menu(texts)
                    )
            elif isinstance(event, Message):
                await event.answer(texts.common.error, reply_markup=only_menu(texts))
        except TelegramAPIError:
            logger.exception("error_reply_failed")
