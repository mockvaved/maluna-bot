"""Кнопка «Я подписался» на экране шлюза.

Единственный колбэк, который шлюз пропускает мимо себя, — иначе из
экрана подписки не было бы выхода.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.config import Config
from bot.content.store import ContentStore
from bot.db.repo import Repository
from bot.handlers.common import show_main_menu, show_screen, user_id_of
from bot.keyboards.builders import subscribe_gate
from bot.keyboards.callbacks import GateCB
from bot.services.subscription import SubscriptionChecker

router = Router(name="gate")


@router.callback_query(GateCB.filter(F.action == "check"))
async def recheck_subscription(
    callback: CallbackQuery,
    state: FSMContext,
    content_store: ContentStore,
    repo: Repository,
    config: Config,
    subscription: SubscriptionChecker,
) -> None:
    await callback.answer()
    texts = content_store.current.texts
    user_id = user_id_of(callback)

    if callback.bot is None:
        return

    # Кеш сбрасываем: человек только что подписался, старый ответ врёт.
    subscription.forget(user_id)
    result = await subscription.check(callback.bot, user_id, use_cache=False)

    if not result.allowed:
        await show_screen(
            callback, texts.gate.not_yet, subscribe_gate(texts, config.channel_url)
        )
        return

    await state.clear()
    await repo.touch_user(user_id)
    await repo.log_event(user_id, "gate_passed")
    await show_main_menu(callback, texts, prefix=texts.welcome.strip())
