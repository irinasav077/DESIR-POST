import os
import re
import asyncio
import logging
import time

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


# =========================================================
# STORAGE
# =========================================================

# Активні альбоми
# (chat_id, media_group_id) -> messages
albums = {}

# Таймери альбомів
album_tasks = {}

# Окремі тексти, які можуть прийти разом з альбомом
# chat_id -> [(message, timestamp)]
pending_texts = {}


# =========================================================
# PRICE
# =========================================================

def parse_price(value):

    value = value.strip()

    # 3.500 -> 3500
    # 3,500 -> 3500
    # 12.500 -> 12500
    # 12,500 -> 12500

    if re.fullmatch(
        r"\d{1,3}(?:[.,]\d{3})+",
        value,
    ):
        value = re.sub(
            r"[.,]",
            "",
            value,
        )

        return float(value)

    # 650.50 -> 650.5
    # 650,50 -> 650.5

    return float(
        value.replace(",", ".")
    )


def find_price(text):

    patterns = [

        # 650€
        # 650 €
        # 3.500€
        # 3,500€
        r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s*€",

        # 650-25%
        # 650 -25%
        # 3.500-25%
        # 3,500 -25%
        r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)"
        r"\s*€?\s*[-–—]\s*\d+\s*%",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
        )

        if match:

            return parse_price(
                match.group(1)
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

    brand = re.sub(
        r"[^a-zа-яіїєґ0-9\s&'-]",
        "",
        brand,
    )

    brand = brand.replace(
        "&",
        "",
    )

    brand = brand.replace(
        "'",
        "",
    )

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

    # Спочатку hashtag
    for line in lines:

        if line.startswith("#"):

            return clean_brand(
                line.split()[0]
            )

    # Потім назва бренду
    for line in lines:

        # Не ціна
        if re.search(
            r"\d+\s*€",
            line,
        ):
            continue

        # Не знижка
        if re.search(
            r"\d+\s*%",
            line,
        ):
            continue

        # Не просто цифри
        if re.fullmatch(
            r"[\d\s./,-]+",
            line,
        ):
            continue

        # Не розмір
        if is_size_line(line):
            continue

        # Не службовий текст
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

    # 36 38 39 40
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
    # БУКВЕНІ РОЗМІРИ
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
    # ЧИСЛОВІ РОЗМІРИ
    # -----------------------------------------------------

    for line in lines:

        if re.search(
            r"\d+\s*%",
            line,
        ):
            continue

        if "€" in line:
            continue

        numbers = re.findall(
            r"\d+(?:[.,]\d+)?",
            line,
        )

        if not numbers:
            continue

        # "2" не є розміром
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

            result.append(
                number.replace(
                    ",",
                    ".",
                )
            )

        return "/".join(result)

    return ""


# =========================================================
# CREATE CAPTION
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

    # Зменшуємо знижку на 10 п.п.
    new_discount = max(
        discount - 10,
        0,
    )

    new_price = round(
        price * (
            1 - new_discount / 100
        )
    )

    price_text = f"{price:g}"

    return (
        f"<i>#{brand}</i>\n"
        f"<i>{sizes}</i>\n\n"
        f"<i>🏷️{price_text}€-%={new_price}€</i>\n"
        f"<i>+ доставка 📦</i>\n\n"
        f"<i>Для консультації та замовлення:</i>\n"
        f"<i>💌@irasavchenkoo</i>"
    )


# =========================================================
# CHECK ACTIVE ALBUM
# =========================================================

def has_active_album(chat_id):

    for key in albums:

        if key[0] == chat_id:
            return True

    return False


# =========================================================
# GET TEXT FOR ALBUM
# =========================================================

def get_pending_text(chat_id):

    items = pending_texts.get(
        chat_id,
        [],
    )

    if not items:
        return ""

    now = time.time()

    fresh = [
        item
        for item in items
        if now - item[1] <= 12
    ]

    pending_texts[chat_id] = fresh

    if not fresh:
        return ""

    return fresh[-1][0].text or ""


# =========================================================
# SEND ALBUM
# =========================================================

async def process_album(
    chat_id,
    group_id,
):

    key = (
        chat_id,
        group_id,
    )

    # Чекаємо, поки Telegram передасть
    # весь альбом + можливий окремий текст
    await asyncio.sleep(5)

    messages = albums.pop(
        key,
        [],
    )

    album_tasks.pop(
        key,
        None,
    )

    if not messages:
        return

    messages.sort(
        key=lambda m: m.message_id
    )

    # -----------------------------------------------------
    # CAPTION ІЗ САМОГО АЛЬБОМУ
    # -----------------------------------------------------

    source_text = ""

    for message in messages:

        if message.caption:

            source_text = message.caption
            break

    # -----------------------------------------------------
    # ЯКЩО CAPTION НЕМАЄ —
    # БЕРЕМО ОКРЕМИЙ ТЕКСТ
    # -----------------------------------------------------

    if not source_text:

        source_text = get_pending_text(
            chat_id
        )

    if not source_text:

        await messages[0].reply_text(
            "⚠️ Не знайшов текст для обробки."
        )

        return

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

    # Telegram дозволяє максимум 10
    # елементів у media group
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
# SEND SINGLE MEDIA POST
# =========================================================

async def process_single_media(
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

    # PHOTO
    if message.photo:

        await message.reply_photo(
            photo=message.photo[-1].file_id,
            caption=caption,
            parse_mode="HTML",
        )

        return

    # VIDEO
    if message.video:

        await message.reply_video(
            video=message.video.file_id,
            caption=caption,
            parse_mode="HTML",
        )

        return


# =========================================================
# HANDLE MESSAGE
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.message

    if not message:
        return

    chat_id = message.chat_id

    # =====================================================
    # 1. АЛЬБОМ
    # =====================================================

    if message.media_group_id:

        group_id = message.media_group_id

        key = (
            chat_id,
            group_id,
        )

        if key not in albums:

            albums[key] = []

        albums[key].append(
            message
        )

        # Таймер створюємо тільки один раз
        if key not in album_tasks:

            album_tasks[key] = asyncio.create_task(
                process_album(
                    chat_id,
                    group_id,
                )
            )

        return

    # =====================================================
    # 2. ОДИНОЧНИЙ ПОСТ З МЕДІА
    # =====================================================

    if message.photo or message.video:

        await process_single_media(
            message
        )

        return

    # =====================================================
    # 3. ОКРЕМИЙ ТЕКСТ
    # =====================================================

    if message.text:

        # Якщо зараз збирається альбом,
        # цей текст може бути його caption,
        # тому тимчасово зберігаємо.
        if has_active_album(chat_id):

            if chat_id not in pending_texts:

                pending_texts[chat_id] = []

            pending_texts[chat_id].append(
                (
                    message,
                    time.time(),
                )
            )

            return

        # Якщо альбому немає —
        # це звичайний окремий пост
        caption = create_caption(
            message.text
        )

        await message.reply_text(
            caption,
            parse_mode="HTML",
        )

        return


# =========================================================
# MAIN
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
