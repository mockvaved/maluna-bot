"""Контент в памяти процесса.

Читается один раз на старте, дальше все хендлеры берут данные отсюда.
Команда /reload собирает новый снимок и подменяет ссылку целиком: если
новый контент не проходит валидацию, в работе остаётся прежний.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from bot.content import loader
from bot.content.schemas import (
    ITEM_TO_CATEGORY,
    SECTION_DISPOSAL,
    SECTION_HOW_TO_USE,
    AstroSign,
    Card,
    FaqItem,
    Practice,
    Product,
    Replies,
    Ritual,
    Texts,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ContentSnapshot:
    texts: Texts
    replies: Replies
    cards: tuple[Card, ...]
    rituals: tuple[Ritual, ...]
    products: tuple[Product, ...]
    astro: tuple[AstroSign, ...]
    faq: tuple[FaqItem, ...]
    practices: tuple[Practice, ...]

    # ── Активный контент: то, что реально показывается пользователю ──
    @property
    def active_cards(self) -> tuple[Card, ...]:
        return tuple(card for card in self.cards if card.active)

    @property
    def active_rituals(self) -> tuple[Ritual, ...]:
        return tuple(ritual for ritual in self.rituals if ritual.active)

    @property
    def active_products(self) -> tuple[Product, ...]:
        return tuple(product for product in self.products if product.active)

    @property
    def active_practices(self) -> tuple[Practice, ...]:
        return tuple(
            sorted((p for p in self.practices if p.active), key=lambda p: (p.order, p.title))
        )

    def product(self, product_id: str) -> Product | None:
        for product in self.active_products:
            if product.id == product_id:
                return product
        return None

    def practice(self, practice_id: str) -> Practice | None:
        for practice in self.active_practices:
            if practice.id == practice_id:
                return practice
        return None

    def card(self, card_id: str) -> Card | None:
        for card in self.cards:
            if card.id == card_id:
                return card
        return None

    def ritual(self, ritual_id: int) -> Ritual | None:
        for ritual in self.active_rituals:
            if ritual.id == ritual_id:
                return ritual
        return None

    def sign(self, sign_name: str) -> AstroSign | None:
        for sign in self.astro:
            if sign.sign == sign_name:
                return sign
        return None

    def categories(self) -> list[tuple[str, str]]:
        """Категории продуктов в порядке появления в файле: (код, подпись)."""
        labels = self.texts.guide.categories
        ordered: list[tuple[str, str]] = []
        seen: set[str] = set()
        for product in self.active_products:
            if product.category in seen:
                continue
            seen.add(product.category)
            ordered.append((product.category, labels.get(product.category, product.category)))
        return ordered

    def products_in_category(self, category: str) -> tuple[Product, ...]:
        return tuple(p for p in self.active_products if p.category == category)

    def products_for_items(self, items: Sequence[str]) -> list[Product]:
        """Продукты MALUNA, которые участвуют в ритуале.

        Предметы из пятого вопроса — это категории, а не конкретные позиции,
        поэтому показываем все активные продукты подходящих категорий.
        """
        categories = [
            ITEM_TO_CATEGORY[item] for item in items if item in ITEM_TO_CATEGORY
        ]
        return [product for product in self.active_products if product.category in categories]

    def faq_section(self, section: str) -> tuple[FaqItem, ...]:
        return tuple(
            sorted(
                (item for item in self.faq if item.active and item.section == section),
                key=lambda item: (item.order, item.question),
            )
        )

    @property
    def how_to_use_faq(self) -> tuple[FaqItem, ...]:
        return self.faq_section(SECTION_HOW_TO_USE)

    @property
    def disposal_faq(self) -> tuple[FaqItem, ...]:
        return self.faq_section(SECTION_DISPOSAL)

    def stats(self) -> dict[str, int]:
        return {
            "cards": len(self.active_cards),
            "rituals": len(self.active_rituals),
            "products": len(self.active_products),
            "astro_signs": len(self.astro),
            "faq": len(self.faq),
            "practices": len(self.active_practices),
        }


def load_snapshot(content_dir: Path) -> ContentSnapshot:
    """Читает все файлы. Бросает ContentError, если хоть один невалиден."""
    return ContentSnapshot(
        texts=loader.load_object(content_dir, "texts", Texts),
        replies=loader.load_object(content_dir, "replies", Replies),
        cards=tuple(loader.load_list(content_dir, "cards", Card)),
        rituals=tuple(loader.load_list(content_dir, "rituals", Ritual)),
        products=tuple(loader.load_list(content_dir, "products", Product)),
        astro=tuple(loader.load_list(content_dir, "astro_2027", AstroSign)),
        faq=tuple(loader.load_list(content_dir, "faq", FaqItem)),
        practices=tuple(loader.load_list(content_dir, "practices", Practice)),
    )


class ContentStore:
    """Держит актуальный снимок контента и умеет его перечитывать."""

    def __init__(self, content_dir: Path) -> None:
        self._content_dir = content_dir
        self._snapshot = load_snapshot(content_dir)
        logger.info("content_loaded", extra=self._snapshot.stats())

    @property
    def current(self) -> ContentSnapshot:
        return self._snapshot

    def reload(self) -> ContentSnapshot:
        """Перечитывает файлы. При ошибке оставляет прежний снимок в работе."""
        snapshot = load_snapshot(self._content_dir)
        self._snapshot = snapshot
        logger.info("content_reloaded", extra=snapshot.stats())
        return snapshot
