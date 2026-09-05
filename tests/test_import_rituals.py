"""Импорт базы ритуалов из Excel."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import import_rituals  # noqa: E402

from bot.content.loader import load_list  # noqa: E402
from bot.content.schemas import Ritual  # noqa: E402

HEADERS = import_rituals.TEMPLATE_HEADERS
ROW = [1, "вечер, день", 15, "устала", "отдохнуть", "свечи MALUNA, чай", "Название", "Текст", "да"]


def make_workbook(tmp_path: Path, rows: list[list], sheet_name: str = "Ритуалы") -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    path = tmp_path / "rituals.xlsx"
    workbook.save(path)
    return path


def test_import_reads_lists_and_flags(tmp_path: Path) -> None:
    source = make_workbook(tmp_path, [ROW])
    target = tmp_path / "rituals.yaml"

    import_rituals.write_yaml(import_rituals.to_rituals(import_rituals.read_rows(source)), target)

    rituals = load_list(tmp_path, "rituals", Ritual)
    assert len(rituals) == 1
    assert rituals[0].time_of_day == ["вечер", "день"]
    assert rituals[0].items == ["свечи MALUNA", "чай"]
    assert rituals[0].active is True


def test_multiline_text_stays_readable(tmp_path: Path) -> None:
    """Текст ритуала пишется блоком после |, а не строкой с \\n."""
    row = list(ROW)
    row[7] = "Первый абзац.\n\nВторой абзац."
    source = make_workbook(tmp_path, [row])
    target = tmp_path / "rituals.yaml"

    import_rituals.write_yaml(import_rituals.to_rituals(import_rituals.read_rows(source)), target)

    body = target.read_text(encoding="utf-8")
    assert "text: |" in body
    assert "\\n" not in body
    assert load_list(tmp_path, "rituals", Ritual)[0].text.startswith("Первый абзац.")


def test_empty_active_cell_means_active(tmp_path: Path) -> None:
    row = list(ROW)
    row[8] = None
    source = make_workbook(tmp_path, [row])
    assert import_rituals.to_rituals(import_rituals.read_rows(source))[0]["active"] is True


def test_no_in_active_column_hides_the_ritual(tmp_path: Path) -> None:
    row = list(ROW)
    row[8] = "нет"
    source = make_workbook(tmp_path, [row])
    assert import_rituals.to_rituals(import_rituals.read_rows(source))[0]["active"] is False


def test_empty_trailing_rows_are_skipped(tmp_path: Path) -> None:
    source = make_workbook(tmp_path, [ROW, [None] * 9, [None] * 9])
    assert len(import_rituals.read_rows(source)) == 1


def test_value_outside_vocabulary_is_reported_with_line_number(tmp_path: Path) -> None:
    row = list(ROW)
    row[1] = "ночь"
    source = make_workbook(tmp_path, [row])

    with pytest.raises(import_rituals.ImportError_) as exc:
        import_rituals.to_rituals(import_rituals.read_rows(source))
    assert "строка 2" in str(exc.value)


def test_duplicate_ids_are_reported(tmp_path: Path) -> None:
    source = make_workbook(tmp_path, [ROW, ROW])
    with pytest.raises(import_rituals.ImportError_, match="дважды"):
        import_rituals.to_rituals(import_rituals.read_rows(source))


def test_wrong_sheet_name_is_reported(tmp_path: Path) -> None:
    source = make_workbook(tmp_path, [ROW], sheet_name="Лист1")
    with pytest.raises(import_rituals.ImportError_, match="Ритуалы"):
        import_rituals.read_rows(source)


def test_missing_column_is_reported(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Ритуалы"
    sheet.append(["ID", "Название"])
    sheet.append([1, "Название"])
    path = tmp_path / "rituals.xlsx"
    workbook.save(path)

    with pytest.raises(import_rituals.ImportError_, match="не хватает колонок"):
        import_rituals.read_rows(path)


def test_template_round_trip_keeps_content(tmp_path: Path) -> None:
    """Таблица из yaml и обратно в yaml даёт те же ритуалы."""
    from bot.config import PROJECT_ROOT

    xlsx = tmp_path / "MALUNA_rituals.xlsx"
    import_rituals.write_template(xlsx, PROJECT_ROOT / "content" / "rituals.yaml")

    target = tmp_path / "rituals.yaml"
    import_rituals.write_yaml(import_rituals.to_rituals(import_rituals.read_rows(xlsx)), target)

    original = load_list(PROJECT_ROOT / "content", "rituals", Ritual)
    imported = load_list(tmp_path, "rituals", Ritual)

    assert {r.id for r in imported} == {r.id for r in original}
    by_id = {r.id: r for r in imported}
    for ritual in original:
        assert by_id[ritual.id].title == ritual.title
        assert by_id[ritual.id].text.strip() == ritual.text.strip()
        assert by_id[ritual.id].items == ritual.items
