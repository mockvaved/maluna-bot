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
    SECTION_DISPOSAL,
    SECTION_HOW_TO_USE,
    AstroSign,
    Card,
    FaqItem,
    NumerologyYear,
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
    numerology: tuple[NumerologyYear, ...]

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

    def personal_year(self, number: int) -> NumerologyYear | None:
        for year in self.numerology:
            if year.number == number:
                return year
        return None

    def categories(self) -> list[tuple[str, str]]:
        """Все категории в порядке появления в файле: (код, подпись).

        Индекс в этом списке используется в callback_data, поэтому список
        сквозной — и для категорий внутри групп, и для тех, что в корне.
        """
        labels = self.texts.guide.categories
        ordered: list[tuple[str, str]] = []
        seen: set[str] = set()
        for product in self.active_products:
            if product.category in seen:
                continue
            seen.add(product.category)
            ordered.append((product.category, labels.get(product.category, product.category)))
        return ordered

    def groups(self) -> list[tuple[str, str]]:
        """Группы верхнего уровня в порядке появления: (код, подпись)."""
        labels = self.texts.guide.groups
        ordered: list[tuple[str, str]] = []
        seen: set[str] = set()
        for product in self.active_products:
            if not product.group or product.group in seen:
                continue
            seen.add(product.group)
            ordered.append((product.group, labels.get(product.group, product.group)))
        return ordered

    def root_entries(self) -> list[tuple[str, str, str]]:
        """Верхний уровень меню «Как пользоваться»: (вид, код, подпись).

        Вид — group или category. Товары без группы показываются своей
        категорией сразу в корне, остальные прячутся за группой.
        """
        group_labels = self.texts.guide.groups
        category_labels = self.texts.guide.categories
        entries: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()

        for product in self.active_products:
            if product.group:
                key = ("group", product.group)
                label = group_labels.get(product.group, product.group)
            else:
                key = ("category", product.category)
                label = category_labels.get(product.category, product.category)
            if key in seen:
                continue
            seen.add(key)
            entries.append((key[0], key[1], label))
        return entries

    def categories_in_group(self, group: str) -> list[tuple[str, str]]:
        """Категории внутри группы: (код, подпись). Порядок как в файле."""
        labels = self.texts.guide.categories
        ordered: list[tuple[str, str]] = []
        seen: set[str] = set()
        for product in self.active_products:
            if product.group != group or product.category in seen:
                continue
            seen.add(product.category)
            ordered.append((product.category, labels.get(product.category, product.category)))
        return ordered

    def group_of_category(self, category: str) -> str:
        for product in self.active_products:
            if product.category == category:
                return product.group
        return ""

    def products_in_category(self, category: str) -> tuple[Product, ...]:
        return tuple(p for p in self.active_products if p.category == category)

    def ritual_links(self, items: Sequence[str]) -> list[tuple[str, str, str]]:
        """Куда ведут кнопки предметов под ритуалом: (вид, код, подпись).

        Карта предмет → цель живёт в texts.yaml (ritual.item_links). Цель —
        либо id конкретного товара, либо код группы: у «свечей MALUNA» нет
        одной карточки, их 35, поэтому предмет ведёт в раздел «Свечи».
        Предметы вроде душа и чая продуктами бренда не являются и в карте
        отсутствуют, поэтому кнопок для них не будет.
        """
        links = self.texts.ritual.item_links
        result: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()

        for item in items:
            target = links.get(item)
            if target is None:
                continue

            product = self.product(target)
            if product is not None:
                key = ("product", product.id)
                label = product.name
            elif any(code == target for code, _ in self.groups()):
                key = ("group", target)
                label = dict(self.groups())[target]
            else:
                logger.warning("ritual_item_link_unresolved", extra={"item_link": target})
                continue

            if key in seen:
                continue
            seen.add(key)
            result.append((key[0], key[1], label))
        return result

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
            "numerology": len(self.numerology),
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
        numerology=_check_numerology(
            tuple(loader.load_list(content_dir, "numerology_2027", NumerologyYear))
        ),
    )


def _check_numerology(years: tuple[NumerologyYear, ...]) -> tuple[NumerologyYear, ...]:
    """Разборов должно быть ровно девять, по одному на цифру 1–9.

    Пропуск любой цифры оставил бы часть людей без прогноза, поэтому
    проверяем на старте, а не в момент, когда человек прислал дату.
    """
    numbers = {year.number for year in years}
    missing = sorted(set(range(1, 10)) - numbers)
    if missing:
        raise loader.ContentError(
            "numerology_2027: missing entries for numbers "
            + ", ".join(str(number) for number in missing)
        )
    return years


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
