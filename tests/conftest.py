from __future__ import annotations

from pathlib import Path

import pytest

from bot.config import PROJECT_ROOT
from bot.content.store import ContentSnapshot, load_snapshot

CONTENT_DIR = PROJECT_ROOT / "content"


@pytest.fixture(scope="session")
def content() -> ContentSnapshot:
    """Настоящий контент проекта: тесты заодно проверяют, что он валиден."""
    return load_snapshot(CONTENT_DIR)


@pytest.fixture
def content_dir() -> Path:
    return CONTENT_DIR
