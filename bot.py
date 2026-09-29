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

# =========================================================
# STORAGE
# =========================================================

albums = {}

# Очікувані пари:
# фото/відео -> наступне текстове повідомлення
pending_media = {}

WAIT_SECONDS = 10


# =========================================================
# PRICE
# =========================================================

def find_price(text):

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

    # -----------------------------------------------------
    # HASHTAG
    # -----------------------------------------------------

    for line in lines:

        if line.startswith("#"):

            return clean_brand(
                line.split()[0]
            )

    # -----------------------------------------------------
    # BRAND NAME
    # -----------------------------------------------------

    for line in lines:

        if re.search(
            r"\d+\s*€",
            line,
        ):
            continue

        if re.search(
            r"\d+\s*%",
            line,
        ):
            continue

        if re.fullmatch(
            r"[\d\s./,-]+",
            line,
        ):
            continue

        if is_size_line(line):
            continue

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
    # LETTER SIZES
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
    # NUMERIC SIZES
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

        # Самотнє число 2 не є розміром

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
            r"[\s/;:,.+-]+",
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

    # Зменшуємо знижку на 10 пунктів

    new_discount = max(
        discount - 10,
        0,
    )

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
# SEND SINGLE PHOTO
# =========================================================

async def send_single_photo(
    message,
    text,
):

    caption = create_caption(text)

    await message.reply_photo(
        photo=message.photo[-1].file_id,
        caption=caption,
        parse_mode="HTML",
    )


# =========================================================
# SEND SINGLE VIDEO
# =========================================================

async def send_single_video(
    message,
    text,
):

    caption = create_caption(text)

    await message.reply_video(
        video=message.video.file_id,
        caption=caption,
        parse_mode="HTML",
    )


# =========================================================
# SEND ALBUM
# =========================================================

async def send_album(
    messages,
    text,
):

    caption = create_caption(text)

    media = []

    for index, message in enumerate(messages):

        if message.photo:

            file_id = message.photo[-1].file_id

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

        elif message.video:

            file_id = message.video.file_id

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
# WAITING TIMER
# =========================================================

async def media_timeout(
    key,
):

    await asyncio.sleep(
        WAIT_SECONDS
    )

    # Якщо текст вже прийшов,
    # цього запису тут не буде

    if key in pending_media:

        pending_media.pop(
            key,
            None,
        )


# =========================================================
# PROCESS ALBUM
# =========================================================

async def process_album(
    group_id,
):

    await asyncio.sleep(2)

    messages = albums.pop(
        group_id,
        [],
    )

    if not messages:
        return

    messages.sort(
        key=lambda m: m.message_id
    )

    # Перевіряємо, чи був caption

    source_text = ""

    for message in messages:

        if message.caption:

            source_text = message.caption
            break

    # Caption вже є

    if source_text:

        await send_album(
            messages,
            source_text,
        )

        return

    # Caption немає.
    # Зберігаємо альбом і чекаємо текст.

    first_message = messages[0]

    key = (
        first_message.chat_id,
        first_message.from_user.id,
    )

    pending_media[key] = {
        "type": "album",
        "messages": messages,
    }

    asyncio.create_task(
        media_timeout(key)
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

    # Унікальний ключ:
    # чат + конкретний користувач

    user_id = (
        message.from_user.id
        if message.from_user
        else 0
    )

    key = (
        message.chat_id,
        user_id,
    )

    # =====================================================
    # TEXT MESSAGE
    # =====================================================

    if message.text:

        # -------------------------------------------------
        # СПОЧАТКУ ПЕРЕВІРЯЄМО,
        # ЧИ Є ОЧІКУЮЧЕ ФОТО/ВІДЕО
        # -------------------------------------------------

        pending = pending_media.pop(
            key,
            None,
        )

        if pending:

            text = message.text

            # PHOTO + TEXT
            if pending["type"] == "photo":

                await send_single_photo(
                    pending["message"],
                    text,
                )

                return

            # VIDEO + TEXT
            if pending["type"] == "video":

                await send_single_video(
                    pending["message"],
                    text,
                )

                return

            # ALBUM + TEXT
            if pending["type"] == "album":

                await send_album(
                    pending["messages"],
                    text,
                )

                return

        # -------------------------------------------------
        # Якщо фото/відео перед ним не було
        # -------------------------------------------------

        caption = create_caption(
            message.text
        )

        await message.reply_text(
            caption,
            parse_mode="HTML",
        )

        return

    # =====================================================
    # ALBUM
    # =====================================================

    if message.media_group_id:

        group_id = message.media_group_id

        if group_id not in albums:

            albums[group_id] = []

        albums[group_id].append(
            message
        )

        # Таймер тільки для першого
        # повідомлення альбому

        if len(albums[group_id]) == 1:

            asyncio.create_task(
                process_album(
                    group_id
                )
            )

        return

    # =====================================================
    # SINGLE PHOTO
    # =====================================================

    if message.photo:

        # Фото вже має caption

        if message.caption:

            await send_single_photo(
                message,
                message.caption,
            )

            return

        # Фото без caption.
        # Тепер чекаємо текст.

        pending_media[key] = {
            "type": "photo",
            "message": message,
        }

        asyncio.create_task(
            media_timeout(key)
        )

        return

    # =====================================================
    # SINGLE VIDEO
    # =====================================================

    if message.video:

        # Відео вже має caption

        if message.caption:

            await send_single_video(
                message,
                message.caption,
            )

            return

        # Відео без caption.
        # Чекаємо текст.

        pending_media[key] = {
            "type": "video",
            "message": message,
        }

        asyncio.create_task(
            media_timeout(key)
        )

        return


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
