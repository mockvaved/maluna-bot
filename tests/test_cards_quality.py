"""Качество предсказаний: гендерная нейтральность и запретные темы.

Требования владельца: предсказание обращается к человеку без указания
рода и не задевает здоровье, политику, деньги, отношения и прочие темы,
которые можно прочитать как диагноз, обещание или упрёк.

Проверки грубые — по стоп-спискам. Они не заменяют вычитку, но ловят
самое частое и не дают качеству поехать, когда карточек несколько сотен.
"""

from __future__ import annotations

import re

import pytest

from bot.content.store import ContentSnapshot

# ── Родовые формы ───────────────────────────────────────────────────
# Проверка идёт по целым словам, а не по подстрокам: «Вселенная
# приготовила» — нормально, род собеседника тут ни при чём, а вот
# «ты задумала» — уже нет.

# Слова, которые могут относиться только к самому человеку. Появилось
# такое в тексте — род собеседника уже назван.
ALWAYS_GENDERED = (
    r"устал[аои]?", r"должен", r"должна", r"одинок[аи]?", r"влюблён",
    r"влюблена", r"обязан", r"обязана", r"виноват[аы]?",
)
_ALWAYS_GENDERED_RE = re.compile(
    r"\b(?:" + "|".join(ALWAYS_GENDERED) + r")\b", re.IGNORECASE
)

# А эти слова сами по себе безобидны: они часто описывают предмет, а не
# человека — «повод найдётся сам», «день уже готов», «самой верной
# мыслью». Род собеседника они выдают, только когда стоят рядом с
# обращением: «ты сам», «тебе самой», «будь готова», «останешься одна».
CONTEXT_GENDERED = (
    r"сам", r"сама", r"самому", r"самой", r"готов[аы]?", r"рад[аы]?",
    r"прав", r"права", r"уверен[аы]?", r"спокоен", r"спокойна", r"доволен",
    r"довольна", r"занят[аы]?", r"свободен", r"свободна", r"один", r"одна",
)
_CONTEXT = "|".join(CONTEXT_GENDERED)
_ADDRESS = r"ты|тебе|тебя|твой|твоя|тво[её]|твои"

_CONTEXT_GENDERED_RE = re.compile(
    # «ты сам», «тебе самой решать»
    rf"\b(?:{_ADDRESS})\b(?:\s+\w+){{0,1}}\s+(?:{_CONTEXT})\b"
    # «сам ты», «готова ты»
    rf"|\b(?:{_CONTEXT})\b\s+(?:{_ADDRESS})\b"
    # «будь готова», «останешься одна», «окажешься прав»
    rf"|\b(?:будь|станешь|останешься|окажешься|будешь)\s+(?:{_CONTEXT})\b",
    re.IGNORECASE,
)

# Глагол прошедшего времени рядом с «ты» — «ты вчера решила», «ты понял».
_SECOND_PERSON_PAST_RE = re.compile(
    r"\bты\b(?:\s+\w+){0,2}\s+\w+л[аи]?\b|\b\w+л[аи]?\b\s+ты\b", re.IGNORECASE
)

# Темы, которых в предсказании быть не должно. Шаблоны с границей слова:
# «болезнь» ловится, а «больше» — нет.
FORBIDDEN_TOPICS = {
    "здоровье": (r"здоровь", r"здоров\b", r"болезн", r"болит\b", r"боль\b",
                 r"лечен", r"лечит", r"врач", r"диагноз", r"таблет", r"лекарств",
                 r"симптом", r"иммунит", r"психик", r"депресс", r"терапи",
                 r"клиник", r"больниц"),
    "политика": (r"политик", r"власт", r"президент", r"правительств", r"войн",
                 r"митинг", r"парти[ия]\b", r"депутат", r"государств", r"санкц"),
    # «долги» и «долгов» — про деньги, а «долгий» и «долго» — про время.
    "деньги": (r"деньг", r"зарплат", r"доход", r"прибыл", r"богатств", r"кредит",
               r"долг\b", r"долги\b", r"долгов\b", r"долгам", r"инвест", r"рубл",
               r"финанс", r"бюджет", r"преми[яи]\b", r"заработ", r"копейк"),
    "отношения": (r"замуж", r"свадьб", r"развод", r"измен[аы]\b", r"изменил",
                  r"расстан", r"жених", r"невест", r"беремен", r"партн[её]р",
                  r"роман\b", r"секс", r"свидани"),
    "внешность и вес": (r"похуд", r"вес\b", r"диет", r"калор", r"фигур",
                        r"морщин", r"стройн", r"толст"),
    "утраты": (r"смерт", r"умер", r"похорон", r"горе\b", r"траур", r"утрат"),
    "работа": (r"увольн", r"уволи", r"начальник", r"карьер", r"должност",
               r"собеседов"),
}
_TOPIC_RE = {
    topic: re.compile(r"\b(?:" + "|".join(words) + r")", re.IGNORECASE)
    for topic, words in FORBIDDEN_TOPICS.items()
}


def cards_text(content: ContentSnapshot) -> list[tuple[str, str]]:
    return [(card.id, f"{card.title} {card.text}") for card in content.cards]


def test_cards_are_gender_neutral(content: ContentSnapshot) -> None:
    """Предсказание не должно выдавать род того, кто его читает."""
    offenders: list[str] = []
    for card_id, text in cards_text(content):
        if found := _ALWAYS_GENDERED_RE.search(text):
            offenders.append(f"{card_id}: слово «{found.group()}» → {text}")
        elif found := _CONTEXT_GENDERED_RE.search(text):
            offenders.append(f"{card_id}: «{found.group()}» — род рядом с обращением → {text}")
        elif found := _SECOND_PERSON_PAST_RE.search(text):
            offenders.append(f"{card_id}: «{found.group()}» — прошедшее время на «ты» → {text}")
    assert not offenders, "Родовые формы в предсказаниях:\n" + "\n".join(offenders)


@pytest.mark.parametrize("topic", sorted(FORBIDDEN_TOPICS))
def test_cards_avoid_forbidden_topics(content: ContentSnapshot, topic: str) -> None:
    pattern = _TOPIC_RE[topic]
    offenders = [
        f"{card_id}: «{found.group()}» → {text}"
        for card_id, text in cards_text(content)
        if (found := pattern.search(text))
    ]
    assert not offenders, f"Тема «{topic}» в предсказаниях:\n" + "\n".join(offenders)


def test_cards_are_unique(content: ContentSnapshot) -> None:
    """Ни одинаковых текстов, ни одинаковых заголовков."""
    texts: dict[str, str] = {}
    titles: dict[str, str] = {}
    duplicates: list[str] = []

    for card in content.cards:
        key = re.sub(r"[^\w]+", " ", card.text.lower()).strip()
        if key in texts:
            duplicates.append(f"текст {card.id} повторяет {texts[key]}")
        texts[key] = card.id

        title = card.title.lower().strip()
        if title in titles:
            duplicates.append(f"заголовок {card.id} повторяет {titles[title]}")
        titles[title] = card.id

    assert not duplicates, "Повторы в предсказаниях:\n" + "\n".join(duplicates)


def test_cards_stay_within_brand_voice(content: ContentSnapshot) -> None:
    """Короткие фразы, обращение на «ты», не больше двух разрешённых эмодзи."""
    allowed_emoji = {"🕯", "✨", "💜"}
    problems: list[str] = []

    for card in content.cards:
        if len(card.title) > 40:
            problems.append(f"{card.id}: заголовок длиннее 40 символов")
        if len(card.text) > 220:
            problems.append(f"{card.id}: текст длиннее 220 символов")
        if "вы " in card.text.lower() or "вас " in card.text.lower():
            problems.append(f"{card.id}: обращение на «вы»")

        emoji = [ch for ch in card.text if ord(ch) > 0x2000 and ch not in "—–…«»‑"]
        if len(emoji) > 2:
            problems.append(f"{card.id}: больше двух эмодзи")
        if set(emoji) - allowed_emoji:
            extra = "".join(sorted(set(emoji) - allowed_emoji))
            problems.append(f"{card.id}: эмодзи вне списка 🕯 ✨ 💜 — {extra}")

    assert not problems, "Тон предсказаний:\n" + "\n".join(problems)


def test_enough_cards_for_a_year(content: ContentSnapshot) -> None:
    """Карточек хватает на год без повторов."""
    assert len(content.active_cards) >= 365


def test_products_have_no_prices(content: ContentSnapshot) -> None:
    """В карточках товаров не должно быть цен, скидок и ссылок в магазин."""
    money = re.compile(r"₽|\bруб|\bскидк|\bпромокод|tproduct|malunabeauty", re.IGNORECASE)
    offenders = [
        product.id
        for product in content.products
        if money.search(f"{product.name} {product.short_desc} {product.description}")
    ]
    assert not offenders, f"Цены или ссылки в магазин: {offenders}"
