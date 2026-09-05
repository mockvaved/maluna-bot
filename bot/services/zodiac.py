"""Разбор даты рождения и определение знака зодиака.

Дата нужна ровно для одного действия — вычислить знак — и после этого
выбрасывается. Ни функция, ни вызывающий код не сохраняют её и не пишут
в логи (ТЗ, раздел 9).
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass

from bot.content.schemas import AstroSign

# ДД.ММ или ДД.ММ.ГГГГ. Разделителем может быть точка, дефис или слэш.
_DATE_RE = re.compile(r"^\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})(?:\s*[.\-/]\s*(\d{2,4}))?\s*\.?\s*$")

# Високосный год: 29.02 — валидная дата рождения.
_LEAP_YEAR = 2024


class InvalidDate(ValueError):
    """Строка не похожа на дату или такого дня в этом месяце не бывает."""


@dataclass(frozen=True, slots=True)
class DayMonth:
    day: int
    month: int


def parse_day_month(raw: str) -> DayMonth:
    """«14.03» или «14.03.1990» → DayMonth(14, 3). Год игнорируется."""
    match = _DATE_RE.match(raw)
    if not match:
        raise InvalidDate("unrecognised date format")

    day, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise InvalidDate("month out of range")
    # Год не проверяем и не используем — для знака он не нужен.
    if not 1 <= day <= calendar.monthrange(_LEAP_YEAR, month)[1]:
        raise InvalidDate("day out of range for this month")
    return DayMonth(day=day, month=month)


def _as_ordinal(day: int, month: int) -> int:
    """Число вида ММДД — им удобно сравнивать границы знаков."""
    return month * 100 + day


def find_sign(signs: tuple[AstroSign, ...], value: DayMonth) -> AstroSign | None:
    """Знак по дню и месяцу. Козерог переходит через новый год."""
    point = _as_ordinal(value.day, value.month)
    for sign in signs:
        start_day, start_month = (int(part) for part in sign.date_from.split("."))
        end_day, end_month = (int(part) for part in sign.date_to.split("."))
        start = _as_ordinal(start_day, start_month)
        end = _as_ordinal(end_day, end_month)
        if start <= end:
            if start <= point <= end:
                return sign
        # Интервал через границу года (22.12 – 19.01).
        elif point >= start or point <= end:
            return sign
    return None
