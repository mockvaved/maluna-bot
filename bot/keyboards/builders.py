"""Сборка inline-клавиатур. Все подписи берутся из texts.yaml."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.content.schemas import RitualQuestion, Texts
from bot.content.store import ContentSnapshot
from bot.keyboards.callbacks import AstroCB, DeleteCB, GuideCB, MenuCB, RitualCB

CHECKED_MARK = "✅ "


def _to_menu_button(texts: Texts, label: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=label or texts.common.to_menu,
        callback_data=MenuCB(section="main").pack(),
    )


def main_menu(texts: Texts) -> InlineKeyboardMarkup:
    buttons = texts.menu.buttons
    builder = InlineKeyboardBuilder()
    for section, label in (
        ("prediction", buttons.prediction),
        ("ritual", buttons.ritual),
        ("astro", buttons.astro),
        ("guide", buttons.guide),
        ("about", buttons.about),
    ):
        builder.button(text=label, callback_data=MenuCB(section=section))
    builder.adjust(1)
    return builder.as_markup()


def only_menu(texts: Texts, label: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_to_menu_button(texts, label)]])


def about_menu(texts: Texts) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if texts.about_site_url:
        rows.append([InlineKeyboardButton(text=texts.about_site_button, url=texts.about_site_url)])
    rows.append([_to_menu_button(texts)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Собери свой ритуал ──────────────────────────────────────────────
def ritual_question(
    texts: Texts, question: RitualQuestion, step: int, selected: frozenset[str] = frozenset()
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, option in enumerate(question.options):
        if question.multi:
            label = f"{CHECKED_MARK}{option}" if option in selected else option
            builder.button(text=label, callback_data=RitualCB(action="toggle", value=index))
        else:
            builder.button(text=option, callback_data=RitualCB(action="pick", value=index))
    builder.adjust(1)

    if question.multi:
        builder.row(
            InlineKeyboardButton(
                text=texts.ritual.multi_done, callback_data=RitualCB(action="done").pack()
            )
        )

    navigation = []
    if step > 0:
        navigation.append(
            InlineKeyboardButton(
                text=texts.common.back, callback_data=RitualCB(action="back").pack()
            )
        )
    navigation.append(
        InlineKeyboardButton(
            text=texts.common.cancel, callback_data=RitualCB(action="cancel").pack()
        )
    )
    builder.row(*navigation)
    return builder.as_markup()


def ritual_result(
    texts: Texts, content: ContentSnapshot, product_ids: list[str], has_alternative: bool
) -> InlineKeyboardMarkup:
    """Продукты ритуала ведут в карточку справочника, ниже — навигация."""
    builder = InlineKeyboardBuilder()
    categories = [code for code, _ in content.categories()]
    for product_id in product_ids:
        product = content.product(product_id)
        if product is None:
            continue
        products = content.products_in_category(product.category)
        builder.row(
            InlineKeyboardButton(
                text=product.name,
                callback_data=GuideCB(
                    action="product",
                    value=[p.id for p in products].index(product.id),
                    extra=categories.index(product.category),
                ).pack(),
            )
        )

    navigation: list[InlineKeyboardButton] = []
    if has_alternative:
        navigation.append(
            InlineKeyboardButton(
                text=texts.ritual.another, callback_data=RitualCB(action="another").pack()
            )
        )
    navigation.append(_to_menu_button(texts))
    builder.row(*navigation)
    return builder.as_markup()


# ── Астропрогноз ────────────────────────────────────────────────────
def subscribe_gate(texts: Texts, channel_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=texts.astro.subscribe_button, url=channel_url)],
            [
                InlineKeyboardButton(
                    text=texts.astro.check_button, callback_data=AstroCB(action="check").pack()
                )
            ],
            [_to_menu_button(texts)],
        ]
    )


def astro_cancel(texts: Texts) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_to_menu_button(texts, texts.common.cancel)]]
    )


def astro_result(
    texts: Texts, content: ContentSnapshot, product_ids: list[str]
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    categories = [code for code, _ in content.categories()]
    for product_id in product_ids:
        product = content.product(product_id)
        if product is None:
            continue
        products = content.products_in_category(product.category)
        builder.row(
            InlineKeyboardButton(
                text=product.name,
                callback_data=GuideCB(
                    action="product",
                    value=[p.id for p in products].index(product.id),
                    extra=categories.index(product.category),
                ).pack(),
            )
        )
    builder.row(
        InlineKeyboardButton(
            text=texts.astro.another_date, callback_data=AstroCB(action="again").pack()
        ),
        _to_menu_button(texts),
    )
    return builder.as_markup()


# ── Справочник ──────────────────────────────────────────────────────
def guide_root(texts: Texts) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.guide.how_to_use, callback_data=GuideCB(action="howto"))
    builder.button(text=texts.guide.practices, callback_data=GuideCB(action="practices"))
    builder.button(text=texts.guide.disposal, callback_data=GuideCB(action="disposal"))
    builder.adjust(1)
    builder.row(_to_menu_button(texts))
    return builder.as_markup()


def guide_how_to_use(texts: Texts, content: ContentSnapshot) -> InlineKeyboardMarkup:
    """Общие карточки сверху, ниже — категории продуктов из products.yaml."""
    builder = InlineKeyboardBuilder()
    for index, item in enumerate(content.how_to_use_faq):
        builder.button(text=item.question, callback_data=GuideCB(action="faq", value=index))
    for index, (_, label) in enumerate(content.categories()):
        builder.button(text=label, callback_data=GuideCB(action="category", value=index))
    builder.adjust(1)
    builder.row(_back_to_guide(texts), _to_menu_button(texts))
    return builder.as_markup()


def guide_category(texts: Texts, content: ContentSnapshot, category_index: int) -> InlineKeyboardMarkup:
    categories = content.categories()
    builder = InlineKeyboardBuilder()
    if 0 <= category_index < len(categories):
        products = content.products_in_category(categories[category_index][0])
        for index, product in enumerate(products):
            builder.button(
                text=product.name,
                callback_data=GuideCB(action="product", value=index, extra=category_index),
            )
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(
            text=texts.common.back, callback_data=GuideCB(action="howto").pack()
        ),
        _to_menu_button(texts),
    )
    return builder.as_markup()


def guide_practices(texts: Texts, content: ContentSnapshot) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, practice in enumerate(content.active_practices):
        builder.button(text=practice.title, callback_data=GuideCB(action="practice", value=index))
    builder.adjust(1)
    builder.row(_back_to_guide(texts), _to_menu_button(texts))
    return builder.as_markup()


def guide_disposal(texts: Texts, content: ContentSnapshot) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    offset = len(content.how_to_use_faq)
    for index, item in enumerate(content.disposal_faq):
        # Индексы FAQ сквозные: сначала «Как пользоваться», потом «Утилизация».
        builder.button(text=item.question, callback_data=GuideCB(action="faq", value=offset + index))
    builder.adjust(1)
    builder.row(_back_to_guide(texts), _to_menu_button(texts))
    return builder.as_markup()


def guide_back(texts: Texts, back: GuideCB) -> InlineKeyboardMarkup:
    """Клавиатура карточки: назад в список и в меню."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=texts.common.back, callback_data=back.pack()),
                _to_menu_button(texts),
            ]
        ]
    )


def _back_to_guide(texts: Texts) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=texts.common.back, callback_data=GuideCB(action="root").pack()
    )


# ── /delete ─────────────────────────────────────────────────────────
def delete_confirm(texts: Texts) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.delete.confirm_button,
                    callback_data=DeleteCB(action="confirm").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=texts.delete.cancel_button,
                    callback_data=DeleteCB(action="cancel").pack(),
                )
            ],
        ]
    )
