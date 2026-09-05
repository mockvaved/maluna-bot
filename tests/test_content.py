"""Валидация контента: бот не должен стартовать на битом файле."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.content.loader import ContentError, load_list, load_object
from bot.content.schemas import Card, Replies, Ritual, Texts
from bot.content.store import ContentSnapshot, ContentStore, load_snapshot


def write(directory: Path, name: str, body: str) -> None:
    (directory / name).write_text(body, encoding="utf-8")


# ── Реальный контент проекта ────────────────────────────────────────
def test_project_content_is_valid(content: ContentSnapshot) -> None:
    assert content.active_cards
    assert content.active_rituals
    assert len(content.astro) == 12


def test_ritual_answer_options_match_the_vocabulary(content: ContentSnapshot) -> None:
    """Варианты ответов — ключи матчинга, они обязаны совпадать со словарями."""
    from bot.content.schemas import DESIRE_VALUES, ITEM_VALUES, MOOD_VALUES, TIME_OF_DAY_VALUES

    options = {q.key: q.options for q in content.texts.ritual.questions}
    assert set(options["time_of_day"]) <= set(TIME_OF_DAY_VALUES)
    assert set(options["mood"]) <= set(MOOD_VALUES)
    assert set(options["desire"]) <= set(DESIRE_VALUES)
    assert set(options["items"]) <= set(ITEM_VALUES)


def test_no_russian_strings_in_python_sources() -> None:
    """Все тексты интерфейса живут в контенте, а не в коде (ТЗ, раздел 15).

    Комментарии и докстринги на русском разрешены — они помогают
    поддерживать код. Проверяются только строковые литералы.
    """
    import ast
    import re

    from bot.config import PROJECT_ROOT

    cyrillic = re.compile(r"[а-яА-ЯёЁ]")

    # Единственные два исключения, и оба не являются текстом для пользователя:
    #   schemas.py — словари допустимых значений; ТЗ требует, чтобы они
    #     совпадали с ответами кнопок дословно, это ключи матчинга;
    #   main.py — сообщение об ошибке старта в stderr: оно печатается
    #     ровно тогда, когда контент прочитать не удалось, поэтому из
    #     контент-файла взяться не может.
    allowed_files = {"schemas.py", "main.py"}
    offenders: list[str] = []

    for path in (PROJECT_ROOT / "bot").rglob("*.py"):
        if path.name in allowed_files:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            node.body[0].value
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if node in docstrings or not cyrillic.search(node.value):
                continue
            offenders.append(f"{path.name}:{node.lineno}: {node.value[:60]!r}")

    assert not offenders, "Russian UI strings must live in content files:\n" + "\n".join(offenders)


# ── Поведение при ошибках ───────────────────────────────────────────
def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ContentError, match="content file not found"):
        load_list(tmp_path, "cards", Card)


def test_broken_yaml_reports_the_line(tmp_path: Path) -> None:
    write(tmp_path, "cards.yaml", "- id: card_001\n  title: [unclosed\n")
    with pytest.raises(ContentError, match="broken YAML"):
        load_list(tmp_path, "cards", Card)


def test_missing_required_field_names_the_item(tmp_path: Path) -> None:
    write(tmp_path, "cards.yaml", "- id: card_001\n  text: Текст\n")
    with pytest.raises(ContentError) as exc:
        load_list(tmp_path, "cards", Card)
    assert "card_001" in str(exc.value)
    assert "title" in str(exc.value)


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    write(
        tmp_path,
        "cards.yaml",
        "- id: card_001\n  title: A\n  text: B\n- id: card_001\n  title: C\n  text: D\n",
    )
    with pytest.raises(ContentError, match="duplicate id"):
        load_list(tmp_path, "cards", Card)


def test_unknown_field_rejected(tmp_path: Path) -> None:
    """Опечатка в названии поля не проходит молча."""
    write(tmp_path, "cards.yaml", "- id: card_001\n  titel: A\n  title: B\n  text: C\n")
    with pytest.raises(ContentError):
        load_list(tmp_path, "cards", Card)


def test_json_is_accepted_too(tmp_path: Path) -> None:
    write(tmp_path, "cards.json", '[{"id": "card_001", "title": "A", "text": "B"}]')
    assert len(load_list(tmp_path, "cards", Card)) == 1


def test_birthday_tag_rejected() -> None:
    """Бот не знает даты рождения — тега birthday в карточках быть не может."""
    with pytest.raises(Exception, match="birthday"):
        Card(id="card_001", title="A", text="B", tags=["birthday"])


def test_name_placeholder_rejected(tmp_path: Path, content: ContentSnapshot) -> None:
    """Обращение безличное: плейсхолдера {name} в приветствии быть не должно."""
    import yaml

    data = content.texts.model_dump()
    data["welcome"] = "Привет, {name}!"
    write(tmp_path, "texts.yaml", yaml.safe_dump(data, allow_unicode=True))
    with pytest.raises(ContentError, match="name"):
        load_object(tmp_path, "texts", Texts)


# ── Словари ритуалов ────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("time_of_day", ["ночь"]),
        ("mood", ["весело"]),
        ("items", ["шампунь MALUNA"]),
        ("desire", "поспать"),
    ],
)
def test_value_outside_vocabulary_is_an_error(field: str, value: object) -> None:
    payload = {
        "id": 1,
        "time_of_day": ["вечер"],
        "duration_min": 15,
        "mood": ["устала"],
        "desire": "отдохнуть",
        "items": ["чай"],
        "title": "Название",
        "text": "Текст",
    }
    payload[field] = value
    with pytest.raises(Exception):
        Ritual.model_validate(payload)


def test_duration_outside_dictionary_is_an_error() -> None:
    with pytest.raises(Exception):
        Ritual.model_validate(
            {
                "id": 1,
                "time_of_day": ["вечер"],
                "duration_min": 20,
                "mood": ["устала"],
                "desire": "отдохнуть",
                "items": [],
                "title": "Название",
                "text": "Текст",
            }
        )


# ── /reload ─────────────────────────────────────────────────────────
def test_reload_keeps_previous_content_on_error(tmp_path: Path, content_dir: Path) -> None:
    """Битый файл после /reload не роняет бота: в работе остаётся прежний снимок."""
    import shutil

    working = tmp_path / "content"
    shutil.copytree(content_dir, working, ignore=shutil.ignore_patterns("_source"))

    store = ContentStore(working)
    before = store.current.stats()

    (working / "cards.yaml").write_text("- id: card_001\n  title: [broken\n", encoding="utf-8")
    with pytest.raises(ContentError):
        store.reload()

    assert store.current.stats() == before


def test_reload_picks_up_changes(tmp_path: Path, content_dir: Path) -> None:
    import shutil

    working = tmp_path / "content"
    shutil.copytree(content_dir, working, ignore=shutil.ignore_patterns("_source"))

    store = ContentStore(working)
    before = len(store.current.active_cards)

    with (working / "cards.yaml").open("a", encoding="utf-8") as handle:
        handle.write('\n- id: card_new\n  title: "Новая"\n  text: "Текст"\n  active: true\n')

    assert len(store.reload().active_cards) == before + 1


def test_replies_rules_are_loadable(content_dir: Path) -> None:
    replies = load_object(content_dir, "replies", Replies)
    assert replies.fallback
    assert {rule.id for rule in replies.rules} >= {"emotional", "health", "order", "privacy"}


def test_snapshot_loads_from_json_copy(tmp_path: Path, content_dir: Path) -> None:
    """Загрузчик одинаково работает с YAML и JSON."""
    import json
    import shutil

    import yaml

    working = tmp_path / "content"
    shutil.copytree(content_dir, working, ignore=shutil.ignore_patterns("_source"))
    for path in list(working.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        path.with_suffix(".json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        path.unlink()

    assert load_snapshot(working).stats()["astro_signs"] == 12
