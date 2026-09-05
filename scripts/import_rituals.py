#!/usr/bin/env python3
"""Импорт базы ритуалов из Excel в content/rituals.yaml.

Как пользоваться:
  1. Заполни лист «Ритуалы» в файле MALUNA_rituals.xlsx
  2. Запусти:  python scripts/import_rituals.py
  3. Отправь боту команду /reload

Если таблицы ещё нет, собери её из текущего contents/rituals.yaml:
     python scripts/import_rituals.py --template

Скрипт перезаписывает content/rituals.yaml целиком, поэтому правки руками
в этом файле потеряются. Веди базу либо в таблице, либо в файле.

Колонки листа (регистр и лишние пробелы не важны):
  ID | Время суток | Время (мин) | Настроение | Что хочется |
  Нужные продукты | Название | Текст ритуала | Активен

Списки в ячейках пишутся через запятую: «утро, день».
Колонка «Активен» необязательна: пусто = ритуал активен.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from bot.config import PROJECT_ROOT  # noqa: E402
from bot.content.schemas import Ritual  # noqa: E402

SHEET_NAME = "Ритуалы"
DEFAULT_SOURCE = PROJECT_ROOT / "MALUNA_rituals.xlsx"
DEFAULT_TARGET = PROJECT_ROOT / "content" / "rituals.yaml"

# Заголовок в таблице → поле в rituals.yaml
COLUMNS = {
    "id": "id",
    "время суток": "time_of_day",
    "время (мин)": "duration_min",
    "время мин": "duration_min",
    "настроение": "mood",
    "что хочется": "desire",
    "нужные продукты": "items",
    "название": "title",
    "текст ритуала": "text",
    "текст": "text",
    "активен": "active",
}

LIST_FIELDS = ("time_of_day", "mood", "items")

HEADER = """\
# ═══════════════════════════════════════════════════════════════════
#  БАЗА РИТУАЛОВ ДЛЯ РАЗДЕЛА «✨ СОБЕРИ СВОЙ РИТУАЛ»
#
#  Файл собран скриптом scripts/import_rituals.py из MALUNA_rituals.xlsx.
#  Правки руками потеряются при следующем импорте — меняй таблицу.
#
#  ── КАК БОТ ВЫБИРАЕТ РИТУАЛ ────────────────────────────────────────
#  Сначала жёстко отсекает лишнее:
#    • desire должен точно совпасть с ответом на вопрос «Что хочется»;
#    • duration_min не больше, чем ответ на вопрос про время.
#  Потом считает баллы: +1 за совпадение time_of_day, +1 за каждое
#  совпавшее mood, +1 за каждый предмет из items, который человек
#  отметил дома. Побеждает ритуал с наибольшим счётом.
#
#  ── ДОПУСТИМЫЕ ЗНАЧЕНИЯ (иначе бот не стартует) ────────────────────
#  time_of_day : утро, день, вечер, любое
#  duration_min: 5, 15, 30
#  mood        : устала, тревожно, хочется вдохновения, радостно, любое
#  desire      : отдохнуть, взбодриться, позаботиться о коже, создать уют
#  items       : свечи MALUNA, гидрофильное масло MALUNA,
#                очищающий гель MALUNA, увлажняющий крем MALUNA,
#                душ, ванна, кофе, чай
# ═══════════════════════════════════════════════════════════════════
"""


class _Dumper(yaml.SafeDumper):
    """Пишет YAML так, чтобы файл оставалось удобно читать глазами."""

    def increase_indent(self, flow: bool = False, indentless: bool = False):
        # Элементы списка с отступом, а не вплотную к ключу.
        return super().increase_indent(flow, False)


def _represent_str(dumper: yaml.SafeDumper, data: str):
    # Многострочные тексты ритуалов — блоком после |, без кавычек и \\n.
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(str, _represent_str)


class ImportError_(RuntimeError):
    """Таблица не читается или в ней не хватает колонок."""


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _split(value: Any) -> list[str]:
    return [part.strip() for part in _clean(value).split(",") if part.strip()]


def _as_bool(value: Any) -> bool:
    text = _clean(value).lower()
    if not text:
        return True
    return text not in {"нет", "no", "false", "0", "-", "скрыт", "неактивен"}


def read_rows(path: Path) -> list[dict[str, Any]]:
    workbook = load_workbook(path, data_only=True)
    if SHEET_NAME not in workbook.sheetnames:
        available = ", ".join(workbook.sheetnames)
        raise ImportError_(f"в файле нет листа «{SHEET_NAME}». Есть такие листы: {available}")

    sheet = workbook[SHEET_NAME]
    rows = sheet.iter_rows(values_only=True)

    try:
        header = next(rows)
    except StopIteration as exc:
        raise ImportError_("лист пустой") from exc

    mapping: dict[int, str] = {}
    for index, title in enumerate(header):
        key = _clean(title).lower()
        if key in COLUMNS:
            mapping[index] = COLUMNS[key]

    missing = {"id", "duration_min", "desire", "title", "text"} - set(mapping.values())
    if missing:
        raise ImportError_(f"в таблице не хватает колонок: {', '.join(sorted(missing))}")

    result: list[dict[str, Any]] = []
    for line_number, row in enumerate(rows, start=2):
        raw: dict[str, Any] = {}
        for index, field in mapping.items():
            raw[field] = row[index] if index < len(row) else None
        if not _clean(raw.get("id")) and not _clean(raw.get("title")):
            continue  # пустая строка в конце таблицы

        entry: dict[str, Any] = {"__line": line_number}
        for field, value in raw.items():
            if field in LIST_FIELDS:
                entry[field] = _split(value)
            elif field == "active":
                entry[field] = _as_bool(value)
            elif field in {"id", "duration_min"}:
                entry[field] = _clean(value)
            else:
                entry[field] = _clean(value)
        result.append(entry)
    return result


def to_rituals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Валидирует строки теми же схемами, что и бот, и приводит к виду файла."""
    rituals: list[dict[str, Any]] = []
    problems: list[str] = []

    for entry in rows:
        line = entry.pop("__line")
        try:
            entry["id"] = int(float(entry["id"]))
            entry["duration_min"] = int(float(entry["duration_min"]))
        except (TypeError, ValueError):
            problems.append(f"строка {line}: ID и «Время (мин)» должны быть числами")
            continue

        entry.setdefault("items", [])
        entry.setdefault("active", True)
        try:
            ritual = Ritual.model_validate(entry)
        except Exception as exc:  # noqa: BLE001 — сообщение показываем владельцу целиком
            problems.append(f"строка {line}: {exc}")
            continue
        rituals.append(ritual.model_dump())

    if problems:
        raise ImportError_("\n  ".join(["в таблице есть ошибки:", *problems]))

    seen: set[int] = set()
    for ritual in rituals:
        if ritual["id"] in seen:
            raise ImportError_(f"ID {ritual['id']} встречается в таблице дважды")
        seen.add(ritual["id"])
    return rituals


def write_yaml(rituals: list[dict[str, Any]], target: Path) -> None:
    for ritual in rituals:
        # Блочный скаляр требует перевода строки в конце — иначе pyyaml
        # свернёт текст обратно в кавычки.
        if "\n" in ritual["text"] and not ritual["text"].endswith("\n"):
            ritual["text"] += "\n"

    body = yaml.dump(
        rituals,
        Dumper=_Dumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        indent=2,
        width=100,
    )
    target.write_text(f"{HEADER}\n{body}", encoding="utf-8")


TEMPLATE_HEADERS = [
    "ID",
    "Время суток",
    "Время (мин)",
    "Настроение",
    "Что хочется",
    "Нужные продукты",
    "Название",
    "Текст ритуала",
    "Активен",
]


def write_template(target: Path, source_yaml: Path) -> int:
    """Собирает таблицу из текущего rituals.yaml, чтобы было с чего начать."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    from bot.content.loader import ContentError, load_list

    try:
        rituals = load_list(source_yaml.parent, source_yaml.stem, Ritual)
    except ContentError as exc:
        print(f"❌ {exc}")
        return 1

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_NAME
    sheet.append(TEMPLATE_HEADERS)

    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for ritual in rituals:
        sheet.append(
            [
                ritual.id,
                ", ".join(ritual.time_of_day),
                ritual.duration_min,
                ", ".join(ritual.mood),
                ritual.desire,
                ", ".join(ritual.items),
                ritual.title,
                ritual.text.strip(),
                "да" if ritual.active else "нет",
            ]
        )

    widths = (6, 18, 12, 28, 22, 46, 28, 80, 10)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = width
    for row in sheet.iter_rows(min_row=2):
        row[7].alignment = Alignment(wrap_text=True, vertical="top")

    sheet.freeze_panes = "A2"
    workbook.save(target)
    print(f"✅ Собрал таблицу: {target}")
    print(f"   Внутри {len(rituals)} ритуалов, дописывай строки и запускай импорт.")
    return 0


def main() -> int:
    argv = [arg for arg in sys.argv[1:] if arg != "--template"]
    if "--template" in sys.argv:
        target = Path(argv[0]) if argv else DEFAULT_SOURCE
        return write_template(target, DEFAULT_TARGET)

    source = Path(argv[0]) if argv else DEFAULT_SOURCE
    target = Path(argv[1]) if len(argv) > 1 else DEFAULT_TARGET

    if not source.is_file():
        print(f"❌ Не нашёл файл таблицы: {source}")
        print("   Положи MALUNA_rituals.xlsx в корень проекта или укажи путь аргументом.")
        return 1

    try:
        rituals = to_rituals(read_rows(source))
    except ImportError_ as exc:
        print(f"❌ {exc}")
        return 1

    if not rituals:
        print("❌ В таблице нет ни одной заполненной строки.")
        return 1

    write_yaml(rituals, target)
    print(f"✅ Перенёс {len(rituals)} ритуалов в {target}")
    print("   Теперь отправь боту команду /reload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
