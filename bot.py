import os
import re
import logging

from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")


# -------------------------------------------------
# PRICE
# -------------------------------------------------

def find_price(text):
    """
    Розуміє формати:
    650€
    650 €
    650-25%
    650 -25%
    650€. -20%
    """

    patterns = [
        r"(\d+(?:[.,]\d+)?)\s*€",
        r"(\d+(?:[.,]\d+)?)\s*€?\s*[\-–—]\s*\d+\s*%",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            return float(match.group(1).replace(",", "."))

    return None


# -------------------------------------------------
# DISCOUNT
# -------------------------------------------------

def find_discount(text):
    """
    Розуміє:
    35%
    -35%
    35%⚡️
    - 35%
    """

    match = re.search(
        r"-?\s*(\d{1,2})\s*%",
        text
    )

    if match:
        return int(match.group(1))

    return None


# -------------------------------------------------
# BRAND
# -------------------------------------------------

def find_brand(text):

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    # Якщо бренд написаний як hashtag
    for line in lines:

        if line.startswith("#"):

            brand = line.split()[0]

            return clean_brand(brand)

    # Якщо hashtag немає — шукаємо назву бренду
    for line in lines:

        # пропускаємо рядки з ціною
        if re.search(r"\d+\s*€", line):
            continue

        # пропускаємо рядки зі знижкою
        if re.search(r"\d+\s*%", line):
            continue

        # пропускаємо рядки тільки з числами
        if re.fullmatch(r"[\d\s./,-]+", line):
            continue

        # пропускаємо рядки з розмірами
        if is_size_line(line):
            continue

        # пропускаємо технічні назви колекцій
        if re.search(
            r"\b(FW|SS|NEW|SALE|DROP|COLLECTION)\d*",
            line,
            re.IGNORECASE,
        ):
            continue

        return clean_brand(line)

    return None


def clean_brand(brand):

    brand = brand.replace("#", "")
    brand = brand.lower()

    # залишаємо букви, цифри та пробіли
    brand = re.sub(
        r"[^a-zа-яіїєґ0-9\s&'-]",
        "",
        brand,
    )

    # прибираємо & та апострофи
    brand = re.sub(
        r"[&']",
        "",
        brand,
    )

    # всі слова об'єднуємо
    brand = re.sub(
        r"[\s-]+",
        "",
        brand,
    )

    return brand


# -------------------------------------------------
# SIZES
# -------------------------------------------------

SIZE_WORDS = {
    "XXXS",
    "XXS",
    "XS",
    "S",
    "M",
    "L",
    "XL",
    "XXL",
    "XXXL",
}


def is_size_line(line):

    cleaned = line.upper().strip()

    # S. M. L. XL.
    words = re.findall(
        r"[A-ZА-ЯІЇЄҐ]+",
        cleaned,
    )

    if words and all(
        word in SIZE_WORDS
        for word in words
    ):
        return True

    # 36 37 38
    # 36/37/38
    numbers = re.findall(
        r"\b\d{2}\b",
        cleaned,
    )

    if numbers:

        other = re.sub(
            r"[\d\s/.,;:-]",
            "",
            cleaned,
        )

        if not other:
            return True

    return False


def normalize_sizes(text):

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    # Спочатку буквені розміри
    for line in lines:

        if re.search(
            r"\b(?:XXXS|XXS|XS|S|M|L|XL|XXL|XXXL)\b",
            line,
            re.IGNORECASE,
        ):

            sizes = re.findall(
                r"\b(?:XXXS|XXS|XS|S|M|L|XL|XXL|XXXL)\b",
                line,
                re.IGNORECASE,
            )

            if sizes:

                return "/".join(
                    size.upper()
                    for size in sizes
                )

    # Потім числові розміри
    for line in lines:

        numbers = re.findall(
            r"\b\d{2}\b",
            line,
        )

        if numbers:

            # Не беремо ціну
            if re.search(
                r"\d+\s*€",
                line,
            ):
                continue

            # Не беремо знижку
            if re.search(
                r"\d+\s*%",
                line,
            ):
                continue

            cleaned = re.sub(
                r"[\d\s/.,;:-]",
                "",
                line,
            )

            if not cleaned:

                return "/".join(numbers)

    return ""


# -------------------------------------------------
# CREATE CAPTION
# -------------------------------------------------

def create_caption(text):

    price = find_price(text)
    discount = find_discount(text)
    brand = find_brand(text)
    sizes = normalize_sizes(text)

    if price is None:

        return (
            "⚠️ Не вдалося знайти ціну."
        )

    if discount is None:

        return (
            "⚠️ Не вдалося знайти знижку."
        )

    if not brand:

        brand = "brand"

    # Зменшуємо знижку на 10 процентних пунктів
    new_discount = max(
        discount - 10,
        0,
    )

    # Рахуємо кінцеву ціну
    new_price = round(
        price * (
            1 - new_discount / 100
        )
    )

    caption = (
        f"<i>#{brand}</i>\n"
        f"<i>{sizes}</i>\n\n"
        f"<i>🏷️{price:g}€-%={new_price}€</i>\n"
        f"<i>+ доставка 📦</i>\n\n"
        f"<i>Для консультації та замовлення:</i>\n"
        f"<i>💌@irasavchenkoo</i>"
    )

    return caption


# -------------------------------------------------
# TELEGRAM MESSAGE
# -------------------------------------------------

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.message

    if not message:
        return

    # Беремо текст повідомлення
    # або caption до фото/відео
    text = (
        message.caption
        or message.text
        or ""
    )

    if not text:

        await message.reply_text(
            "⚠️ Не знайшов текст для обробки."
        )

        return

    caption = create_caption(text)

    await message.reply_text(
        caption,
        parse_mode="HTML",
    )


# -------------------------------------------------
# START BOT
# -------------------------------------------------

def main():

    if not BOT_TOKEN:

        raise ValueError(
            "BOT_TOKEN is not set"
        )

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO
            | filters.VIDEO
            | filters.TEXT,
            handle_message,
        )
    )

    print(
        "DESIR POST BOT started"
    )

    app.run_polling()


if __name__ == "__main__":

    main()
