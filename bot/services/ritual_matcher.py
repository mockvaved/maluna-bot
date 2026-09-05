"""Подбор ритуала по пяти ответам (ТЗ, раздел 8).

Жёсткие фильтры:
  1. desire совпадает точно, иначе ритуал выбывает;
  2. duration_min <= времени, которое есть у человека, а среди
     оставшихся приоритет у ближайшей меньшей длительности: на «15 минут»
     сначала пятнадцатиминутные, и только если таких нет — пятиминутные.

Скоринг по прошедшим фильтры:
  3. +1 за совпадение времени суток («любое» даёт +1 всегда);
  4. +1 за каждое совпавшее настроение («любое» даёт +1 всегда);
  5. +1 за каждый продукт из items, который человек отметил дома.

Совпадений по продуктам может не быть вообще — это не повод отбрасывать
ритуалы: пользователь не должен остаться без ответа ни при каком наборе
ответов.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from bot.content.schemas import ANY_VALUE, Ritual


@dataclass(frozen=True, slots=True)
class RitualAnswers:
    time_of_day: str
    duration_min: int
    mood: str
    desire: str
    items: frozenset[str]


@dataclass(frozen=True, slots=True)
class ScoredRitual:
    ritual: Ritual
    score: int


def score_ritual(ritual: Ritual, answers: RitualAnswers) -> int:
    score = 0
    if ANY_VALUE in ritual.time_of_day or answers.time_of_day in ritual.time_of_day:
        score += 1
    for mood in ritual.mood:
        if mood == ANY_VALUE or mood == answers.mood:
            score += 1
    score += sum(1 for item in ritual.items if item in answers.items)
    return score


def _duration_bucket(rituals: tuple[Ritual, ...], limit: int) -> tuple[Ritual, ...]:
    """Ритуалы ближайшей подходящей длительности, не длиннее limit."""
    durations = sorted({r.duration_min for r in rituals if r.duration_min <= limit}, reverse=True)
    for duration in durations:
        bucket = tuple(r for r in rituals if r.duration_min == duration)
        if bucket:
            return bucket
    return ()


def rank_rituals(
    rituals: tuple[Ritual, ...], answers: RitualAnswers, rng: random.Random | None = None
) -> list[ScoredRitual]:
    """Все подходящие ритуалы от лучшего к худшему.

    Внутри одинакового score порядок случайный, чтобы повторное
    прохождение с теми же ответами не выдавало один и тот же ритуал.
    """
    rng = rng or random.Random()

    by_desire = tuple(r for r in rituals if r.desire == answers.desire)
    if not by_desire:
        return []

    fitting = tuple(r for r in by_desire if r.duration_min <= answers.duration_min)
    if not fitting:
        return []

    # Ближайшая меньшая длительность идёт первой, более короткие — следом,
    # чтобы «Другой вариант» не упирался в одну корзину.
    ordered_buckets: list[tuple[Ritual, ...]] = []
    remaining = fitting
    while remaining:
        bucket = _duration_bucket(remaining, answers.duration_min)
        if not bucket:
            break
        ordered_buckets.append(bucket)
        bucket_ids = {r.id for r in bucket}
        remaining = tuple(r for r in remaining if r.id not in bucket_ids)

    ranked: list[ScoredRitual] = []
    for bucket in ordered_buckets:
        scored = [ScoredRitual(ritual=r, score=score_ritual(r, answers)) for r in bucket]
        rng.shuffle(scored)
        scored.sort(key=lambda item: item.score, reverse=True)
        ranked.extend(scored)
    return ranked


def pick_ritual(
    ranked: list[ScoredRitual], already_shown: frozenset[int], tolerance: int = 1
) -> Ritual | None:
    """Лучший ритуал, который ещё не показывали в этой сессии.

    Показанный ранее ритуал не повторяется, пока есть альтернатива, чьё
    отставание по score не больше tolerance. Если альтернатив нет —
    возвращаем лучший из оставшихся, но не пустоту.
    """
    if not ranked:
        return None

    best_score = ranked[0].score
    fresh = [item for item in ranked if item.ritual.id not in already_shown]
    if fresh:
        acceptable = [item for item in fresh if item.score >= best_score - tolerance]
        return (acceptable or fresh)[0].ritual
    return None
