"""Поддельная сессия Telegram: гоняем сценарии, не выходя в сеть.

Записывает все исходящие вызовы API и отдаёт правдоподобные ответы,
чтобы хендлеры можно было прогнать целиком.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberLeft,
    ChatMemberMember,
    InlineKeyboardMarkup,
    Message,
    Update,
    User,
)

USER_ID = 424242
CHAT_ID = 424242

_user = User(id=USER_ID, is_bot=False, first_name="Tester")
_chat = Chat(id=CHAT_ID, type="private")


class FakeSession(BaseSession):
    """Отвечает на вызовы API и складывает их в calls."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self.member_status = "member"
        self.fail_get_chat_member: Exception | None = None
        self._message_id = 100

    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        self.calls.append(method)
        name = type(method).__name__

        if name == "GetChatMember":
            if self.fail_get_chat_member is not None:
                raise self.fail_get_chat_member
            if self.member_status == "member":
                return ChatMemberMember(status="member", user=_user)
            return ChatMemberLeft(status="left", user=_user)

        if name in {"SendMessage", "EditMessageText"}:
            self._message_id += 1
            return Message(
                message_id=self._message_id,
                date=datetime.now(tz=timezone.utc),
                chat=_chat,
                from_user=_user,
                text=getattr(method, "text", ""),
                reply_markup=getattr(method, "reply_markup", None),
            )

        # AnswerCallbackQuery, SetMyCommands, EditMessageReplyMarkup и прочее.
        return True

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError
        yield b""

    async def close(self) -> None:
        return None

    # ── Помощники для тестов ────────────────────────────────────────
    def reset(self) -> None:
        self.calls.clear()

    def sent_texts(self) -> list[str]:
        return [
            getattr(call, "text", "")
            for call in self.calls
            if type(call).__name__ in {"SendMessage", "EditMessageText"}
        ]

    def last_text(self) -> str:
        texts = self.sent_texts()
        assert texts, "bot sent no messages"
        return texts[-1]

    def last_markup(self) -> InlineKeyboardMarkup | None:
        for call in reversed(self.calls):
            if type(call).__name__ in {"SendMessage", "EditMessageText"}:
                return getattr(call, "reply_markup", None)
        return None

    def button_labels(self) -> list[str]:
        markup = self.last_markup()
        if markup is None:
            return []
        return [button.text for row in markup.inline_keyboard for button in row]

    def callback_for(self, label: str) -> str:
        """callback_data кнопки с такой подписью на последнем экране."""
        markup = self.last_markup()
        assert markup is not None, "last message has no keyboard"
        for row in markup.inline_keyboard:
            for button in row:
                if button.text == label and button.callback_data:
                    return button.callback_data
        raise AssertionError(f"button {label!r} not found in {self.button_labels()}")

    def alerts(self) -> list[str]:
        return [
            getattr(call, "text", "") or ""
            for call in self.calls
            if type(call).__name__ == "AnswerCallbackQuery"
        ]


def make_message_update(text: str, update_id: int = 1) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(tz=timezone.utc),
            chat=_chat,
            from_user=_user,
            text=text,
        ),
    )


def make_callback_update(data: str, update_id: int = 1) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=str(update_id),
            from_user=_user,
            chat_instance="test",
            data=data,
            message=Message(
                message_id=update_id,
                date=datetime.now(tz=timezone.utc),
                chat=_chat,
                from_user=_user,
                text="previous screen",
            ),
        ),
    )
