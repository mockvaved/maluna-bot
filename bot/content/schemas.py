"""Схемы контент-файлов.

Всё, что владелец редактирует руками, проверяется этими моделями. Если
файл не проходит валидацию — бот не стартует, а в лог уходит имя файла и
поле (ТЗ, раздел 14).
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ── Словари допустимых значений для базы ритуалов ───────────────────
TIME_OF_DAY_VALUES = ("утро", "день", "вечер")
DURATION_VALUES = (5, 15, 30)
MOOD_VALUES = ("устала", "тревожно", "хочется вдохновения", "радостно")
DESIRE_VALUES = ("отдохнуть", "взбодриться", "позаботиться о коже", "создать уют")
ITEM_VALUES = (
    "свечи MALUNA",
    "гидрофильное масло MALUNA",
    "очищающий гель MALUNA",
    "увлажняющий крем MALUNA",
    "душ",
    "ванна",
    "кофе",
    "чай",
)
ANY_VALUE = "любое"

CANDLE_ITEM = "свечи MALUNA"

# Разделы справочника, которые бот умеет показывать.
SECTION_HOW_TO_USE = "Как пользоваться"
SECTION_DISPOSAL = "Утилизация"

_DDMM_RE = re.compile(r"^\d{2}\.\d{2}$")

# Цены, скидки и промокоды в текстах запрещены (ТЗ, раздел 3).
_PRICE_RE = re.compile(r"₽|\bруб\b|\bруб\.|\bскидк|\bпромокод|\bпо цене\b", re.IGNORECASE)

NonEmptyStr = Annotated[str, Field(min_length=1)]


class ContentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ── cards ───────────────────────────────────────────────────────────
class Card(ContentModel):
    id: NonEmptyStr
    title: NonEmptyStr
    text: NonEmptyStr
    tags: list[str] = Field(default_factory=list)
    active: bool = True

    @field_validator("tags")
    @classmethod
    def _no_birthday_tag(cls, tags: list[str]) -> list[str]:
        # ТЗ, раздел 7: бот не знает дату рождения, тега birthday быть не должно.
        if any(tag.strip().lower() == "birthday" for tag in tags):
            raise ValueError("tag 'birthday' is not allowed: the bot never stores birth dates")
        return tags


# ── rituals ─────────────────────────────────────────────────────────
class Ritual(ContentModel):
    id: int
    time_of_day: list[str] = Field(min_length=1)
    duration_min: Literal[5, 15, 30]
    mood: list[str] = Field(min_length=1)
    desire: str
    items: list[str] = Field(default_factory=list)
    title: NonEmptyStr
    text: NonEmptyStr
    active: bool = True

    @field_validator("time_of_day")
    @classmethod
    def _check_time_of_day(cls, values: list[str]) -> list[str]:
        return _check_vocabulary(values, TIME_OF_DAY_VALUES, allow_any=True, field="time_of_day")

    @field_validator("mood")
    @classmethod
    def _check_mood(cls, values: list[str]) -> list[str]:
        return _check_vocabulary(values, MOOD_VALUES, allow_any=True, field="mood")

    @field_validator("items")
    @classmethod
    def _check_items(cls, values: list[str]) -> list[str]:
        return _check_vocabulary(values, ITEM_VALUES, allow_any=False, field="items")

    @field_validator("desire")
    @classmethod
    def _check_desire(cls, value: str) -> str:
        if value not in DESIRE_VALUES:
            raise ValueError(f"unknown desire {value!r}, expected one of: {', '.join(DESIRE_VALUES)}")
        return value


def _check_vocabulary(
    values: list[str], allowed: tuple[str, ...], *, allow_any: bool, field: str
) -> list[str]:
    vocabulary = set(allowed) | ({ANY_VALUE} if allow_any else set())
    for value in values:
        if value not in vocabulary:
            raise ValueError(
                f"unknown {field} value {value!r}, expected one of: {', '.join(sorted(vocabulary))}"
            )
    return values


# ── products ────────────────────────────────────────────────────────
class Product(ContentModel):
    id: NonEmptyStr
    name: NonEmptyStr
    # Верхний уровень меню справочника. Пусто — товар лежит сразу в корне.
    group: str = ""
    category: NonEmptyStr
    short_desc: NonEmptyStr
    # Полное описание из каталога бренда.
    description: str = ""
    how_to_use: list[str] = Field(default_factory=list)
    care: str = ""
    disposal: str = ""
    mood_tags: list[str] = Field(default_factory=list)
    # Пути к картинкам относительно папки content. Показывается первая.
    photos: list[str] = Field(default_factory=list)
    # Страница товара на сайте бренда. Под карточкой появляется кнопка,
    # ведущая сюда. Пусто — кнопки не будет.
    url: str = ""
    active: bool = True

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError(f"product url must start with http:// or https://, got {value!r}")
        return value

    @field_validator("description", "short_desc")
    @classmethod
    def _no_prices(cls, value: str) -> str:
        # ТЗ, раздел 3: ни цен, ни скидок, ни промокодов.
        if _PRICE_RE.search(value):
            raise ValueError("prices and discounts are not allowed in product texts")
        return value

    @property
    def photo(self) -> str:
        return self.photos[0] if self.photos else ""


# ── astro_2027 ──────────────────────────────────────────────────────
class AstroSign(ContentModel):
    sign: NonEmptyStr
    date_from: str
    date_to: str
    title: NonEmptyStr
    text: NonEmptyStr
    product_ids: list[str] = Field(default_factory=list)

    @field_validator("date_from", "date_to")
    @classmethod
    def _check_ddmm(cls, value: str) -> str:
        if not _DDMM_RE.match(value):
            raise ValueError(f"expected date in DD.MM format, got {value!r}")
        day, month = (int(part) for part in value.split("."))
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            raise ValueError(f"{value!r} is not a valid day and month")
        return value


# ── numerology_2027 ─────────────────────────────────────────────────
class NumerologyYear(ContentModel):
    """Разбор личного года по цифре от 1 до 9."""

    number: int = Field(ge=1, le=9)
    title: NonEmptyStr
    text: NonEmptyStr
    product_ids: list[str] = Field(default_factory=list)

    @property
    def id(self) -> int:
        # Загрузчик проверяет уникальность по полю id.
        return self.number


# ── faq ─────────────────────────────────────────────────────────────
class FaqItem(ContentModel):
    id: NonEmptyStr
    section: NonEmptyStr
    question: NonEmptyStr
    answer: NonEmptyStr
    order: int = 100
    active: bool = True


# ── practices ───────────────────────────────────────────────────────
class Practice(ContentModel):
    id: NonEmptyStr
    title: NonEmptyStr
    text: NonEmptyStr
    order: int = 100
    active: bool = True


# ── replies ─────────────────────────────────────────────────────────
class ReplyRule(ContentModel):
    id: NonEmptyStr
    keywords: list[NonEmptyStr] = Field(min_length=1)
    answer: NonEmptyStr


class Replies(ContentModel):
    rules: list[ReplyRule] = Field(default_factory=list)
    fallback: NonEmptyStr


# ── texts ───────────────────────────────────────────────────────────
class MenuButtons(ContentModel):
    prediction: NonEmptyStr
    ritual: NonEmptyStr
    astro: NonEmptyStr
    gift: NonEmptyStr
    guide: NonEmptyStr
    about: NonEmptyStr


class GiftTexts(ContentModel):
    """Подарок за отзыв."""

    ask_photo: NonEmptyStr
    photo_note: NonEmptyStr
    photo_saved: NonEmptyStr
    not_a_photo: NonEmptyStr
    save_failed: NonEmptyStr
    too_many_attempts: NonEmptyStr
    ask_date: NonEmptyStr
    forecast: NonEmptyStr


class MenuTexts(ContentModel):
    title: NonEmptyStr
    buttons: MenuButtons


class CommonTexts(ContentModel):
    to_menu: NonEmptyStr
    back_to_menu: NonEmptyStr
    back: NonEmptyStr
    cancel: NonEmptyStr
    error: NonEmptyStr


class PredictionTexts(ContentModel):
    card: NonEmptyStr
    already_today: NonEmptyStr


class RitualQuestion(ContentModel):
    key: NonEmptyStr
    text: NonEmptyStr
    # Значения из словаря ТЗ. Они же ключи подбора ритуала — менять нельзя.
    options: list[NonEmptyStr] = Field(min_length=2)
    # Подписи кнопок, если показывать нужно не сам ключ: {ключ: подпись}.
    # Так «устала» на экране становится нейтральным «нет сил».
    option_labels: dict[str, NonEmptyStr] = Field(default_factory=dict)
    multi: bool = False

    def label(self, option: str) -> str:
        return self.option_labels.get(option, option)

    @model_validator(mode="after")
    def _labels_match_options(self) -> RitualQuestion:
        unknown = sorted(set(self.option_labels) - set(self.options))
        if unknown:
            raise ValueError(f"option_labels refer to missing options: {', '.join(unknown)}")
        return self


class RitualTexts(ContentModel):
    intro: NonEmptyStr
    progress: NonEmptyStr
    multi_hint: NonEmptyStr
    multi_done: NonEmptyStr
    multi_empty: NonEmptyStr
    another: NonEmptyStr
    no_more: NonEmptyStr
    cancelled: NonEmptyStr
    result: NonEmptyStr
    products_header: NonEmptyStr
    # Куда ведёт кнопка предмета под ритуалом: {предмет: id товара или код группы}.
    # Предметов из пятого вопроса, которых тут нет, под ритуалом не будет.
    item_links: dict[str, NonEmptyStr] = Field(default_factory=dict)
    questions: list[RitualQuestion] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_questions(self) -> RitualTexts:
        expected = {
            "time_of_day": set(TIME_OF_DAY_VALUES),
            "mood": set(MOOD_VALUES),
            "desire": set(DESIRE_VALUES),
            "items": set(ITEM_VALUES),
        }
        keys = [question.key for question in self.questions]
        for key in ("time_of_day", "duration", "mood", "desire", "items"):
            if key not in keys:
                raise ValueError(f"question with key {key!r} is missing")
        for question in self.questions:
            allowed = expected.get(question.key)
            # Варианты ответов — ключи матчинга, они обязаны совпадать со словарями.
            if allowed is not None and not set(question.options) <= allowed:
                unknown = sorted(set(question.options) - allowed)
                raise ValueError(
                    f"question {question.key!r} has options outside the vocabulary: {', '.join(unknown)}"
                )
            if question.key == "duration":
                for option in question.options:
                    if not any(str(value) in option for value in DURATION_VALUES):
                        raise ValueError(
                            f"duration option {option!r} must mention one of {DURATION_VALUES}"
                        )
        return self


class AstroTexts(ContentModel):
    subscribe_required: NonEmptyStr
    subscribe_button: NonEmptyStr
    check_button: NonEmptyStr
    not_subscribed_yet: NonEmptyStr
    ask_date: NonEmptyStr
    privacy_note: NonEmptyStr
    invalid_date: NonEmptyStr
    too_many_attempts: NonEmptyStr
    forecast: NonEmptyStr
    product_header: NonEmptyStr
    another_date: NonEmptyStr


class GuideTexts(ContentModel):
    title: NonEmptyStr
    how_to_use: NonEmptyStr
    how_to_use_title: NonEmptyStr
    practices: NonEmptyStr
    practices_title: NonEmptyStr
    disposal: NonEmptyStr
    disposal_title: NonEmptyStr
    empty_section: NonEmptyStr
    product_card: NonEmptyStr
    product_how_to_use: NonEmptyStr
    product_care: NonEmptyStr
    product_disposal: NonEmptyStr
    # Подпись кнопки на страницу товара. Пустая строка убирает кнопку
    # со всех карточек разом.
    buy_button: str = ""
    # Подписи для меню. Слева код из products.yaml, справа то, что видит человек.
    # Нет подписи — показывается сам код.
    groups: dict[str, str] = Field(default_factory=dict)
    categories: dict[str, str] = Field(default_factory=dict)


class DeleteTexts(ContentModel):
    confirm: NonEmptyStr
    confirm_button: NonEmptyStr
    cancel_button: NonEmptyStr
    done: NonEmptyStr
    cancelled: NonEmptyStr


class AdminTexts(ContentModel):
    reload_ok: NonEmptyStr
    reload_failed: NonEmptyStr
    reviews_empty: NonEmptyStr
    reviews_caption: NonEmptyStr


class Texts(ContentModel):
    welcome: NonEmptyStr
    menu: MenuTexts
    common: CommonTexts
    prediction: PredictionTexts
    ritual: RitualTexts
    astro: AstroTexts
    gift: GiftTexts
    guide: GuideTexts
    about: NonEmptyStr
    about_site_button: NonEmptyStr
    about_site_url: str = ""
    about_contacts: str = ""
    delete: DeleteTexts
    admin: AdminTexts

    @field_validator("welcome")
    @classmethod
    def _no_placeholders(cls, value: str) -> str:
        # ТЗ, раздел 4: бот не знает имени, плейсхолдеров вида {name} быть не должно.
        if "{name}" in value:
            raise ValueError("{name} placeholder is not allowed: the bot never knows the user's name")
        return value


def duration_to_minutes(option: str) -> int:
    """Достаёт число минут из подписи кнопки («15 минут» → 15)."""
    match = re.search(r"\d+", option)
    if not match:
        raise ValueError(f"no number found in duration option {option!r}")
    return int(match.group())


__all__ = [
    "ANY_VALUE",
    "CANDLE_ITEM",
    "DESIRE_VALUES",
    "DURATION_VALUES",
    "ITEM_VALUES",
    "MOOD_VALUES",
    "SECTION_DISPOSAL",
    "SECTION_HOW_TO_USE",
    "TIME_OF_DAY_VALUES",
    "AstroSign",
    "Card",
    "FaqItem",
    "NumerologyYear",
    "Practice",
    "Product",
    "Replies",
    "ReplyRule",
    "Ritual",
    "Texts",
    "duration_to_minutes",
]
