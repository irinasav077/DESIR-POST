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

# ============================================================
# НАЛАШТУВАННЯ
# ============================================================

WAIT_SECONDS = 10

# Очікуємо текст після окремо надісланого фото/відео
pending_media = {}

# Альбоми
albums = {}


# ============================================================
# PRICE
# ============================================================

def find_price(text):
    patterns = [
        r"(\d+(?:[.,]\d+)?)\s*€",
        r"(\d+(?:[.,]\d+)?)\s*€?\s*[-–—]\s*\d+\s*%",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            return float(match.group(1).replace(",", "."))

    return None


# ============================================================
# DISCOUNT
# ============================================================

def find_discount(text):
    match = re.search(r"-?\s*(\d{1,2})\s*%", text)

    if match:
        return int(match.group(1))

    return None


# ============================================================
# BRAND
# ============================================================

def clean_brand(brand):
    brand = brand.replace("#", "")
    brand = brand.lower()

    brand = re.sub(
        r"[^a-zа-яіїєґ0-9\s&'-]",
        "",
        brand,
    )

    brand = brand.replace("&", "")
    brand = brand.replace("'", "")

    brand = re.sub(r"[\s-]+", "", brand)

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
            return clean_brand(line.split()[0])

    # Потім шукаємо назву бренду
    for line in lines:

        if re.search(r"\d+\s*€", line):
            continue

        if re.search(r"\d+\s*%", line):
            continue

        if re.fullmatch(r"[\d\s./,-]+", line):
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


# ============================================================
# SIZES
# ============================================================

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

    # Буквені розміри
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

    # Числові розміри
    for line in lines:

        if re.search(r"\d+\s*%", line):
            continue

        if "€" in line:
            continue

        numbers = re.findall(
            r"\d+(?:[.,]\d+)?",
            line,
        )

        if not numbers:
            continue

        # Одне маленьке число типу "2"
        # не вважаємо розміром
        if len(numbers) == 1:

            try:

                number = float(
                    numbers[0].replace(",", ".")
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

            number = number.replace(",", ".")

            result.append(number)

        return "/".join(result)

    return ""


# ============================================================
# CREATE CAPTION
# ============================================================

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

    # Зменшуємо знижку на 10%
    new_discount = max(
        discount - 10,
        0,
    )

    new_price = round(
        price * (1 - new_discount / 100)
    )

    return (
        f"<i>#{brand}</i>\n"
        f"<i>{sizes}</i>\n\n"
        f"<i>🏷️{price:g}€-%={new_price}€</i>\n"
        f"<i>+ доставка 📦</i>\n\n"
        f"<i>Для консультації та замовлення:</i>\n"
        f"<i>💌@irasavchenkoo</i>"
    )


# ============================================================
# ВІДПРАВКА ОКРЕМОГО ФОТО
# ============================================================

async def send_pending_photo(
    context,
    chat_id,
    media_data,
    caption,
):

    await context.bot.send_photo(
        chat_id=chat_id,
        photo=media_data["file_id"],
        caption=caption,
        parse_mode="HTML",
    )


# ============================================================
# ВІДПРАВКА ОКРЕМОГО ВІДЕО
# ============================================================

async def send_pending_video(
    context,
    chat_id,
    media_data,
    caption,
):

    await context.bot.send_video(
        chat_id=chat_id,
        video=media_data["file_id"],
        caption=caption,
        parse_mode="HTML",
    )


# ============================================================
# ТАЙМЕР 10 СЕКУНД
# ============================================================

async def wait_for_caption(
    chat_id,
    context,
    message_id,
):

    await asyncio.sleep(WAIT_SECONDS)

    data = pending_media.get(chat_id)

    if not data:
        return

    # Перевіряємо, що це все ще те саме фото
    if data.get("message_id") != message_id:
        return

    # Якщо текст за 10 секунд не прийшов —
    # видаляємо очікування
    pending_media.pop(chat_id, None)

    logging.info(
        f"10 секунд минули. Очікування тексту завершено: {chat_id}"
    )


# ============================================================
# ФОТО
# ============================================================

async def handle_photo(
    message,
    context,
):

    text = message.caption or ""

    # --------------------------------------------------------
    # Якщо caption є одразу з фото
    # --------------------------------------------------------

    if text:

        caption = create_caption(text)

        await context.bot.send_photo(
            chat_id=message.chat_id,
            photo=message.photo[-1].file_id,
            caption=caption,
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # Якщо фото БЕЗ caption —
    # запам'ятовуємо його на 10 секунд
    # --------------------------------------------------------

    chat_id = message.chat_id

    pending_media[chat_id] = {
        "type": "photo",
        "file_id": message.photo[-1].file_id,
        "message_id": message.message_id,
    }

    logging.info(
        f"Фото очікує текст 10 секунд. chat_id={chat_id}"
    )

    asyncio.create_task(
        wait_for_caption(
            chat_id,
            context,
            message.message_id,
        )
    )


# ============================================================
# ВІДЕО
# ============================================================

async def handle_video(
    message,
    context,
):

    text = message.caption or ""

    # Якщо caption є одразу
    if text:

        caption = create_caption(text)

        await context.bot.send_video(
            chat_id=message.chat_id,
            video=message.video.file_id,
            caption=caption,
            parse_mode="HTML",
        )

        return

    # Якщо відео без caption
    chat_id = message.chat_id

    pending_media[chat_id] = {
        "type": "video",
        "file_id": message.video.file_id,
        "message_id": message.message_id,
    }

    logging.info(
        f"Відео очікує текст 10 секунд. chat_id={chat_id}"
    )

    asyncio.create_task(
        wait_for_caption(
            chat_id,
            context,
            message.message_id,
        )
    )


# ============================================================
# ТЕКСТ
# ============================================================

async def handle_text(
    message,
    context,
):

    text = message.text or ""

    chat_id = message.chat_id

    # ========================================================
    # НАЙВАЖЛИВІША ЧАСТИНА
    #
    # Якщо перед цим було фото/відео,
    # НЕ ВІДПРАВЛЯЄМО ТЕКСТ ОКРЕМО.
    #
    # Використовуємо його як дані для caption.
    # ========================================================

    if chat_id in pending_media:

        media_data = pending_media.pop(chat_id)

        logging.info(
            f"Знайдено очікуване медіа для тексту. "
            f"chat_id={chat_id}"
        )

        caption = create_caption(text)

        if media_data["type"] == "photo":

            await send_pending_photo(
                context,
                chat_id,
                media_data,
                caption,
            )

            return

        if media_data["type"] == "video":

            await send_pending_video(
                context,
                chat_id,
                media_data,
                caption,
            )

            return

    # ========================================================
    # Якщо фото/відео НЕ було —
    # тоді обробляємо звичайний текст
    # ========================================================

    caption = create_caption(text)

    await context.bot.send_message(
        chat_id=chat_id,
        text=caption,
        parse_mode="HTML",
    )


# ============================================================
# АЛЬБОМ
# ============================================================

async def process_album(
    group_id,
    context,
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

    source_text = ""

    for message in messages:

        if message.caption:

            source_text = message.caption
            break

    # --------------------------------------------------------
    # Якщо в альбомі caption уже є —
    # обробляємо одразу
    # --------------------------------------------------------

    if source_text:

        caption = create_caption(
            source_text
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
                            media=file_id
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
                            media=file_id
                        )
                    )

        for start in range(
            0,
            len(media),
            10,
        ):

            chunk = media[
                start:start + 10
            ]

            await context.bot.send_media_group(
                chat_id=messages[0].chat_id,
                media=chunk,
            )

        return

    # --------------------------------------------------------
    # Альбом БЕЗ caption
    #
    # Запам'ятовуємо його і чекаємо текст 10 сек
    # --------------------------------------------------------

    chat_id = messages[0].chat_id

    media_items = []

    for message in messages:

        if message.photo:

            media_items.append({
                "type": "photo",
                "file_id": message.photo[-1].file_id,
            })

        elif message.video:

            media_items.append({
                "type": "video",
                "file_id": message.video.file_id,
            })

    if not media_items:
        return

    pending_media[chat_id] = {
        "type": "album",
        "items": media_items,
        "message_id": messages[0].message_id,
    }

    logging.info(
        f"Альбом очікує текст 10 секунд. "
        f"chat_id={chat_id}"
    )

    asyncio.create_task(
        wait_for_caption(
            chat_id,
            context,
            messages[0].message_id,
        )
    )


# ============================================================
# ОБРОБКА ПОВІДОМЛЕНЬ
# ============================================================

async def handle_message(
    update,
    context,
):

    message = update.message

    if not message:
        return

    # ========================================================
    # АЛЬБОМ
    # ========================================================

    if message.media_group_id:

        group_id = message.media_group_id

        if group_id not in albums:

            albums[group_id] = []

        albums[group_id].append(
            message
        )

        # Перший елемент запускає обробку
        if len(albums[group_id]) == 1:

            asyncio.create_task(
                process_album(
                    group_id,
                    context,
                )
            )

        return

    # ========================================================
    # ОКРЕМЕ ФОТО
    # ========================================================

    if message.photo:

        await handle_photo(
            message,
            context,
        )

        return

    # ========================================================
    # ОКРЕМЕ ВІДЕО
    # ========================================================

    if message.video:

        await handle_video(
            message,
            context,
        )

        return

    # ========================================================
    # ТЕКСТ
    # ========================================================

    if message.text:

        await handle_text(
            message,
            context,
        )

        return


# ============================================================
# MAIN
# ============================================================

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
