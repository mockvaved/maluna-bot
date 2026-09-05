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
    Document,
    File,
    InlineKeyboardMarkup,
    Message,
    PhotoSize,
    Update,
    User,
)

USER_ID = 424242
CHAT_ID = 424242

# Методы, которыми бот рисует экран.
_TEXT_METHODS = frozenset({"SendMessage", "EditMessageText", "SendPhoto"})

_user = User(id=USER_ID, is_bot=False, first_name="Tester")
_chat = Chat(id=CHAT_ID, type="private")


class FakeSession(BaseSession):
    """Отвечает на вызовы API и складывает их в calls."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self.member_status = "member"
        self.fail_get_chat_member: Exception | None = None
        # Содержимое «скачиваемого» файла и способ сломать скачивание.
        self.file_bytes = b"fake-jpeg-bytes"
        self.fail_download: Exception | None = None
        self._message_id = 100

    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        self.calls.append(method)
        name = type(method).__name__

        if name == "GetFile":
            return File(
                file_id=getattr(method, "file_id", "file-1"),
                file_unique_id="unique-1",
                file_size=len(self.file_bytes),
                file_path="photos/file_1.jpg",
            )

        if name == "GetChatMember":
            if self.fail_get_chat_member is not None:
                raise self.fail_get_chat_member
            if self.member_status == "member":
                return ChatMemberMember(status="member", user=_user)
            return ChatMemberLeft(status="left", user=_user)

        if name in {"SendMessage", "EditMessageText", "SendPhoto"}:
            self._message_id += 1
            return Message(
                message_id=self._message_id,
                date=datetime.now(tz=timezone.utc),
                chat=_chat,
                from_user=_user,
                text=getattr(method, "text", None),
                caption=getattr(method, "caption", None),
                reply_markup=getattr(method, "reply_markup", None),
            )

        # AnswerCallbackQuery, SetMyCommands, EditMessageReplyMarkup и прочее.
        return True

    async def stream_content(self, *args: Any, **kwargs: Any):
        """Отдаёт байты «скачанного» файла — так работает bot.download_file."""
        if self.fail_download is not None:
            raise self.fail_download
        yield self.file_bytes

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

    def captions_and_texts(self) -> str:
        """Всё, что бот отправил на последнем шаге, включая подписи к фото."""
        parts = [
            getattr(call, "text", None) or getattr(call, "caption", None) or ""
            for call in self.calls
            if type(call).__name__ in _TEXT_METHODS
        ]
        return "\n".join(parts)

    def last_text(self) -> str:
        """Текст последнего экрана. У карточки с фото это подпись."""
        for call in reversed(self.calls):
            if type(call).__name__ in _TEXT_METHODS:
                return getattr(call, "text", None) or getattr(call, "caption", None) or ""
        raise AssertionError("bot sent no messages")

    def last_markup(self) -> InlineKeyboardMarkup | None:
        """Клавиатура последнего экрана.

        Правка снятия кнопок со старого сообщения (EditMessageReplyMarkup)
        экраном не считается — иначе фото-карточка выглядела бы как экран
        без кнопок.
        """
        for call in reversed(self.calls):
            if type(call).__name__ in _TEXT_METHODS:
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


def make_photo_update(update_id: int = 1, file_id: str = "photo-1") -> Update:
    """Апдейт с фотографией — как когда человек присылает скриншот."""
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(tz=timezone.utc),
            chat=_chat,
            from_user=_user,
            photo=[
                PhotoSize(
                    file_id=file_id,
                    file_unique_id=f"{file_id}-u",
                    width=800,
                    height=600,
                    file_size=12345,
                )
            ],
        ),
    )


def make_document_update(
    update_id: int = 1, mime_type: str = "image/png", file_id: str = "doc-1"
) -> Update:
    """Апдейт с файлом: картинку часто присылают именно так."""
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(tz=timezone.utc),
            chat=_chat,
            from_user=_user,
            document=Document(
                file_id=file_id,
                file_unique_id=f"{file_id}-u",
                mime_type=mime_type,
                file_name="review.png",
                file_size=23456,
            ),
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
