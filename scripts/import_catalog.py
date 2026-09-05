#!/usr/bin/env python3
"""Импорт каталога товаров из KATALOG_MALUNA.md в content/products.yaml.

Как пользоваться:
  1. Обнови выгрузку каталога: content/KATALOG_MALUNA.md и папку content/images/
  2. Запусти:  python scripts/import_catalog.py
  3. Отправь боту команду /reload

Скрипт перезаписывает content/products.yaml целиком, так что правки руками
в этом файле потеряются — меняй выгрузку и запускай импорт заново.

Что скрипт НЕ переносит, и это намеренно (ТЗ, раздел 3 — бот не продаёт):
  • цены, старые цены и скидки;
  • ссылки на карточки товара в магазине.
Ссылка на бренд в боте допустима ровно одна — в разделе «О бренде».

Картинки конвертируются из .webp в .jpg и складываются в content/media/:
Telegram надёжно принимает JPEG, а webp в sendPhoto иногда отбивает.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from bot.config import PROJECT_ROOT  # noqa: E402
from bot.content.schemas import Product  # noqa: E402

# Переиспользуем аккуратный вывод YAML из импорта ритуалов: блочные скаляры,
# отступы у списков, кириллица без экранирования.
from import_rituals import _Dumper  # noqa: E402

CONTENT_DIR = PROJECT_ROOT / "content"
DEFAULT_SOURCE = CONTENT_DIR / "KATALOG_MALUNA.md"
DEFAULT_TARGET = CONTENT_DIR / "products.yaml"
IMAGES_DIR = CONTENT_DIR / "images"
MEDIA_DIR = CONTENT_DIR / "media"

JPEG_QUALITY = 85
# Телеграм не любит огромные картинки, да и смысла в них нет.
MAX_SIDE = 1280

# Группа верхнего уровня в меню справочника: код → подпись.
GROUP_LABELS = {"candles": "Свечи"}

# Категория из каталога → (код группы, код категории, подпись категории).
CATEGORY_MAP = {
    "Косметика": ("", "cosmetics", "Косметика"),
    "Свечи → Астросвечи": ("candles", "astro_candles", "Астросвечи"),
    "Свечи → Моно набор": ("candles", "mono_set", "Моно наборы"),
    "Свечи → Микс набор": ("candles", "mix_set", "Микс наборы"),
    "Свечи → Свечи-скрутки": ("candles", "twists", "Свечи-скрутки"),
    "Свечи → Наборы": ("candles", "gift_sets", "Подарочные наборы"),
    "Карты": ("", "cards", "Карты"),
}

# Артикул из каталога → устойчивый id латиницей. Артикулы кириллические и
# местами непоследовательные (астро-скорпион через дефис), поэтому таблица
# явная: id попадают в контент-файлы и меняться не должны.
ID_MAP = {
    "гидрофильное_масло": "cosmetic_hydrophilic_oil",
    "очищающий_гель": "cosmetic_cleansing_gel",
    "увлажняющий_крем": "cosmetic_moisturizer",
    "астро_овен": "astro_aries",
    "астро_телец": "astro_taurus",
    "астро_близнецы": "astro_gemini",
    "астро_рак": "astro_cancer",
    "астро_лев": "astro_leo",
    "астро_дева": "astro_virgo",
    "астро_весы": "astro_libra",
    "астро-скорпион": "astro_scorpio",
    "астро_стрелец": "astro_sagittarius",
    "астро_козерог": "astro_capricorn",
    "астро_водолей": "astro_aquarius",
    "астро_рыбы": "astro_pisces",
    "моно_роза": "mono_rose",
    "моно_чабрец": "mono_thyme",
    "моно_календула": "mono_calendula",
    "моно_базилик": "mono_basil",
    "моно_береза": "mono_birch",
    "моно_мята": "mono_mint",
    "моно_одуванчик": "mono_dandelion",
    "моно_душица": "mono_oregano",
    "моно_лаванда": "mono_lavender",
    "моно_шалфей": "mono_sage",
    "моно_полынь": "mono_wormwood",
    "микс_22": "mix_22",
    "микс_36": "mix_36",
    "микс_37": "mix_37",
    "микс_38": "mix_38",
    "микс_39": "mix_39",
    "микс_50": "mix_50",
    "скрутки_зеленые": "twist_green",
    "скрутки_красные": "twist_red",
    "скрутки_черные": "twist_black",
    "набор_dream": "set_dream",
    "набор_love": "set_love",
    "набор_money": "set_money",
    "карты_знак": "cards_your_sign",
}

_TRANSLIT = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya", " ": "_",
        "-": "_",
    }
)

HEADER = """\
# ═══════════════════════════════════════════════════════════════════
#  ПРОДУКТЫ MALUNA — раздел «📖 Справочник → Как пользоваться»
#
#  Файл собран скриптом scripts/import_catalog.py из KATALOG_MALUNA.md.
#  Правки руками потеряются при следующем импорте — меняй выгрузку.
#
#  Цен и ссылок на магазин здесь нет и быть не должно: бот не продаёт.
#
#  group    — верхний уровень меню (пусто = товар сразу в корне)
#  category — второй уровень
#  Подписи для обоих задаются в texts.yaml → guide.groups / guide.categories
#
#  photos   — пути от папки content. В карточке показывается первая.
#  active   — false прячет товар от пользователей, не удаляя его
# ═══════════════════════════════════════════════════════════════════
"""


class CatalogError(RuntimeError):
    """Каталог не читается или в нём не хватает данных."""


def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).lower().translate(_TRANSLIT)
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _field(block: str, name: str) -> str:
    match = re.search(rf"^\|\s*{name}\s*\|(.+?)\|\s*$", block, re.M)
    return match.group(1).strip() if match else ""


def parse_catalog(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogError(f"не читается файл каталога: {exc}") from exc

    blocks = re.split(r"^### \d+\.\s*", text, flags=re.M)[1:]
    if not blocks:
        raise CatalogError("в файле не нашлось ни одного товара (ожидались заголовки «### 1. Название»)")

    products: list[dict[str, Any]] = []
    problems: list[str] = []

    for block in blocks:
        name = block.split("\n", 1)[0].strip()
        sku = _field(block, "Артикул")
        raw_category = _field(block, "Категория")
        short_desc = _field(block, "Кратко")

        product_id = ID_MAP.get(sku) or slugify(sku or name)
        if not product_id:
            problems.append(f"{name}: не удалось построить id")
            continue

        mapped = CATEGORY_MAP.get(raw_category)
        if mapped is None:
            problems.append(f"{name}: неизвестная категория {raw_category!r}")
            continue
        group, category, _ = mapped

        if not short_desc:
            problems.append(f"{name}: пустое поле «Кратко»")
            continue

        description = ""
        if "**Описание**" in block:
            description = block.split("**Описание**", 1)[1]
            # Описание заканчивается горизонтальной чертой. За ней либо
            # следующий товар, либо заголовок новой секции каталога —
            # ни то, ни другое в описание попасть не должно.
            description = re.split(r"^---\s*$", description, maxsplit=1, flags=re.M)[0].strip()

        products.append(
            {
                "id": product_id,
                "name": name,
                "group": group,
                "category": category,
                "short_desc": short_desc,
                "description": description,
                "images": re.findall(r"img_\d{3}\.webp", block),
            }
        )

    if problems:
        raise CatalogError("\n  ".join(["в каталоге есть проблемы:", *problems]))
    return products


def convert_images(products: list[dict[str, Any]]) -> list[str]:
    """webp → jpg в content/media/. Возвращает список проблем."""
    from PIL import Image

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []

    for product in products:
        photos: list[str] = []
        for index, source_name in enumerate(dict.fromkeys(product.pop("images")), start=1):
            source = IMAGES_DIR / source_name
            if not source.is_file():
                problems.append(f"{product['id']}: нет файла {source_name}")
                continue

            target = MEDIA_DIR / f"{product['id']}_{index}.jpg"
            try:
                with Image.open(source) as image:
                    image = image.convert("RGB")
                    image.thumbnail((MAX_SIDE, MAX_SIDE))
                    image.save(target, "JPEG", quality=JPEG_QUALITY, optimize=True)
            except Exception as exc:  # noqa: BLE001 — сообщение показываем владельцу
                problems.append(f"{product['id']}: не сконвертировалась {source_name} ({exc})")
                continue
            photos.append(f"media/{target.name}")
        product["photos"] = photos

    return problems


def to_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Валидирует теми же схемами, что и бот, и приводит к виду файла."""
    result: list[dict[str, Any]] = []
    problems: list[str] = []
    seen: set[str] = set()

    for entry in products:
        entry.setdefault("how_to_use", [])
        entry.setdefault("active", True)
        try:
            product = Product.model_validate(entry)
        except Exception as exc:  # noqa: BLE001 — текст ошибки нужен владельцу целиком
            problems.append(f"{entry.get('name', '?')}: {exc}")
            continue
        if product.id in seen:
            problems.append(f"id {product.id!r} встречается дважды")
            continue
        seen.add(product.id)
        # Свойство photo вычисляемое, в файл его писать не нужно.
        result.append(product.model_dump())

    if problems:
        raise CatalogError("\n  ".join(["товары не прошли проверку:", *problems]))
    return result


def write_yaml(products: list[dict[str, Any]], target: Path) -> None:
    for product in products:
        if product["description"] and not product["description"].endswith("\n"):
            product["description"] += "\n"

    body = yaml.dump(
        products,
        Dumper=_Dumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        indent=2,
        width=100,
    )
    target.write_text(f"{HEADER}\n{body}", encoding="utf-8")


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TARGET

    if not source.is_file():
        print(f"❌ Не нашёл файл каталога: {source}")
        return 1

    try:
        parsed = parse_catalog(source)
        image_problems = convert_images(parsed)
        products = to_products(parsed)
    except CatalogError as exc:
        print(f"❌ {exc}")
        return 1
    except ImportError:
        print("❌ Для конвертации картинок нужна библиотека Pillow:")
        print("   pip install -r requirements.txt")
        return 1

    write_yaml(products, target)

    photos = sum(len(product["photos"]) for product in products)
    print(f"✅ Перенёс {len(products)} товаров в {target}")
    print(f"   Картинок сконвертировано: {photos} → {MEDIA_DIR}")
    if image_problems:
        print("⚠️  С картинками не всё гладко:")
        for problem in image_problems:
            print(f"   {problem}")
    print("   Теперь отправь боту команду /reload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
