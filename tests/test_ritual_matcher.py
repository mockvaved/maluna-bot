"""Жёсткие фильтры и скоринг подбора ритуала."""

from __future__ import annotations

import random

import pytest

from bot.content.schemas import Ritual
from bot.content.store import ContentSnapshot
from bot.services.ritual_matcher import RitualAnswers, pick_ritual, rank_rituals, score_ritual


def make_ritual(
    ritual_id: int,
    *,
    desire: str = "отдохнуть",
    duration: int = 15,
    time_of_day: list[str] | None = None,
    mood: list[str] | None = None,
    items: list[str] | None = None,
) -> Ritual:
    return Ritual(
        id=ritual_id,
        time_of_day=time_of_day or ["любое"],
        duration_min=duration,
        mood=mood or ["любое"],
        desire=desire,
        items=items or [],
        title=f"Ритуал {ritual_id}",
        text="Текст ритуала",
        active=True,
    )


def answers(**overrides) -> RitualAnswers:
    base = {
        "time_of_day": "вечер",
        "duration_min": 15,
        "mood": "устала",
        "desire": "отдохнуть",
        "items": frozenset({"свечи MALUNA", "чай"}),
    }
    base.update(overrides)
    return RitualAnswers(**base)  # type: ignore[arg-type]


# ── Скоринг ─────────────────────────────────────────────────────────
def test_score_counts_time_mood_and_items() -> None:
    ritual = make_ritual(
        1, time_of_day=["вечер"], mood=["устала", "тревожно"], items=["свечи MALUNA", "чай"]
    )
    # +1 время суток, +1 совпавшее настроение, +2 продукта
    assert score_ritual(ritual, answers()) == 4


def test_any_value_always_scores() -> None:
    ritual = make_ritual(1, time_of_day=["любое"], mood=["любое"])
    assert score_ritual(ritual, answers(time_of_day="утро", mood="радостно")) == 2


def test_unmatched_mood_scores_zero() -> None:
    ritual = make_ritual(1, time_of_day=["утро"], mood=["радостно"], items=[])
    assert score_ritual(ritual, answers()) == 0


# ── Жёсткие фильтры ─────────────────────────────────────────────────
def test_desire_must_match_exactly() -> None:
    rituals = (make_ritual(1, desire="взбодриться"),)
    assert rank_rituals(rituals, answers(desire="отдохнуть")) == []


def test_longer_rituals_are_dropped() -> None:
    """Тридцатиминутный ритуал нельзя предложить тому, у кого пять минут."""
    rituals = (make_ritual(1, duration=30),)
    assert rank_rituals(rituals, answers(duration_min=5)) == []


def test_nearest_lower_duration_wins_over_score() -> None:
    """На «15 минут» сначала идут пятнадцатиминутные, потом пятиминутные."""
    short_but_perfect = make_ritual(
        1, duration=5, time_of_day=["вечер"], mood=["устала"], items=["свечи MALUNA", "чай"]
    )
    exact_duration = make_ritual(2, duration=15, time_of_day=["утро"], mood=["радостно"])

    ranked = rank_rituals((short_but_perfect, exact_duration), answers())

    assert [item.ritual.id for item in ranked] == [2, 1]
    assert ranked[0].score < ranked[1].score  # приоритет корзины важнее баллов


def test_shorter_bucket_used_when_exact_is_empty() -> None:
    rituals = (make_ritual(1, duration=5),)
    ranked = rank_rituals(rituals, answers(duration_min=30))
    assert [item.ritual.id for item in ranked] == [1]


# ── Fallback по продуктам ───────────────────────────────────────────
def test_no_item_matches_still_returns_a_ritual() -> None:
    """Нулевые совпадения по продуктам не отбрасывают ритуалы."""
    rituals = (
        make_ritual(1, items=["ванна"], time_of_day=["вечер"]),
        make_ritual(2, items=["душ"], mood=["устала"]),
    )
    ranked = rank_rituals(rituals, answers(items=frozenset({"кофе"})))
    assert len(ranked) == 2
    assert pick_ritual(ranked, frozenset()) is not None


def test_user_always_gets_an_answer_for_every_item_set(content: ContentSnapshot) -> None:
    """На любом наборе ответов из реального контента ритуал находится."""
    from bot.content.schemas import DESIRE_VALUES, ITEM_VALUES, MOOD_VALUES, TIME_OF_DAY_VALUES

    for desire in DESIRE_VALUES:
        for duration in (5, 15, 30):
            for time_of_day in TIME_OF_DAY_VALUES:
                for mood in MOOD_VALUES:
                    for item in ITEM_VALUES:
                        ranked = rank_rituals(
                            content.active_rituals,
                            RitualAnswers(
                                time_of_day=time_of_day,
                                duration_min=duration,
                                mood=mood,
                                desire=desire,
                                items=frozenset({item}),
                            ),
                        )
                        assert ranked, f"{desire} / {duration} / {time_of_day} / {mood} / {item}"


# ── Порядок выдачи ──────────────────────────────────────────────────
def test_ties_are_shuffled_not_ordered_by_file() -> None:
    """При равных баллах порядок случайный, чтобы ответы не повторялись."""
    rituals = tuple(make_ritual(index) for index in range(1, 6))
    first = [item.ritual.id for item in rank_rituals(rituals, answers(), random.Random(1))]
    second = [item.ritual.id for item in rank_rituals(rituals, answers(), random.Random(7))]
    assert first != second
    assert sorted(first) == sorted(second)


def test_pick_skips_already_shown() -> None:
    rituals = (
        make_ritual(1, time_of_day=["вечер"], mood=["устала"]),
        make_ritual(2, time_of_day=["вечер"], mood=["устала"]),
    )
    ranked = rank_rituals(rituals, answers(), random.Random(0))
    first = pick_ritual(ranked, frozenset())
    assert first is not None
    second = pick_ritual(ranked, frozenset({first.id}))
    assert second is not None and second.id != first.id


def test_pick_returns_none_when_everything_was_shown() -> None:
    rituals = (make_ritual(1),)
    ranked = rank_rituals(rituals, answers())
    assert pick_ritual(ranked, frozenset({1})) is None


@pytest.mark.parametrize("duration", [5, 15, 30])
def test_duration_filter_is_inclusive(duration: int) -> None:
    rituals = (make_ritual(1, duration=duration),)
    assert rank_rituals(rituals, answers(duration_min=duration))
