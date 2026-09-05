"""📖 Справочник: как пользоваться, практики со свечами, утилизация.

Меню категорий строится динамически из products.yaml: появился продукт
новой категории — в меню появился новый пункт, код править не нужно.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.config import Config
from bot.content.schemas import Product, Texts
from bot.content.store import ContentSnapshot, ContentStore
from bot.db.repo import Repository
from bot.handlers.common import render, show_photo_screen, show_screen, user_id_of
from bot.keyboards.builders import (
    guide_back,
    guide_category,
    guide_disposal,
    guide_group,
    guide_how_to_use,
    guide_practices,
    guide_root,
)
from bot.keyboards.callbacks import GuideCB, MenuCB

router = Router(name="guide")


@router.callback_query(MenuCB.filter(F.section == "guide"))
@router.callback_query(GuideCB.filter(F.action == "root"))
async def show_root(
    callback: CallbackQuery, content_store: ContentStore, repo: Repository
) -> None:
    await callback.answer()
    texts = content_store.current.texts
    await repo.log_event(user_id_of(callback), "guide_opened")
    await show_screen(callback, texts.guide.title, guide_root(texts))


@router.callback_query(GuideCB.filter(F.action == "howto"))
async def show_how_to_use(callback: CallbackQuery, content_store: ContentStore) -> None:
    await callback.answer()
    content = content_store.current
    texts = content.texts
    if not content.how_to_use_faq and not content.categories():
        await show_screen(callback, texts.guide.empty_section, guide_root(texts))
        return
    await show_screen(callback, texts.guide.how_to_use_title, guide_how_to_use(texts, content))


@router.callback_query(GuideCB.filter(F.action == "group"))
async def show_group(
    callback: CallbackQuery, callback_data: GuideCB, content_store: ContentStore
) -> None:
    """Второй уровень: подвиды внутри группы, например виды свечей."""
    await callback.answer()
    content = content_store.current
    texts = content.texts
    groups = content.groups()

    if not 0 <= callback_data.value < len(groups):
        await show_screen(callback, texts.guide.how_to_use_title, guide_how_to_use(texts, content))
        return

    label = groups[callback_data.value][1]
    await show_screen(callback, label, guide_group(texts, content, callback_data.value))


@router.callback_query(GuideCB.filter(F.action == "category"))
async def show_category(
    callback: CallbackQuery, callback_data: GuideCB, content_store: ContentStore
) -> None:
    await callback.answer()
    content = content_store.current
    texts = content.texts
    categories = content.categories()

    if not 0 <= callback_data.value < len(categories):
        await show_screen(callback, texts.guide.how_to_use_title, guide_how_to_use(texts, content))
        return

    label = categories[callback_data.value][1]
    await show_screen(callback, label, guide_category(texts, content, callback_data.value))


@router.callback_query(GuideCB.filter(F.action == "product"))
async def show_product(
    callback: CallbackQuery,
    callback_data: GuideCB,
    content_store: ContentStore,
    repo: Repository,
    config: Config,
) -> None:
    await callback.answer()
    content = content_store.current
    texts = content.texts
    categories = content.categories()

    if not 0 <= callback_data.extra < len(categories):
        await show_screen(callback, texts.guide.how_to_use_title, guide_how_to_use(texts, content))
        return

    products = content.products_in_category(categories[callback_data.extra][0])
    if not 0 <= callback_data.value < len(products):
        await show_screen(callback, texts.guide.how_to_use_title, guide_how_to_use(texts, content))
        return

    product = products[callback_data.value]
    await repo.log_event(user_id_of(callback), "product_opened", {"product_id": product.id})

    body = _render_product(texts, product)
    markup = guide_back(texts, GuideCB(action="category", value=callback_data.extra), product)

    if product.photo:
        await show_photo_screen(callback, config.content_dir / product.photo, body, markup)
        return
    await show_screen(callback, body, markup)


@router.callback_query(GuideCB.filter(F.action == "practices"))
async def show_practices(callback: CallbackQuery, content_store: ContentStore) -> None:
    await callback.answer()
    content = content_store.current
    texts = content.texts
    if not content.active_practices:
        await show_screen(callback, texts.guide.empty_section, guide_root(texts))
        return
    await show_screen(callback, texts.guide.practices_title, guide_practices(texts, content))


@router.callback_query(GuideCB.filter(F.action == "practice"))
async def show_practice(
    callback: CallbackQuery,
    callback_data: GuideCB,
    content_store: ContentStore,
    repo: Repository,
) -> None:
    await callback.answer()
    content = content_store.current
    texts = content.texts
    practices = content.active_practices

    if not 0 <= callback_data.value < len(practices):
        await show_screen(callback, texts.guide.practices_title, guide_practices(texts, content))
        return

    practice = practices[callback_data.value]
    await repo.log_event(user_id_of(callback), "practice_opened", {"practice_id": practice.id})
    await show_screen(
        callback,
        f"{practice.title}\n\n{practice.text.strip()}",
        guide_back(texts, GuideCB(action="practices")),
    )


@router.callback_query(GuideCB.filter(F.action == "disposal"))
async def show_disposal(
    callback: CallbackQuery, content_store: ContentStore, repo: Repository
) -> None:
    await callback.answer()
    content = content_store.current
    texts = content.texts
    await repo.log_event(user_id_of(callback), "disposal_opened")
    if not content.disposal_faq:
        await show_screen(callback, texts.guide.empty_section, guide_root(texts))
        return
    await show_screen(callback, texts.guide.disposal_title, guide_disposal(texts, content))


@router.callback_query(GuideCB.filter(F.action == "faq"))
async def show_faq(
    callback: CallbackQuery, callback_data: GuideCB, content_store: ContentStore
) -> None:
    """Карточка FAQ. Индексы сквозные: «Как пользоваться», затем «Утилизация»."""
    await callback.answer()
    content = content_store.current
    texts = content.texts
    how_to_use = content.how_to_use_faq
    items = how_to_use + content.disposal_faq

    if not 0 <= callback_data.value < len(items):
        await show_screen(callback, texts.guide.title, guide_root(texts))
        return

    item = items[callback_data.value]
    back = GuideCB(action="howto" if callback_data.value < len(how_to_use) else "disposal")
    await show_screen(
        callback,
        f"{item.question}\n\n{item.answer.strip()}",
        guide_back(texts, back),
    )


def _render_product(texts: Texts, product: Product) -> str:
    """Карточка продукта: описание, шаги применения, хранение, утилизация."""
    blocks = [
        render(texts.guide.product_card, name=product.name, short_desc=product.short_desc).strip()
    ]

    if product.description:
        blocks.append(product.description.strip())
    if product.how_to_use:
        steps = "\n".join(f"{index}. {step}" for index, step in enumerate(product.how_to_use, 1))
        blocks.append(f"{texts.guide.product_how_to_use}\n{steps}")
    if product.care:
        blocks.append(f"{texts.guide.product_care}\n{product.care}")
    if product.disposal:
        blocks.append(f"{texts.guide.product_disposal}\n{product.disposal}")

    return "\n\n".join(blocks)
