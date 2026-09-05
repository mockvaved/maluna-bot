#!/usr/bin/env python3
"""Проверка контент-файлов без запуска бота.

Запуск:  python scripts/validate_content.py [папка]

Показывает, что не так с файлами, теми же правилами, по которым бот
проверяет их на старте. Удобно прогнать после правки контента, чтобы не
уронить бота на продакшене.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import PROJECT_ROOT  # noqa: E402
from bot.content.loader import ContentError  # noqa: E402
from bot.content.store import load_snapshot  # noqa: E402


def main() -> int:
    content_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "content"

    try:
        snapshot = load_snapshot(content_dir)
    except ContentError as exc:
        print("❌ Контент не прошёл проверку:")
        print(f"   {exc}")
        print()
        print("Исправь файл и запусти скрипт ещё раз.")
        return 1

    print(f"✅ Контент в порядке: {content_dir}")
    for name, count in snapshot.stats().items():
        print(f"   {name}: {count}")

    if len(snapshot.active_cards) < 60:
        print()
        print(
            f"⚠️  Предсказаний пока {len(snapshot.active_cards)}. "
            "Чтобы два месяца шли без повторов, нужно 60 и больше."
        )
    if not snapshot.active_products:
        print("⚠️  В products нет активных продуктов — раздел «Как пользоваться» будет пустым.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
