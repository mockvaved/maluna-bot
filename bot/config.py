"""Конфигурация из переменных окружения. Секреты только в .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(RuntimeError):
    """Не хватает обязательной переменной окружения."""


def _parse_admin_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError as exc:
            raise ConfigError(f"ADMIN_IDS contains a non-numeric value: {chunk!r}") from exc
    return frozenset(ids)


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int] = field(default_factory=frozenset)
    channel_username: str = "@maluna118"
    channel_url: str = "https://t.me/maluna118"
    db_path: Path = PROJECT_ROOT / "data" / "maluna.db"
    content_dir: Path = PROJECT_ROOT / "content"
    health_port: int = 8080
    log_level: str = "INFO"
    redis_url: str | None = None

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


def load_config() -> Config:
    load_dotenv(PROJECT_ROOT / ".env")

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    channel = os.getenv("CHANNEL_USERNAME", "@maluna118").strip()
    if channel and not channel.startswith("@") and not channel.startswith("-"):
        channel = "@" + channel

    def _path(env_name: str, default: Path) -> Path:
        raw = os.getenv(env_name, "").strip()
        if not raw:
            return default
        path = Path(raw)
        return path if path.is_absolute() else PROJECT_ROOT / path

    return Config(
        bot_token=token,
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS", "")),
        channel_username=channel,
        channel_url=os.getenv("CHANNEL_URL", "").strip()
        or f"https://t.me/{channel.lstrip('@')}",
        db_path=_path("DB_PATH", PROJECT_ROOT / "data" / "maluna.db"),
        content_dir=_path("CONTENT_DIR", PROJECT_ROOT / "content"),
        health_port=int(os.getenv("HEALTH_PORT", "8080")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        redis_url=os.getenv("REDIS_URL", "").strip() or None,
    )
