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

# Фото/відео, які чекають наступного текстового повідомлення
pending_media = {}

# =========================================================
# PRICE
# =========================================================

def find_price(text):

    patterns = [
        # 3.600€ / 3,600€ / 12.500€
        r"(\d{1,3}(?:[.,]\d{3})+)\s*€",

        # 3600€ / 3600 € / 999.99€
        r"(\d+(?:[.,]\d+)?)\s*€",

        # 3.600 - 20% / 3600 - 20%
        r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s*[-–—]\s*\d+\s*%",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
        )

        if match:

            value = match.group(1)

            # 3.600 → 3600
            # 3,600 → 3600
            if re.fullmatch(
                r"\d{1,3}(?:[.,]\d{3})+",
                value,
            ):

                return float(
                    re.sub(
                        r"[.,]",
                        "",
                        value,
                    )
                )

            # 999,99 → 999.99
            return float(
                value.replace(
                    ",",
                    ".",
                )
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

    # Hashtag
    for line in lines:

        if line.startswith("#"):

            return clean_brand(
                line.split()[0]
            )

    # Назва бренду
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
    # Буквені розміри
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
    # Числові розміри
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

        # Самотнє "2" — не розмір
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
# SEND PHOTO
# =========================================================

async def send_photo(
    message,
    text,
):

    caption = create_caption(
        text
    )

    await message.reply_photo(
        photo=message.photo[-1].file_id,
        caption=caption,
        parse_mode="HTML",
    )


# =========================================================
# SEND VIDEO
# =========================================================

async def send_video(
    message,
    text,
):

    caption = create_caption(
        text
    )

    await message.reply_video(
        video=message.video.file_id,
        caption=caption,
        parse_mode="HTML",
    )


# =========================================================
# WAIT FOR TEXT AFTER MEDIA
# =========================================================

async def wait_for_text(
    message,
):

    await asyncio.sleep(5)

    user_id = message.from_user.id

    pending = pending_media.get(
        user_id
    )

    if not pending:
        return

    pending_media.pop(
        user_id,
        None,
    )

    await message.reply_text(
        "⚠️ Не знайшов текст із брендом, ціною та знижкою."
    )


# =========================================================
# BUILD ALBUM
# =========================================================

async def send_album(
    messages,
    text,
):

    caption = create_caption(
        text
    )

    messages.sort(
        key=lambda m: m.message_id
    )

    media = []

    for index, message in enumerate(
        messages
    ):

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
    # елементів в одному media group.

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
# PROCESS ALBUM
# =========================================================

async def process_album(
    group_id,
):

    # Даємо Telegram час передати
    # всі повідомлення альбому.
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

    source_text = ""

    # -----------------------------------------------------
    # Шукаємо caption серед усіх елементів
    # -----------------------------------------------------

    for message in messages:

        if message.caption:

            source_text = message.caption

            break

    # -----------------------------------------------------
    # Якщо caption є — одразу весь альбом
    # -----------------------------------------------------

    if source_text:

        await send_album(
            messages,
            source_text,
        )

        return

    # -----------------------------------------------------
    # Якщо caption немає —
    # чекаємо окремий текст
    # -----------------------------------------------------

    first_message = messages[0]

    user_id = first_message.from_user.id

    pending_media[user_id] = {
        "messages": messages,
        "type": "album",
    }

    asyncio.create_task(
        wait_for_text(
            first_message
        )
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

    user_id = message.from_user.id

    # =====================================================
    # TEXT
    # =====================================================

    if message.text:

        pending = pending_media.get(
            user_id
        )

        if pending:

            pending_media.pop(
                user_id,
                None,
            )

            text = message.text

            # ---------------------------------------------
            # Одне фото
            # ---------------------------------------------

            if pending["type"] == "photo":

                await send_photo(
                    pending["message"],
                    text,
                )

                return

            # ---------------------------------------------
            # Одне відео
            # ---------------------------------------------

            if pending["type"] == "video":

                await send_video(
                    pending["message"],
                    text,
                )

                return

            # ---------------------------------------------
            # Альбом
            # ---------------------------------------------

            if pending["type"] == "album":

                await send_album(
                    pending["messages"],
                    text,
                )

                return

        # -------------------------------------------------
        # Звичайний текст без медіа НЕ обробляємо
        # -------------------------------------------------

        return

    # =====================================================
    # АЛЬБОМ
    # =====================================================

    if message.media_group_id:

        group_id = message.media_group_id

        if group_id not in albums:

            albums[group_id] = []

        albums[group_id].append(
            message
        )

        # -------------------------------------------------
        # ВАЖЛИВО:
        #
        # Таймер запускаємо тільки один раз —
        # після першого повідомлення альбому.
        #
        # Telegram передає всі елементи одного
        # media_group майже одночасно.
        # -------------------------------------------------

        if len(albums[group_id]) == 1:

            asyncio.create_task(
                process_album(
                    group_id
                )
            )

        return

    # =====================================================
    # ОДНЕ ФОТО
    # =====================================================

    if message.photo:

        # Якщо caption вже є —
        # працюємо одразу.

        if message.caption:

            await send_photo(
                message,
                message.caption,
            )

            return

        # Якщо caption немає —
        # чекаємо текст.

        pending_media[user_id] = {
            "message": message,
            "type": "photo",
        }

        asyncio.create_task(
            wait_for_text(
                message
            )
        )

        return

    # =====================================================
    # ОДНЕ ВІДЕО
    # =====================================================

    if message.video:

        if message.caption:

            await send_video(
                message,
                message.caption,
            )

            return

        pending_media[user_id] = {
            "message": message,
            "type": "video",
        }

        asyncio.create_task(
            wait_for_text(
                message
            )
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
