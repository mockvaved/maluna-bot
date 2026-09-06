"""Шлюз: бот работает только для подписчиков канала бренда.

Проверка стоит перед всеми роутерами, поэтому неподписанный человек не
доходит ни до одного раздела — вместо ответа он видит экран с призывом
подписаться.

Мимо шлюза проходят три вещи:
  • админы — иначе им станут недоступны /reload и /reviews;
  • /delete — человек должен иметь возможность стереть свои данные,
    даже если отписался от канала;
  • кнопка «Я подписался» — иначе из шлюза не выбраться.

Если Telegram ответил ошибкой (чаще всего бот не админ в канале), доступ
открывается всем: запирать бот целиком из-за сетевого сбоя или неверной
настройки хуже, чем на время пустить лишних. В лог уходит warning.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from bot.config import Config
from bot.content.store import ContentStore
from bot.keyboards.builders import subscribe_gate
from bot.keyboards.callbacks import DeleteCB, GateCB
from bot.services.subscription import SubscriptionChecker

logger = logging.getLogger(__name__)

# Команды, которые работают без подписки.
ALWAYS_ALLOWED_COMMANDS = ("/delete",)

# Колбэки, которые работают без подписки: подтверждение удаления и
# повторная проверка подписки.
_ALWAYS_ALLOWED_PREFIXES = (DeleteCB.__prefix__, GateCB.__prefix__)


class SubscriptionMiddleware(BaseMiddleware):
    def __init__(
        self,
        content_store: ContentStore,
        config: Config,
        subscription: SubscriptionChecker,
    ) -> None:
        self._content_store = content_store
        self._config = config
        self._subscription = subscription

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        bot = data.get("bot")
        if user is None or bot is None or _is_always_allowed(event):
            return await handler(event, data)

        # Конфиг может быть подменён на лету (в тестах), поэтому берём его
        # из данных апдейта, а не из сохранённого при сборке.
        config: Config = data.get("config", self._config)
        if config.is_admin(user.id):
            return await handler(event, data)

        state = await self._subscription.check(bot, user.id)
        if state.allowed:
            if state.check_failed:
                logger.warning("gate_open_without_check", extra={"user_id": user.id})
            return await handler(event, data)

        await self._show_gate(event, config)
        return None

    async def _show_gate(self, event: TelegramObject, config: Config) -> None:
        texts = self._content_store.current.texts
        markup = subscribe_gate(texts, config.channel_url)

        if isinstance(event, CallbackQuery):
            await event.answer()
            if event.message is not None:
                await event.message.answer(texts.gate.intro.strip(), reply_markup=markup)
        elif isinstance(event, Message):
            await event.answer(texts.gate.intro.strip(), reply_markup=markup)


def _is_always_allowed(event: TelegramObject) -> bool:
    if isinstance(event, Message):
        text = (event.text or "").strip().lower()
        return any(text.startswith(command) for command in ALWAYS_ALLOWED_COMMANDS)
    if isinstance(event, CallbackQuery):
        data = event.data or ""
        return any(data.startswith(f"{prefix}:") for prefix in _ALWAYS_ALLOWED_PREFIXES)
    return False
