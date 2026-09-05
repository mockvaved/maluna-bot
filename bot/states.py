"""Состояния диалогов.

Всё, что здесь копится, живёт в FSM-хранилище (память или Redis с TTL 30
минут) и стирается по завершении сценария. На диск не попадает.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class RitualFlow(StatesGroup):
    """Пять вопросов «Собери свой ритуал»."""

    answering = State()


class AstroFlow(StatesGroup):
    """Ввод даты рождения в астропрогнозе."""

    waiting_for_date = State()


class DeleteFlow(StatesGroup):
    """Подтверждение команды /delete."""

    confirming = State()


# ── Ключи данных FSM ────────────────────────────────────────────────
# Ответы конструктора ритуала.
KEY_STEP = "step"
KEY_ANSWERS = "answers"
KEY_RANKED = "ranked"
KEY_SHOWN_RITUALS = "shown_rituals"

# Астропрогноз: хранится только вычисленный знак, дата рождения — никогда.
KEY_ATTEMPTS = "attempts"
KEY_SIGN = "sign"
