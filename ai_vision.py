"""
AI Vision для DESIR POST BOT.

Читає бренд, ціну, знижку, розміри та модель з фото через Claude API.
AI лише ЗЧИТУЄ дані. Уся математика (формула ціни) залишається в bot.py.

Змінні середовища:
  ANTHROPIC_API_KEY  - ключ API (без нього AI вимкнений, бот працює як раніше)
  AI_MODEL           - модель (за замовчуванням claude-sonnet-5-5)
  AI_VISION          - "0", щоб вимкнути AI
  AI_MAX_PHOTOS      - скільки фото з альбому відправляти в AI (за замовч. 6)
  AI_TIMEOUT         - таймаут запиту, секунд (за замовч. 45)
"""

import os
import re
import base64
import logging
from collections import OrderedDict

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AI_MODEL = os.environ.get("AI_MODEL", "claude-sonnet-5-5")
AI_MAX_PHOTOS = max(1, int(os.environ.get("AI_MAX_PHOTOS", "6")))
AI_TIMEOUT = float(os.environ.get("AI_TIMEOUT", "45"))
AI_ENABLED = (
    bool(ANTHROPIC_API_KEY)
    and os.environ.get("AI_VISION", "1") != "0"
)

CACHE_LIMIT = 200
MAX_IMAGE_BYTES = 5 * 1024 * 1024

_cache = OrderedDict()
_client = None

# Остання помилка AI (коротко) - бот показує її в повідомленні
LAST_ERROR = ""


# =========================================================
# PROMPT + SCHEMA
# =========================================================

SYSTEM_PROMPT = """You read photos of luxury goods (shoes, bags, clothing, accessories) for a reseller.
Report ONLY what is physically visible in the photos. Never guess, never rely on memory, never fill gaps.
When unsure, return null / "not found" instead of a value.

BRAND: only from a logo, inscription, label, tag, box or packaging that is actually visible. Never identify a brand from the style or shape of the item alone.
Certain -> brand_confidence "high". Plausible but not certain -> fill brand and use "low". Nothing -> brand null and "none".

PRICE: read it from a price tag, sticker, label or a screenshot. Ignore barcodes, SKU/article numbers, dates, size numbers and percentages.
A crossed-out / "was" price is price_original. The price to pay now is price_current.
If the photo shows just one price, put it in price_current and set price_kind: "full" if it looks like a regular price, "discounted" if it is marked as reduced (sale sticker, percent badge, or next to a crossed-out price), otherwise "unknown".
If several numbers could be the item's price and you cannot tell which one is current: price_status "ambiguous", price_current null, and list the candidates in price_candidates (for example "450 EUR (large tag)").
If the digits are blurry, cut off or unreadable: price_status "unclear". Never guess digits. If there is no price at all: "not_found".
Use "clear" only when you are sure of every digit.
Numbers: plain numbers, dot as decimal separator, no thousands separators ("1.250,00 EUR" -> 1250). Do not convert currencies.

DISCOUNT: discount_percent only if a percentage is printed (for example "-30%"). Do not calculate it.
CURRENCY: ISO code from the symbol/text (EUR, USD, GBP, PLN, UAH...), null if not visible.
SIZES: only values printed on a size label or tag, for example ["38"], ["M"], ["36","37"]. If the tag shows several size systems, return the EU values. Never estimate a size from how the item looks.
MODEL: product/model name only if it is legible, otherwise null.
WARNINGS: short notes in Ukrainian about anything that lowers reliability (blurry tag, several prices, partly hidden text). Empty list if none.

Several images may show the same item from different angles: combine what you see across all of them.
Always answer by calling report_product."""


PRODUCT_TOOL = {
    "name": "report_product",
    "description": "Report the data that is visible on the product photos.",
    "input_schema": {
        "type": "object",
        "properties": {
            "brand": {"type": ["string", "null"]},
            "brand_confidence": {
                "type": "string",
                "enum": ["high", "low", "none"],
            },
            "model_name": {"type": ["string", "null"]},
            "price_status": {
                "type": "string",
                "enum": ["clear", "unclear", "ambiguous", "not_found"],
            },
            "price_current": {"type": ["number", "null"]},
            "price_original": {"type": ["number", "null"]},
            "price_kind": {
                "type": "string",
                "enum": ["full", "discounted", "unknown"],
            },
            "price_candidates": {
                "type": "array",
                "items": {"type": "string"},
            },
            "discount_percent": {"type": ["integer", "null"]},
            "currency": {"type": ["string", "null"]},
            "sizes": {
                "type": "array",
                "items": {"type": "string"},
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "brand",
            "brand_confidence",
            "price_status",
            "price_current",
            "price_original",
            "price_kind",
            "discount_percent",
            "currency",
            "sizes",
            "warnings",
        ],
    },
}


# =========================================================
# TELEGRAM -> IMAGES
# =========================================================

def _media_type(data):

    if data.startswith(b"\x89PNG"):
        return "image/png"

    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"

    if data[:3] == b"GIF":
        return "image/gif"

    return "image/jpeg"


async def download_photo(message):

    tg_file = await message.photo[-1].get_file()

    return bytes(
        await tg_file.download_as_bytearray()
    )


def select_photos(messages):
    """
    Лише фото (відео пропускаємо). Якщо їх більше за AI_MAX_PHOTOS -
    беремо початок і кінець альбому: саме там зазвичай бирка/цінник.
    """

    photos = [
        m for m in messages
        if getattr(m, "photo", None)
    ]

    if len(photos) <= AI_MAX_PHOTOS:
        return photos

    head = (AI_MAX_PHOTOS + 1) // 2
    tail = AI_MAX_PHOTOS - head

    result = photos[:head]

    if tail:
        result += photos[-tail:]

    return result


# =========================================================
# CLAUDE API
# =========================================================

def _get_client():

    global _client

    if _client is None:

        from anthropic import AsyncAnthropic

        _client = AsyncAnthropic(
            api_key=ANTHROPIC_API_KEY,
            timeout=AI_TIMEOUT,
            max_retries=2,
        )

    return _client


async def _ask_claude(images):

    content = []

    for number, data in enumerate(images, 1):

        content.append(
            {
                "type": "text",
                "text": f"Фото {number}:",
            }
        )

        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": _media_type(data),
                    "data": base64.b64encode(data).decode("ascii"),
                },
            }
        )

    content.append(
        {
            "type": "text",
            "text": "Зчитай дані з цих фото та виклич report_product.",
        }
    )

    # Sonnet 5.5 не підтримує примусовий tool_choice (тільки "auto"),
    # тому просимо викликати інструмент у промпті та перевіряємо відповідь.
    request = dict(
        model=AI_MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        tools=[PRODUCT_TOOL],
        tool_choice={"type": "auto"},
        messages=[
            {
                "role": "user",
                "content": content,
            }
        ],
    )

    # Для читання цінника міркування наперед не потрібне:
    # найнижчий рівень - швидше та дешевше (лише для Sonnet 5.5)
    if "sonnet-5-5" in AI_MODEL:
        request["thinking"] = {"type": "between_tools"}

    for _attempt in range(2):

        response = await _get_client().messages.create(
            **request
        )

        for block in response.content:

            if (
                getattr(block, "type", None) == "tool_use"
                and block.name == "report_product"
            ):
                return dict(block.input)

    return None


async def analyze_photos(messages):
    """
    Повертає dict з даними, які AI прочитав, або None, якщо AI вимкнений
    чи не зміг прочитати фото. Ті самі фото повторно не аналізуються.
    """

    global LAST_ERROR

    LAST_ERROR = ""

    if not AI_ENABLED:
        return None

    photos = select_photos(messages)

    if not photos:
        return None

    key = tuple(
        m.photo[-1].file_unique_id
        for m in photos
    )

    if key in _cache:

        _cache.move_to_end(key)

        return _cache[key]

    try:

        images = []

        for message in photos:

            data = await download_photo(message)

            if len(data) > MAX_IMAGE_BYTES:

                logger.warning(
                    "Photo is too large for AI, skipped"
                )
                continue

            images.append(data)

        if not images:

            LAST_ERROR = "фото завелике для AI"

            return None

        result = await _ask_claude(images)

    except Exception as error:

        LAST_ERROR = (
            f"{type(error).__name__}: {str(error)[:150]}"
        )

        logger.error(
            f"AI vision error: {LAST_ERROR}"
        )

        return None

    if result is None:

        LAST_ERROR = "AI повернув порожню відповідь"

        return None

    _cache[key] = result

    while len(_cache) > CACHE_LIMIT:
        _cache.popitem(last=False)

    return result


async def self_check():
    """Для команди /aicheck: перевіряє ключ, бібліотеку, баланс і модель."""

    if os.environ.get("AI_VISION", "1") == "0":
        return "❌ AI вимкнено змінною AI_VISION=0."

    if not ANTHROPIC_API_KEY:
        return "❌ Змінну ANTHROPIC_API_KEY на хостингу не знайдено."

    try:
        client = _get_client()
    except Exception as error:
        return f"❌ Бібліотека anthropic не встановлена: {type(error).__name__}"

    try:

        await client.messages.create(
            model=AI_MODEL,
            max_tokens=16,
            messages=[
                {
                    "role": "user",
                    "content": "Відповідай одним словом: ок",
                }
            ],
        )

    except Exception as error:

        return f"❌ {type(error).__name__}: {str(error)[:300]}"

    return f"✅ AI працює. Модель: {AI_MODEL}"


# =========================================================
# VALIDATION (Python, не AI)
# =========================================================

def _to_number(value):

    if value is None or isinstance(value, bool):
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if number <= 0 or number > 1_000_000:
        return None

    return number


def _to_percent(value):

    number = _to_number(value)

    if number is None:
        return None

    number = int(round(number))

    if 1 <= number <= 90:
        return number

    return None


def clean_sizes(raw):

    if not isinstance(raw, (list, tuple)):
        return ""

    result = []

    for item in raw:

        value = str(item).strip().upper().replace(",", ".")

        is_letter = re.fullmatch(
            r"XXXS|XXS|XS|S|M|L|XL|XXL|XXXL",
            value,
        )

        is_number = re.fullmatch(
            r"\d{1,3}(?:\.\d)?",
            value,
        )

        if (is_letter or is_number) and value not in result:
            result.append(value)

    return "/".join(result)


def resolve_ai_fields(text_fields, ai):
    """
    text_fields: що знайдено в ТЕКСТІ (price, discount, brand, sizes).
    ai: що прочитав AI.

    Повертає (extra, notes):
      extra - лише те, чого немає в тексті (текст завжди в пріоритеті);
      notes - рядки для повідомлення користувачці.

    "price" в extra - ціна ДО знижки (як у твоєму форматі "600€ -30%").
    """

    extra = {}
    notes = []
    used = []

    if not ai:
        return extra, notes

    text_price = text_fields.get("price")
    text_discount = text_fields.get("discount")

    # -----------------------------------------------------
    # Бренд
    # -----------------------------------------------------

    if not text_fields.get("brand"):

        brand = str(ai.get("brand") or "").strip()

        if brand and ai.get("brand_confidence") == "high":

            extra["brand"] = brand
            used.append(f"бренд {brand}")

        elif brand:

            notes.append(
                f"⚠️ Бренд на фото не впевнений (можливо {brand}) — не використано."
            )

        else:

            notes.append(
                "⚠️ Бренд на фото не визначено."
            )

    # -----------------------------------------------------
    # Розміри
    # -----------------------------------------------------

    if not text_fields.get("sizes"):

        sizes = clean_sizes(ai.get("sizes"))

        if sizes:

            extra["sizes"] = sizes
            used.append(f"розміри {sizes}")

    # -----------------------------------------------------
    # Ціна
    # -----------------------------------------------------

    status = ai.get("price_status")
    current = _to_number(ai.get("price_current"))
    original = _to_number(ai.get("price_original"))
    printed = _to_percent(ai.get("discount_percent"))

    currency = str(ai.get("currency") or "").strip().upper()

    if currency == "€":
        currency = "EUR"

    candidates = [
        str(c) for c in (ai.get("price_candidates") or [])
    ][:5]

    price_ok = status == "clear" and current is not None

    if price_ok and currency not in ("", "EUR"):

        if text_price is None:

            notes.append(
                f"⚠️ Ціна на фото в {currency} ({current:g}), не в EUR — не використано."
            )

        price_ok = False

    elif not price_ok and text_price is None:

        if status == "ambiguous":

            tail = (
                ": " + "; ".join(candidates)
                if candidates
                else ""
            )

            notes.append(
                "⚠️ На фото кілька цін — не вибираю навмання" + tail + "."
            )

        elif status == "unclear":

            notes.append(
                "⚠️ Текст на ціннику нечіткий — ціну не зчитано."
            )

        else:

            notes.append(
                "⚠️ Ціну на фото не знайдено."
            )

    if price_ok:

        tag_discount = printed
        computed = False

        if (
            tag_discount is None
            and original is not None
            and original > current
        ):

            tag_discount = _to_percent(
                (1 - current / original) * 100
            )

            computed = tag_discount is not None

        # ---------------------------------------------
        # Ціни в тексті немає - беремо з фото
        # ---------------------------------------------

        if text_price is None:

            discount = (
                text_discount
                if text_discount is not None
                else tag_discount
            )

            if original is not None:

                base = original

            elif (
                ai.get("price_kind") == "discounted"
                and discount
            ):

                base = round(
                    current / (1 - discount / 100)
                )

                notes.append(
                    "ℹ️ Ціну до знижки розраховано з ціни на ціннику та знижки."
                )

            else:

                base = current

                if ai.get("price_kind") == "discounted":

                    notes.append(
                        "⚠️ Схоже, це ціна вже зі знижкою, а знижки на фото немає — перевірте."
                    )

            extra["price"] = float(base)

            piece = f"ціна {base:g}€"

            if text_discount is None and discount is not None:

                extra["discount"] = discount

                piece += f" (-{discount}%)"

                if computed:

                    notes.append(
                        "ℹ️ Знижку розраховано з двох цін на ціннику."
                    )

            used.append(piece)

        # ---------------------------------------------
        # Ціна в тексті є - знижку з фото беремо
        # лише якщо вона точно до цієї ціни
        # ---------------------------------------------

        elif (
            text_discount is None
            and tag_discount is not None
        ):

            if (
                original is not None
                and abs(original - text_price) <= 1
            ):

                extra["discount"] = tag_discount

                used.append(f"знижка -{tag_discount}%")

                if computed:

                    notes.append(
                        "ℹ️ Знижку розраховано з двох цін на ціннику."
                    )

            else:

                notes.append(
                    f"⚠️ На фото знижка -{tag_discount}%, але ціна з тексту не збігається "
                    f"з ціною до знижки — знижку не застосовано."
                )

    # -----------------------------------------------------
    # Модель (лише інформація, у пост не йде)
    # -----------------------------------------------------

    model = str(ai.get("model_name") or "").strip()

    if model:
        used.append(f"модель {model}")

    for warning in (ai.get("warnings") or [])[:3]:

        notes.append(f"⚠️ {warning}")

    if used:

        notes.insert(
            0,
            "🤖 З фото: " + " · ".join(used),
        )

    return extra, notes
