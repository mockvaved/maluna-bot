"""Разбор даты рождения и границы знаков зодиака."""

from __future__ import annotations

import pytest

from bot.content.store import ContentSnapshot
from bot.services.zodiac import DayMonth, InvalidDate, find_sign, parse_day_month


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("14.03", DayMonth(14, 3)),
        ("14.03.1990", DayMonth(14, 3)),
        ("1.1", DayMonth(1, 1)),
        ("01.01.90", DayMonth(1, 1)),
        (" 29.02 ", DayMonth(29, 2)),  # високосный день — валиден
        ("31.12", DayMonth(31, 12)),
        ("14-03", DayMonth(14, 3)),
        ("14/03/2000", DayMonth(14, 3)),
    ],
)
def test_parse_valid_dates(raw: str, expected: DayMonth) -> None:
    assert parse_day_month(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "31.02",  # такого дня не бывает
        "31.04",
        "00.05",
        "12.13",
        "12.00",
        "просто текст",
        "",
        "1234",
        "14.03.1990.05",
    ],
)
def test_parse_invalid_dates(raw: str) -> None:
    with pytest.raises(InvalidDate):
        parse_day_month(raw)


@pytest.mark.parametrize(
    ("day", "month", "sign"),
    [
        (21, 3, "Овен"),
        (19, 4, "Овен"),
        (20, 4, "Телец"),
        (23, 7, "Лев"),
        (22, 8, "Лев"),
        (23, 8, "Дева"),
        (21, 12, "Стрелец"),
        (22, 12, "Козерог"),
        (31, 12, "Козерог"),  # интервал через новый год
        (1, 1, "Козерог"),
        (19, 1, "Козерог"),
        (20, 1, "Водолей"),
        (29, 2, "Рыбы"),
        (20, 3, "Рыбы"),
    ],
)
def test_sign_boundaries(content: ContentSnapshot, day: int, month: int, sign: str) -> None:
    found = find_sign(content.astro, DayMonth(day, month))
    assert found is not None
    assert found.sign == sign


def test_every_day_of_year_has_a_sign(content: ContentSnapshot) -> None:
    """Ни одна валидная дата не должна остаться без знака."""
    import calendar

    for month in range(1, 13):
        for day in range(1, calendar.monthrange(2024, month)[1] + 1):
            assert find_sign(content.astro, DayMonth(day, month)) is not None, f"{day:02d}.{month:02d}"
