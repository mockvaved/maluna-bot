"""Схема callback_data.

Telegram ограничивает callback_data 64 байтами, поэтому идентификаторы
продуктов и практик передаются индексом в текущем снимке контента, а не
строкой. После /reload индексы пересобираются вместе с меню.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class MenuCB(CallbackData, prefix="m"):
    """Навигация по разделам верхнего уровня."""

    section: str  # main | prediction | ritual | astro | guide | about


class RitualCB(CallbackData, prefix="r"):
    """Шаги конструктора ритуала.

    action: pick (выбор варианта) | toggle (галочка в мультивыборе) |
            done (завершить мультивыбор) | back | cancel | another | start
    value:  индекс варианта или -1, если не нужен
    """

    action: str
    value: int = -1


class AstroCB(CallbackData, prefix="a"):
    """action: check (проверить подписку) | again (другая дата) | start"""

    action: str


class GuideCB(CallbackData, prefix="g"):
    """Разделы справочника.

    action: root | howto | category | product | practices | practice |
            disposal | faq
    value:  индекс категории / продукта / практики / карточки FAQ
    extra:  индекс категории, когда открываем продукт внутри неё
    """

    action: str
    value: int = -1
    extra: int = -1


class DeleteCB(CallbackData, prefix="d"):
    """action: confirm | cancel"""

    action: str
