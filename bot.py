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

# Останнє фото/відео, яке чекає текст
pending_media = {}

# Скільки секунд чекати на текст
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

    # Спочатку hashtag

    for line in lines:

        if line.startswith("#"):

            return clean_brand(
                line.split()[0]
            )

    # Потім назва бренду

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

        # "2" саме по собі не є розміром

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

    # Мінус 10 процентних пунктів

    new_discount = max(
        discount - 10,
        0,
    )

    # Нова ціна

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
# SEND PHOTO + TEXT
# =========================================================

async def send_photo_with_text(
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
# SEND VIDEO + TEXT
# =========================================================

async def send_video_with_text(
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
# SEND ALBUM + TEXT
# =========================================================

async def send_album_with_text(
    messages,
    text,
):

    caption = create_caption(
        text
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

    # Максимум 10 елементів

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
# DELETE OLD PENDING MEDIA
# =========================================================

async def remove_pending_media(
    chat_id,
    message_id,
):

    await asyncio.sleep(
        WAIT_SECONDS
    )

    pending = pending_media.get(
        chat_id
    )

    if not pending:
        return

    # Видаляємо тільки те фото,
    # для якого був запущений цей таймер.
    #
    # Якщо за цей час прийшло нове фото,
    # старий таймер його не видалить.

    if pending["message_id"] == message_id:

        pending_media.pop(
            chat_id,
            None,
        )


# =========================================================
# PROCESS ALBUM
# =========================================================

async def process_album(
    group_id,
):

    # Даємо Telegram час
    # передати всі фото/відео

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

    # Якщо caption уже є —
    # обробляємо одразу

    source_text = ""

    for message in messages:

        if message.caption:

            source_text = message.caption

            break

    if source_text:

        await send_album_with_text(
            messages,
            source_text,
        )

        return

    # Якщо caption немає —
    # запам'ятовуємо альбом

    chat_id = messages[0].chat_id

    pending_media[chat_id] = {
        "type": "album",
        "messages": messages,
        "message_id": messages[0].message_id,
    }

    asyncio.create_task(
        remove_pending_media(
            chat_id,
            messages[0].message_id,
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

    chat_id = message.chat_id

    # =====================================================
    # 1. TEXT
    # =====================================================

    if message.text:

        # -------------------------------------------------
        # НАЙВАЖЛИВІШЕ:
        # СПОЧАТКУ ПЕРЕВІРЯЄМО ОЧІКУВАНЕ ФОТО
        # -------------------------------------------------

        pending = pending_media.pop(
            chat_id,
            None,
        )

        if pending:

            text = message.text

            # Фото

            if pending["type"] == "photo":

                await send_photo_with_text(
                    pending["message"],
                    text,
                )

                return

            # Відео

            if pending["type"] == "video":

                await send_video_with_text(
                    pending["message"],
                    text,
                )

                return

            # Альбом

            if pending["type"] == "album":

                await send_album_with_text(
                    pending["messages"],
                    text,
                )

                return

        # -------------------------------------------------
        # ЯКЩО ФОТО НЕ ЧЕКАЄ —
        # ЦЕ ЗВИЧАЙНИЙ ТЕКСТ
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
    # 2. ALBUM
    # =====================================================

    if message.media_group_id:

        group_id = message.media_group_id

        if group_id not in albums:

            albums[group_id] = []

        albums[group_id].append(
            message
        )

        # Запускаємо обробку тільки один раз

        if len(albums[group_id]) == 1:

            asyncio.create_task(
                process_album(
                    group_id
                )
            )

        return

    # =====================================================
    # 3. SINGLE PHOTO
    # =====================================================

    if message.photo:

        # Якщо caption вже є —
        # обробляємо одразу

        if message.caption:

            await send_photo_with_text(
                message,
                message.caption,
            )

            return

        # -------------------------------------------------
        # ФОТО БЕЗ CAPTION
        # -------------------------------------------------

        pending_media[chat_id] = {
            "type": "photo",
            "message": message,
            "message_id": message.message_id,
        }

        # Запускаємо 10-секундний таймер

        asyncio.create_task(
            remove_pending_media(
                chat_id,
                message.message_id,
            )
        )

        return

    # =====================================================
    # 4. SINGLE VIDEO
    # =====================================================

    if message.video:

        # Якщо caption вже є —
        # обробляємо одразу

        if message.caption:

            await send_video_with_text(
                message,
                message.caption,
            )

            return

        # -------------------------------------------------
        # ВІДЕО БЕЗ CAPTION
        # -------------------------------------------------

        pending_media[chat_id] = {
            "type": "video",
            "message": message,
            "message_id": message.message_id,
        }

        asyncio.create_task(
            remove_pending_media(
                chat_id,
                message.message_id,
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
