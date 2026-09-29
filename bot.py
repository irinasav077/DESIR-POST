import os
import re
import asyncio
import logging

from telegram import Update
from telegram import InputMediaPhoto, InputMediaVideo

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

# Тимчасово зберігаємо альбоми
albums = {}


# =========================================================
# PRICE
# =========================================================

def find_price(text):

    # Наприклад:
    # 650€
    # 650 €
    # 650-25%
    # 650 -25%
    # 650€. -20%

    patterns = [
        r"(\d+(?:[.,]\d+)?)\s*€",
        r"(\d+(?:[.,]\d+)?)\s*€?\s*[-–—]\s*\d+\s*%",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
        )

        if match:

            return float(
                match.group(1).replace(",", ".")
            )

    return None


# =========================================================
# DISCOUNT
# =========================================================

def find_discount(text):

    match = re.search(
        r"-?\s*(\d{1,2})\s*%",
        text,
    )

    if match:

        return int(
            match.group(1)
        )

    return None


# =========================================================
# BRAND
# =========================================================

def clean_brand(brand):

    brand = brand.replace(
        "#",
        "",
    )

    brand = brand.lower()

    # Прибираємо emoji
    brand = re.sub(
        r"[^a-zа-яіїєґ0-9\s&'-]",
        "",
        brand,
    )

    # Прибираємо &
    brand = brand.replace(
        "&",
        "",
    )

    # Прибираємо апострофи
    brand = brand.replace(
        "'",
        "",
    )

    # Прибираємо пробіли та дефіси
    brand = re.sub(
        r"[\s-]+",
        "",
        brand,
    )

    return brand


def find_brand(text):

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    # Спочатку шукаємо hashtag
    for line in lines:

        if line.startswith("#"):

            return clean_brand(
                line.split()[0]
            )

    # Потім шукаємо назву бренду
    for line in lines:

        # Не бренд, якщо це ціна
        if re.search(
            r"\d+\s*€",
            line,
        ):
            continue

        # Не бренд, якщо це знижка
        if re.search(
            r"\d+\s*%",
            line,
        ):
            continue

        # Не бренд, якщо тільки цифри
        if re.fullmatch(
            r"[\d\s./,-]+",
            line,
        ):
            continue

        # Не бренд, якщо це розміри
        if is_size_line(line):
            continue

        # Не бренд, якщо це FW / NEW / SALE
        if re.search(
            r"\b(FW|SS|NEW|SALE|DROP|COLLECTION)\d*",
            line,
            re.IGNORECASE,
        ):
            continue

        return clean_brand(line)

    return None


# =========================================================
# SIZES
# =========================================================

LETTER_SIZE_PATTERN = (
    r"\b(?:XXXS|XXS|XS|S|M|L|XL|XXL|XXXL)\b"
)


def is_size_line(line):

    line = line.strip()

    # S M L XL
    letter_sizes = re.findall(
        LETTER_SIZE_PATTERN,
        line,
        re.IGNORECASE,
    )

    if letter_sizes:

        # Перевіряємо, що в рядку немає
        # зайвого тексту
        cleaned = re.sub(
            LETTER_SIZE_PATTERN,
            "",
            line,
            flags=re.IGNORECASE,
        )

        cleaned = re.sub(
            r"[\s./,;:-]+",
            "",
            cleaned,
        )

        if cleaned == "":
            return True

    # Числові розміри
    numbers = re.findall(
        r"\d+(?:[.,]\d+)?",
        line,
    )

    if numbers:

        cleaned = re.sub(
            r"\d+(?:[.,]\d+)?",
            "",
            line,
        )

        cleaned = re.sub(
            r"[\s/;:,.+-]+",
            "",
            cleaned,
        )

        if cleaned == "":
            return True

    return False


def normalize_sizes(text):

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    # -----------------------------------------------------
    # 1. БУКВЕНІ РОЗМІРИ
    # -----------------------------------------------------

    for line in lines:

        sizes = re.findall(
            LETTER_SIZE_PATTERN,
            line,
            re.IGNORECASE,
        )

        if sizes:

            cleaned = re.sub(
                LETTER_SIZE_PATTERN,
                "",
                line,
                flags=re.IGNORECASE,
            )

            cleaned = re.sub(
                r"[\s./,;:-]+",
                "",
                cleaned,
            )

            if cleaned == "":

                return "/".join(
                    size.upper()
                    for size in sizes
                )

    # -----------------------------------------------------
    # 2. ЧИСЛОВІ РОЗМІРИ
    # -----------------------------------------------------

    for line in lines:

        # Не чіпаємо рядок зі знижкою
        if re.search(
            r"\d+\s*%",
            line,
        ):
            continue

        # Не чіпаємо рядок з €
        if "€" in line:
            continue

        numbers = re.findall(
            r"\d+(?:[.,]\d+)?",
            line,
        )

        if not numbers:
            continue

        # Якщо це просто "2" —
        # це не розмір
        if len(numbers) == 1:

            try:
                number = float(
                    numbers[0].replace(
                        ",",
                        ".",
                    )
                )

                if number < 30:
                    continue

            except ValueError:
                continue

        # Перевіряємо, що крім чисел
        # немає стороннього тексту
        cleaned = re.sub(
            r"\d+(?:[.,]\d+)?",
            "",
            line,
        )

        cleaned = re.sub(
            r"[\s/;:,.+\-]+",
            "",
            cleaned,
        )

        if cleaned != "":
            continue

        result = []

        for number in numbers:

            number = number.replace(
                ",",
                ".",
            )

            result.append(number)

        return "/".join(result)

    return ""


# =========================================================
# CAPTION
# =========================================================

def create_caption(text):

    price = find_price(text)
    discount = find_discount(text)
    brand = find_brand(text)
    sizes = normalize_sizes(text)

    if price is None:

        return (
            "<i>⚠️ Не вдалося знайти ціну.</i>"
        )

    if discount is None:

        return (
            "<i>⚠️ Не вдалося знайти знижку.</i>"
        )

    if not brand:

        brand = "brand"

    # Зменшуємо знижку
    # на 10 процентних пунктів
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

    return (
        f"<i>#{brand}</i>\n"
        f"<i>{sizes}</i>\n\n"
        f"<i>🏷️{price:g}€-%={new_price}€</i>\n"
        f"<i>+ доставка 📦</i>\n\n"
        f"<i>Для консультації та замовлення:</i>\n"
        f"<i>💌@irasavchenkoo</i>"
    )


# =========================================================
# SINGLE PHOTO
# =========================================================

async def handle_photo(
    message,
):

    text = message.caption or ""

    if not text:

        await message.reply_text(
            "⚠️ Не знайшов текст для обробки."
        )

        return

    caption = create_caption(
        text
    )

    # Беремо найбільший варіант фото
    photo_file_id = (
        message.photo[-1].file_id
    )

    await message.reply_photo(
        photo=photo_file_id,
        caption=caption,
        parse_mode="HTML",
    )


# =========================================================
# SINGLE VIDEO
# =========================================================

async def handle_video(
    message,
):

    text = message.caption or ""

    if not text:

        await message.reply_text(
            "⚠️ Не знайшов текст для обробки."
        )

        return

    caption = create_caption(
        text
    )

    await message.reply_video(
        video=message.video.file_id,
        caption=caption,
        parse_mode="HTML",
    )


# =========================================================
# ALBUM
# =========================================================

async def process_album(
    group_id,
):

    # Чекаємо, поки Telegram передасть
    # усі елементи альбому
    await asyncio.sleep(2)

    messages = albums.pop(
        group_id,
        [],
    )

    if not messages:
        return

    # Правильний порядок
    messages.sort(
        key=lambda m: m.message_id
    )

    # Шукаємо caption
    source_text = ""

    for message in messages:

        if message.caption:

            source_text = message.caption

            break

    caption = create_caption(
        source_text
    )

    media = []

    for index, message in enumerate(
        messages
    ):

        # PHOTO
        if message.photo:

            file_id = (
                message.photo[-1].file_id
            )

            if index == 0:

                media.append(
                    InputMediaPhoto(
                        media=file_id,
                        caption=caption,
                        parse_mode="HTML",
                    )
                )

            else:

                media.append(
                    InputMediaPhoto(
                        media=file_id,
                    )
                )

        # VIDEO
        elif message.video:

            file_id = (
                message.video.file_id
            )

            if index == 0:

                media.append(
                    InputMediaVideo(
                        media=file_id,
                        caption=caption,
                        parse_mode="HTML",
                    )
                )

            else:

                media.append(
                    InputMediaVideo(
                        media=file_id,
                    )
                )

    if not media:
        return

    # Telegram: максимум 10 елементів
    # в одному media group
    for start in range(
        0,
        len(media),
        10,
    ):

        chunk = media[
            start:start + 10
        ]

        await messages[0].reply_media_group(
            media=chunk
        )


# =========================================================
# MAIN HANDLER
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.message

    if not message:
        return

    # -----------------------------------------------------
    # АЛЬБОМ
    # -----------------------------------------------------

    if message.media_group_id:

        group_id = message.media_group_id

        if group_id not in albums:

            albums[group_id] = []

        albums[group_id].append(
            message
        )

        # Запускаємо таймер тільки
        # для першого повідомлення
        if len(albums[group_id]) == 1:

            asyncio.create_task(
                process_album(
                    group_id
                )
            )

        return

    # -----------------------------------------------------
    # ОДНЕ ФОТО
    # -----------------------------------------------------

    if message.photo:

        await handle_photo(
            message
        )

        return

    # -----------------------------------------------------
    # ОДНЕ ВІДЕО
    # -----------------------------------------------------

    if message.video:

        await handle_video(
            message
        )

        return

    # -----------------------------------------------------
    # ТЕКСТ
    # -----------------------------------------------------

    if message.text:

        caption = create_caption(
            message.text
        )

        await message.reply_text(
            caption,
            parse_mode="HTML",
        )


# =========================================================
# START
# =========================================================

def main():

    if not BOT_TOKEN:

        raise ValueError(
            "BOT_TOKEN is not set"
        )

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
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

    application.run_polling()


if __name__ == "__main__":

    main()
