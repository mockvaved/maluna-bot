"""Общие помощники хендлеров: подстановки, показ экрана, главное меню."""

from __future__ import annotations

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.content.schemas import Texts
from bot.keyboards.builders import main_menu
from bot.states import KEY_SHOWN_RITUALS

logger = logging.getLogger(__name__)

MENU_SEPARATOR = "\n\n"

# Ограничение Telegram на длину текстового сообщения.
MESSAGE_LIMIT = 4096


def render(template: str, **values: object) -> str:
    """Подставляет {плейсхолдеры} в текст из контент-файла.

    Обычный str.format здесь не подходит: владелец правит тексты руками и
    может написать фигурную скобку в обычном смысле. Подменяем только
    известные ключи, всё остальное оставляем как есть.
    """
    result = template
    for key, value in values.items():
        result = result.replace("{" + key + "}", str(value))
    return result


def split_text(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Режет длинный текст по абзацам, чтобы влезть в лимит Telegram."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        # Абзац сам длиннее лимита — режем по строкам.
        while len(paragraph) > limit:
            cut = paragraph.rfind("\n", 0, limit)
            cut = cut if cut > 0 else limit
            chunks.append(paragraph[:cut])
            paragraph = paragraph[cut:].lstrip("\n")
        current = paragraph
    if current:
        chunks.append(current)
    return chunks


async def show_screen(
    event: Message | CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Рисует экран: на нажатие кнопки правит сообщение, на команду шлёт новое."""
    chunks = split_text(text)

    if isinstance(event, CallbackQuery):
        message = event.message
        if message is None:
            if event.bot is not None and event.from_user is not None:
                await _send_chunks(event.bot.send_message, event.from_user.id, chunks, markup)
            return

        if len(chunks) == 1:
            try:
                await message.edit_text(chunks[0], reply_markup=markup)
                return
            except TelegramBadRequest as exc:
                # «message is not modified» — нажали ту же кнопку дважды.
                if "message is not modified" in str(exc):
                    return
                # Сообщение слишком старое для правки — отправим новое.
                logger.info("edit_failed_sending_new", extra={"reason": str(exc)})

        # Длинный текст правкой не помещается: убираем кнопки со старого
        # экрана, чтобы не осталось двух активных клавиатур, и шлём новые.
        await _drop_markup(message)
        for index, chunk in enumerate(chunks):
            await message.answer(chunk, reply_markup=markup if index == len(chunks) - 1 else None)
        return

    for index, chunk in enumerate(chunks):
        await event.answer(chunk, reply_markup=markup if index == len(chunks) - 1 else None)


async def _send_chunks(send, chat_id: int, chunks: list[str], markup) -> None:
    for index, chunk in enumerate(chunks):
        await send(chat_id, chunk, reply_markup=markup if index == len(chunks) - 1 else None)


async def _drop_markup(message: Message) -> None:
    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        # Кнопок уже нет или сообщение недоступно для правки — не страшно.
        pass


async def show_main_menu(
    event: Message | CallbackQuery, texts: Texts, prefix: str | None = None
) -> None:
    text = f"{prefix}{MENU_SEPARATOR}{texts.menu.title}" if prefix else texts.menu.title
    await show_screen(event, text, main_menu(texts))


def user_id_of(event: Message | CallbackQuery) -> int:
    if event.from_user is None:
        raise ValueError("event without a user")
    return event.from_user.id


async def reset_flow(state: FSMContext) -> None:
    """Обрывает текущий сценарий, но помнит выданные ритуалы этой сессии.

    Ответы на вопросы и введённая дата стираются сразу. Список показанных
    ритуалов живёт до конца сессии, чтобы следующее прохождение не выдало
    то же самое (ТЗ, раздел 8).
    """
    data = await state.get_data()
    shown = data.get(KEY_SHOWN_RITUALS, [])
    await state.clear()
    if shown:
        await state.update_data({KEY_SHOWN_RITUALS: shown})
