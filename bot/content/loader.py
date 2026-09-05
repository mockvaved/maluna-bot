"""Чтение и валидация контент-файлов.

Файл ищется по базовому имени: сначала .yaml, потом .yml, потом .json.
Владелец может держать контент в любом из этих форматов.

Ошибка валидации превращается в ContentError с человекочитаемым текстом
вида «cards.yaml → элемент #3, поле title: field required», который можно
показать админу в ответ на /reload.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)

_EXTENSIONS = (".yaml", ".yml", ".json")


class ContentError(RuntimeError):
    """Контент-файл отсутствует или не проходит валидацию."""


def resolve_path(content_dir: Path, base_name: str) -> Path:
    for extension in _EXTENSIONS:
        candidate = content_dir / f"{base_name}{extension}"
        if candidate.is_file():
            return candidate
    expected = ", ".join(f"{base_name}{ext}" for ext in _EXTENSIONS)
    raise ContentError(f"{content_dir}: content file not found, expected one of: {expected}")


def read_raw(path: Path) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContentError(f"{path.name}: cannot read file ({exc})") from exc

    try:
        if path.suffix == ".json":
            return json.loads(text)
        # safe_load не исполняет произвольные python-объекты из файла.
        return yaml.safe_load(text)
    except json.JSONDecodeError as exc:
        raise ContentError(f"{path.name}: broken JSON on line {exc.lineno} ({exc.msg})") from exc
    except yaml.YAMLError as exc:
        raise ContentError(f"{path.name}: broken YAML ({_yaml_hint(exc)})") from exc


def _yaml_hint(exc: yaml.YAMLError) -> str:
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or str(exc)
    if mark is not None:
        return f"line {mark.line + 1}, column {mark.column + 1}: {problem}"
    return problem


def load_list(content_dir: Path, base_name: str, model: type[ModelT]) -> list[ModelT]:
    """Читает файл со списком объектов и валидирует каждый элемент."""
    path = resolve_path(content_dir, base_name)
    raw = read_raw(path)

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ContentError(f"{path.name}: expected a list of items, got {type(raw).__name__}")

    items: list[ModelT] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ContentError(f"{path.name}: item #{index + 1} must be a mapping, got {type(entry).__name__}")
        try:
            items.append(model.model_validate(entry))
        except ValidationError as exc:
            item_id = entry.get("id", f"#{index + 1}")
            raise ContentError(f"{path.name}: item {item_id!r} — {_format_errors(exc)}") from exc

    _check_unique_ids(path.name, items)
    return items


def load_object(content_dir: Path, base_name: str, model: type[ModelT]) -> ModelT:
    """Читает файл с одним объектом (texts, replies)."""
    path = resolve_path(content_dir, base_name)
    raw = read_raw(path)

    if not isinstance(raw, dict):
        raise ContentError(f"{path.name}: expected a mapping at the top level, got {type(raw).__name__}")
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise ContentError(f"{path.name}: {_format_errors(exc)}") from exc


def _format_errors(exc: ValidationError, limit: int = 3) -> str:
    parts: list[str] = []
    for error in exc.errors()[:limit]:
        location = ".".join(str(item) for item in error["loc"]) or "<root>"
        parts.append(f"field {location}: {error['msg']}")
    remaining = len(exc.errors()) - limit
    if remaining > 0:
        parts.append(f"and {remaining} more problem(s)")
    return "; ".join(parts)


def _check_unique_ids(file_name: str, items: Sequence[BaseModel]) -> None:
    seen: set[object] = set()
    for item in items:
        item_id = getattr(item, "id", None)
        if item_id is None:
            return
        if item_id in seen:
            raise ContentError(f"{file_name}: duplicate id {item_id!r}")
        seen.add(item_id)
