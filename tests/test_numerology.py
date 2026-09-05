"""Расчёт личного года 2027 и разборы по цифрам."""

from __future__ import annotations

import calendar

import pytest

from bot.content.store import ContentSnapshot
from bot.services.numerology import personal_year
from bot.services.zodiac import parse_day_month


# ── Примеры из исходного разбора ────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("15.06", 5),  # 1+5+0+6+2+0+2+7 = 23 → 5
        ("28.11", 5),  # 2+8+1+1+2+0+2+7 = 23 → 5
    ],
)
def test_matches_the_source_examples(raw: str, expected: int) -> None:
    date = parse_day_month(raw)
    assert personal_year(date.day, date.month) == expected


def test_year_is_ignored_in_the_input() -> None:
    """Год рождения на цифру не влияет — считается только день и месяц."""
    assert personal_year(*_dm("15.06.1990")) == personal_year(*_dm("15.06.2003"))


# ── Границы ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01.01", 4),  # 0+1+0+1+2+0+2+7 = 13 → 4, самая маленькая сумма
        ("31.12", 9),  # 3+1+1+2+2+0+2+7 = 18 → 9
        ("29.02", 6),  # високосный день тоже считается
    ],
)
def test_boundary_dates_are_computed(raw: str, expected: int) -> None:
    assert personal_year(*_dm(raw)) == expected


def test_every_day_of_year_gives_a_digit_from_one_to_nine() -> None:
    """Ни одна дата не должна остаться без прогноза."""
    for month in range(1, 13):
        for day in range(1, calendar.monthrange(2024, month)[1] + 1):
            value = personal_year(day, month)
            assert 1 <= value <= 9, f"{day:02d}.{month:02d} → {value}"


def test_all_nine_numbers_are_reachable() -> None:
    values = {
        personal_year(day, month)
        for month in range(1, 13)
        for day in range(1, calendar.monthrange(2024, month)[1] + 1)
    }
    assert values == set(range(1, 10))


# ── Контент ─────────────────────────────────────────────────────────
def test_content_has_a_forecast_for_every_number(content: ContentSnapshot) -> None:
    assert {year.number for year in content.numerology} == set(range(1, 10))


def test_every_date_finds_its_forecast(content: ContentSnapshot) -> None:
    for month in range(1, 13):
        for day in range(1, calendar.monthrange(2024, month)[1] + 1):
            number = personal_year(day, month)
            assert content.personal_year(number) is not None, f"{day:02d}.{month:02d}"


def test_forecasts_fit_into_one_message(content: ContentSnapshot) -> None:
    """Разбор должен влезать в одно сообщение Telegram."""
    for year in content.numerology:
        assert len(year.title) + len(year.text) < 4096, f"разбор {year.number} слишком длинный"


def _dm(raw: str) -> tuple[int, int]:
    date = parse_day_month(raw)
    return date.day, date.month
