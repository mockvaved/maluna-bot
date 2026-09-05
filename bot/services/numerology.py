"""Расчёт личного года по дате рождения.

Складываются все цифры дня, месяца и года прогноза, и результат
сворачивается до одной цифры от 1 до 9:

    15 июня 2027 → 1+5+0+6+2+0+2+7 = 23 → 2+3 = 5
    28 ноября    → 2+8+1+1+2+0+2+7 = 23 → 5

Дата рождения нужна ровно для этого действия и дальше выбрасывается —
как и в астропрогнозе, она не попадает ни в базу, ни в логи.
"""

from __future__ import annotations

FORECAST_YEAR = 2027


def _digit_sum(value: int) -> int:
    return sum(int(digit) for digit in str(value))


def personal_year(day: int, month: int, year: int = FORECAST_YEAR) -> int:
    """Цифра личного года от 1 до 9.

    Ноль получиться не может: минимальная сумма для 01.01.2027 — 13.
    """
    total = _digit_sum(day) + _digit_sum(month) + _digit_sum(year)
    while total > 9:
        total = _digit_sum(total)
    return total
