"""Проверка подписки на канал бренда.

По подписке открывается весь бот: проверку вызывает шлюз в
bot/middlewares/subscription.py на каждое действие человека.

Чтобы не дёргать Telegram API на каждое нажатие, ответ кешируется в
памяти на десять минут по user_id. Это и потолок задержки: столько
отписавшийся ещё сохраняет доступ.

Если бот не админ в канале, getChatMember вернёт ошибку. В этом случае
доступ открывается всем: запирать бот целиком из-за сетевого сбоя или
неверной настройки хуже, чем на время пустить лишних. В лог уходит
warning.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 10 * 60

_ALLOWED_STATUSES = frozenset({"creator", "administrator", "member"})


@dataclass(frozen=True, slots=True)
class SubscriptionState:
    subscribed: bool
    check_failed: bool = False

    @property
    def allowed(self) -> bool:
        """Доступ открыт подписчикам, а также всем, если проверка не сработала."""
        return self.subscribed or self.check_failed


class SubscriptionChecker:
    def __init__(self, channel: str, ttl_seconds: int = CACHE_TTL_SECONDS) -> None:
        self._channel = channel
        self._ttl = ttl_seconds
        self._cache: dict[int, tuple[SubscriptionState, float]] = {}

    async def check(self, bot: Bot, user_id: int, *, use_cache: bool = True) -> SubscriptionState:
        if use_cache:
            cached = self._cache.get(user_id)
            if cached is not None and cached[1] > time.monotonic():
                return cached[0]

        state = await self._fetch(bot, user_id)
        self._cache[user_id] = (state, time.monotonic() + self._ttl)
        return state

    async def _fetch(self, bot: Bot, user_id: int) -> SubscriptionState:
        try:
            member = await bot.get_chat_member(chat_id=self._channel, user_id=user_id)
        except TelegramAPIError as exc:
            # Самая частая причина — бот не добавлен админом в канал.
            logger.warning(
                "subscription_check_failed",
                extra={"user_id": user_id, "channel": self._channel, "reason": str(exc)},
            )
            return SubscriptionState(subscribed=False, check_failed=True)

        status = str(getattr(member, "status", ""))
        if status == "restricted":
            # Ограниченный участник всё ещё в канале, если is_member = True.
            return SubscriptionState(subscribed=bool(getattr(member, "is_member", False)))
        return SubscriptionState(subscribed=status in _ALLOWED_STATUSES)

    def forget(self, user_id: int) -> None:
        """Сбрасывает кеш — нужно после нажатия «Я подписался»."""
        self._cache.pop(user_id, None)
