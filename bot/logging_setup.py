"""Структурированные логи в JSON.

В логи не попадают персональные данные: свободный текст пользователя, дата
рождения, содержимое FSM. Допустимо логировать user_id, тип события и знак
зодиака. Фильтр ниже — второй рубеж защиты на случай, если что-то из этого
всё же попадёт в запись.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone

# Поля, которые LogRecord заполняет сам: их нельзя принимать за наши extra.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}

# Ключи, которые нельзя писать в лог ни при каких обстоятельствах.
_FORBIDDEN_KEYS = frozenset(
    {
        "text",
        "message_text",
        "birth_date",
        "birth_day",
        "birth_month",
        "birth_year",
        "name",
        "first_name",
        "last_name",
        "username",
        "phone",
        "phone_number",
        "location",
    }
)

# Похоже на дату рождения в свободном тексте: 01.02 или 01.02.1990
_DATE_RE = re.compile(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b")

_REDACTED = "[redacted]"


class PrivacyFilter(logging.Filter):
    """Вырезает потенциальные персональные данные из записей лога."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key in list(record.__dict__):
            if key in _RESERVED:
                continue
            if key.lower() in _FORBIDDEN_KEYS:
                record.__dict__[key] = _REDACTED
        if isinstance(record.msg, str):
            record.msg = _DATE_RE.sub(_REDACTED, record.msg)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED:
                continue
            payload[key] = value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(PrivacyFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))

    # aiogram логирует апдейты целиком на DEBUG — это персональные данные.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
