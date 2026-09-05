"""✨ Собери свой ритуал — пять вопросов и подбор ритуала под ответы.

Ответы живут только в FSM (память или Redis с TTL 30 минут) и стираются,
когда человек уходит в меню. На диск они не попадают. В events пишутся
только выбранные варианты из фиксированных списков — свободного текста в
этом сценарии нет вовсе.
"""

from __future__ import annotations

import logging
import random

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.content.schemas import RitualQuestion, Texts, duration_to_minutes
from bot.content.store import ContentSnapshot, ContentStore
from bot.db.repo import Repository
from bot.handlers.common import render, reset_flow, show_main_menu, show_screen, user_id_of
from bot.keyboards.builders import ritual_question, ritual_result
from bot.keyboards.callbacks import MenuCB, RitualCB
from bot.services.ritual_matcher import RitualAnswers, ScoredRitual, pick_ritual, rank_rituals
from bot.states import KEY_ANSWERS, KEY_RANKED, KEY_SHOWN_RITUALS, KEY_STEP, RitualFlow

logger = logging.getLogger(__name__)

router = Router(name="ritual")


# ── Вход в сценарий ─────────────────────────────────────────────────
@router.callback_query(MenuCB.filter(F.section == "ritual"))
async def start_flow(
    callback: CallbackQuery, state: FSMContext, content_store: ContentStore, repo: Repository
) -> None:
    await callback.answer()
    await reset_flow(state)
    await state.set_state(RitualFlow.answering)
    await state.update_data({KEY_STEP: 0, KEY_ANSWERS: {}})
    await repo.log_event(user_id_of(callback), "ritual_started")
    await _render_question(callback, state, content_store.current)


# ── Ответ на вопрос с одним вариантом ───────────────────────────────
@router.callback_query(RitualFlow.answering, RitualCB.filter(F.action == "pick"))
async def pick_option(
    callback: CallbackQuery,
    callback_data: RitualCB,
    state: FSMContext,
    content_store: ContentStore,
    repo: Repository,
) -> None:
    await callback.answer()
    content = content_store.current
    data = await state.get_data()
    step = int(data.get(KEY_STEP, 0))
    questions = content.texts.ritual.questions

    if not 0 <= step < len(questions):
        await _restart(callback, state, content)
        return

    question = questions[step]
    if not 0 <= callback_data.value < len(question.options):
        return

    answers = dict(data.get(KEY_ANSWERS, {}))
    answers[question.key] = question.options[callback_data.value]
    await state.update_data({KEY_ANSWERS: answers, KEY_STEP: step + 1})
    await _advance(callback, state, content, repo)


# ── Мультивыбор на пятом вопросе ────────────────────────────────────
@router.callback_query(RitualFlow.answering, RitualCB.filter(F.action == "toggle"))
async def toggle_option(
    callback: CallbackQuery,
    callback_data: RitualCB,
    state: FSMContext,
    content_store: ContentStore,
) -> None:
    await callback.answer()
    content = content_store.current
    data = await state.get_data()
    step = int(data.get(KEY_STEP, 0))
    questions = content.texts.ritual.questions

    if not 0 <= step < len(questions):
        await _restart(callback, state, content)
        return

    question = questions[step]
    if not question.multi or not 0 <= callback_data.value < len(question.options):
        return

    option = question.options[callback_data.value]
    answers = dict(data.get(KEY_ANSWERS, {}))
    selected: list[str] = list(answers.get(question.key, []))
    if option in selected:
        selected.remove(option)
    else:
        selected.append(option)
    answers[question.key] = selected
    await state.update_data({KEY_ANSWERS: answers})
    await _render_question(callback, state, content)


@router.callback_query(RitualFlow.answering, RitualCB.filter(F.action == "done"))
async def finish_multi(
    callback: CallbackQuery, state: FSMContext, content_store: ContentStore, repo: Repository
) -> None:
    content = content_store.current
    data = await state.get_data()
    step = int(data.get(KEY_STEP, 0))
    questions = content.texts.ritual.questions

    if not 0 <= step < len(questions):
        await callback.answer()
        await _restart(callback, state, content)
        return

    question = questions[step]
    if not question.multi:
        await callback.answer()
        return

    selected = (await state.get_data()).get(KEY_ANSWERS, {}).get(question.key, [])
    if not selected:
        # Без единой галочки подбор получится слишком общим — просим отметить.
        await callback.answer(content.texts.ritual.multi_empty, show_alert=True)
        return

    await callback.answer()
    await state.update_data({KEY_STEP: step + 1})
    await _advance(callback, state, content, repo)


# ── Навигация ───────────────────────────────────────────────────────
@router.callback_query(RitualFlow.answering, RitualCB.filter(F.action == "back"))
async def go_back(
    callback: CallbackQuery, state: FSMContext, content_store: ContentStore
) -> None:
    await callback.answer()
    content = content_store.current
    data = await state.get_data()
    step = int(data.get(KEY_STEP, 0)) - 1

    if step < 0:
        await reset_flow(state)
        await show_main_menu(callback, content.texts)
        return

    await state.update_data({KEY_STEP: step})
    await _render_question(callback, state, content)


@router.callback_query(RitualCB.filter(F.action == "cancel"))
async def cancel(callback: CallbackQuery, state: FSMContext, content_store: ContentStore) -> None:
    await callback.answer()
    texts = content_store.current.texts
    await reset_flow(state)
    await show_main_menu(callback, texts, prefix=texts.ritual.cancelled)


@router.callback_query(RitualCB.filter(F.action == "another"))
async def another_option(
    callback: CallbackQuery, state: FSMContext, content_store: ContentStore, repo: Repository
) -> None:
    """Следующий ритуал по убыванию score, уже показанные пропускаются."""
    await callback.answer()
    content = content_store.current
    await _show_result(callback, state, content, repo)


# ── Внутренняя механика ─────────────────────────────────────────────
async def _advance(
    callback: CallbackQuery, state: FSMContext, content: ContentSnapshot, repo: Repository
) -> None:
    """Показывает следующий вопрос или, если вопросы кончились, ритуал."""
    data = await state.get_data()
    step = int(data.get(KEY_STEP, 0))
    if step < len(content.texts.ritual.questions):
        await _render_question(callback, state, content)
        return
    await _prepare_ranking(state, content, repo, user_id_of(callback))
    await _show_result(callback, state, content, repo)


async def _render_question(
    callback: CallbackQuery, state: FSMContext, content: ContentSnapshot
) -> None:
    texts = content.texts
    data = await state.get_data()
    step = int(data.get(KEY_STEP, 0))
    questions = texts.ritual.questions
    if not 0 <= step < len(questions):
        await _restart(callback, state, content)
        return

    question = questions[step]
    selected = frozenset(data.get(KEY_ANSWERS, {}).get(question.key, []) or [])
    await show_screen(
        callback,
        _question_text(texts, question, step),
        ritual_question(texts, question, step, selected),
    )


def _question_text(texts: Texts, question: RitualQuestion, step: int) -> str:
    progress = render(
        texts.ritual.progress, current=step + 1, total=len(texts.ritual.questions)
    )
    lines = [progress, "", question.text]
    if question.multi:
        lines.append(texts.ritual.multi_hint)
    return "\n".join(lines)


async def _prepare_ranking(
    state: FSMContext, content: ContentSnapshot, repo: Repository, user_id: int
) -> None:
    """Считает порядок ритуалов один раз на прохождение и кладёт его в FSM.

    Порядок фиксируется, чтобы «Другой вариант» шёл по убыванию score, а не
    пересобирал случайную перестановку на каждое нажатие.
    """
    data = await state.get_data()
    raw = data.get(KEY_ANSWERS, {})
    answers = _build_answers(content, raw)
    if answers is None:
        await state.update_data({KEY_RANKED: []})
        return

    ranked = rank_rituals(content.active_rituals, answers, random.Random())
    await state.update_data({KEY_RANKED: [[item.ritual.id, item.score] for item in ranked]})
    await repo.log_event(user_id, "ritual_answers", _event_payload(raw))


def _build_answers(content: ContentSnapshot, raw: dict[str, object]) -> RitualAnswers | None:
    keys = {question.key for question in content.texts.ritual.questions}
    if not keys <= set(raw):
        return None
    try:
        duration = duration_to_minutes(str(raw["duration"]))
    except ValueError:
        logger.warning("bad_duration_answer")
        return None
    return RitualAnswers(
        time_of_day=str(raw["time_of_day"]),
        duration_min=duration,
        mood=str(raw["mood"]),
        desire=str(raw["desire"]),
        items=frozenset(raw.get("items", []) or []),
    )


def _event_payload(raw: dict[str, object]) -> dict[str, object]:
    """В статистику идут только выбранные варианты из фиксированных списков."""
    return {
        "time_of_day": raw.get("time_of_day"),
        "duration": raw.get("duration"),
        "mood": raw.get("mood"),
        "desire": raw.get("desire"),
        "items": sorted(raw.get("items", []) or []),
    }


async def _show_result(
    callback: CallbackQuery, state: FSMContext, content: ContentSnapshot, repo: Repository
) -> None:
    texts = content.texts
    data = await state.get_data()
    ranked = _restore_ranking(content, data.get(KEY_RANKED, []))
    shown: list[int] = list(data.get(KEY_SHOWN_RITUALS, []))

    ritual = pick_ritual(ranked, frozenset(shown))
    if ritual is None:
        # Всё подходящее уже показано либо под ответы ничего не нашлось.
        message = texts.ritual.no_more if ranked else texts.guide.empty_section
        await reset_flow(state)
        await show_main_menu(callback, texts, prefix=message)
        return

    shown.append(ritual.id)
    await state.update_data({KEY_SHOWN_RITUALS: shown})
    await repo.log_event(user_id_of(callback), "ritual_shown", {"ritual_id": ritual.id})

    links = content.ritual_links(ritual.items)
    body = render(texts.ritual.result, title=ritual.title, text=ritual.text.strip()).strip()
    if links:
        body = f"{body}\n\n{texts.ritual.products_header}"

    has_alternative = pick_ritual(ranked, frozenset(shown)) is not None
    await show_screen(callback, body, ritual_result(texts, content, links, has_alternative))


def _restore_ranking(content: ContentSnapshot, stored: list) -> list[ScoredRitual]:
    """Восстанавливает порядок из FSM, пропуская ритуалы, которых больше нет.

    Контент мог измениться командой /reload, пока человек отвечал на вопросы.
    """
    ranked: list[ScoredRitual] = []
    for entry in stored:
        try:
            ritual_id, score = entry
        except (TypeError, ValueError):
            continue
        ritual = content.ritual(int(ritual_id))
        if ritual is not None:
            ranked.append(ScoredRitual(ritual=ritual, score=int(score)))
    return ranked


async def _restart(
    callback: CallbackQuery, state: FSMContext, content: ContentSnapshot
) -> None:
    """Состояние разъехалось с контентом (например, после /reload) — в меню."""
    logger.info("ritual_state_reset")
    await reset_flow(state)
    await show_main_menu(callback, content.texts)
