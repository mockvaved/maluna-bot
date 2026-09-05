"""Сохранение фото отзывов на диск.

Подлинность отзыва не проверяется: засчитывается любая присланная
картинка — так решил владелец. Задача сервиса только в том, чтобы файл
не потерялся и его потом можно было посмотреть.

Файлы лежат в data/reviews/ с именем вида 2027-01-15_424242_1.jpg:
дата, идентификатор пользователя и порядковый номер за этот день.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.types import Document, PhotoSize

logger = logging.getLogger(__name__)

REVIEWS_DIR = "reviews"

# Больше 20 МБ Telegram боту скачать не даст, но и столько не нужно:
# отзыв — это скриншот.
MAX_FILE_SIZE = 10 * 1024 * 1024

_SAFE_SUFFIX = re.compile(r"^\.[a-z0-9]{1,5}$")


class ReviewSaveError(RuntimeError):
    """Файл не удалось скачать или записать на диск."""


def _suffix_of(file_path: str | None, default: str = ".jpg") -> str:
    """Расширение из пути на стороне Telegram, если оно выглядит здраво."""
    if not file_path:
        return default
    suffix = Path(file_path).suffix.lower()
    return suffix if _SAFE_SUFFIX.match(suffix) else default


def _next_free_path(directory: Path, prefix: str, suffix: str) -> Path:
    index = 1
    while (candidate := directory / f"{prefix}_{index}{suffix}").exists():
        index += 1
    return candidate


async def save_review_photo(
    bot: Bot, data_dir: Path, user_id: int, media: PhotoSize | Document
) -> str:
    """Скачивает картинку и возвращает путь относительно data_dir."""
    if (media.file_size or 0) > MAX_FILE_SIZE:
        raise ReviewSaveError(f"file is too large: {media.file_size} bytes")

    directory = data_dir / REVIEWS_DIR
    directory.mkdir(parents=True, exist_ok=True)

    target: Path | None = None
    try:
        info = await bot.get_file(media.file_id)
        target = _next_free_path(
            directory,
            f"{datetime.now(tz=timezone.utc):%Y-%m-%d}_{user_id}",
            _suffix_of(info.file_path),
        )
        await bot.download_file(info.file_path, destination=target)
    except Exception as exc:  # noqa: BLE001 — сеть, диск или отказ Telegram
        # download_file создаёт файл до того, как польются байты, поэтому
        # после обрыва на диске остаётся пустой огрызок. Убираем его.
        if target is not None:
            target.unlink(missing_ok=True)
        raise ReviewSaveError(str(exc)) from exc

    logger.info(
        "review_photo_saved", extra={"user_id": user_id, "file": target.name}
    )
    return f"{REVIEWS_DIR}/{target.name}"
