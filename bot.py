import os
import re
import asyncio
import logging

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

WAIT_SECONDS = 10

# Повідомлення, які чекають на об'єднання
message_batches = {}

# Таймери
batch_tasks = {}

# Telegram albums
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
            return float(
                match.group(1).replace(",", ".")
            )

    return None


# ============================================================
# DISCOUNT
# ============================================================

def find_discount(text):
    match = re.search(
        r"-?\s*(\d{1,2})\s*%",
        text,
    )

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

    # Назва бренду текстом
    for line in lines:

        if re.search(r"\d+\s*€", line):
            continue

        if re.search(r"\d+\s*%", line):
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

        # Самотнє маленьке число типу 2
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
            result.append(
                number.replace(",", ".")
            )

        return "/".join(result)

    return ""


# ============================================================
# CAPTION
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

    # Зменшуємо знижку на 10 процентних пунктів
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


# ============================================================
# ВИТЯГУЄМО ТЕКСТ
# ============================================================

def get_message_text(message):
    """
    Текст може бути:
    - звичайним message.text
    - caption до фото/відео/document
    """

    if message.text:
        return message.text

    if message.caption:
        return message.caption

    return ""


# ============================================================
# ВИТЯГУЄМО ФОТО
# ============================================================

def get_photo_file_id(message):
    """
    Підтримує:
    - звичайне фото
    - фото, переслане з каналу
    - photo з caption
    """

    if message.photo:
        return message.photo[-1].file_id

    return None


# ============================================================
# ВИТЯГУЄМО ВІДЕО
# ============================================================

def get_video_file_id(message):

    if message.video:
        return message.video.file_id

    return None


# ============================================================
# ОБРОБКА ОДНОГО ПАКЕТА
# ============================================================

async def process_batch(
    chat_id,
    context,
):

    batch = message_batches.pop(
        chat_id,
        [],
    )

    batch_tasks.pop(
        chat_id,
        None,
    )

    if not batch:
        return

    logging.info(
        "Processing batch: chat_id=%s messages=%s",
        chat_id,
        len(batch),
    )

    # --------------------------------------------------------
    # ЗБИРАЄМО ВЕСЬ ТЕКСТ
    # --------------------------------------------------------

    texts = []

    for message in batch:

        text = get_message_text(
            message
        )

        if text:
            texts.append(text)

    source_text = "\n".join(
        texts
    ).strip()

    # --------------------------------------------------------
    # ЗБИРАЄМО ФОТО
    # --------------------------------------------------------

    photos = []

    videos = []

    for message in batch:

        photo_id = get_photo_file_id(
            message
        )

        if photo_id:
            photos.append(photo_id)

        video_id = get_video_file_id(
            message
        )

        if video_id:
            videos.append(video_id)

    # --------------------------------------------------------
    # ФОТО + ТЕКСТ
    # --------------------------------------------------------

    if photos and source_text:

        caption = create_caption(
            source_text
        )

        # Одне фото
        if len(photos) == 1:

            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photos[0],
                caption=caption,
                parse_mode="HTML",
            )

            return

        # Кілька фото
        media = []

        for index, file_id in enumerate(
            photos
        ):

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

        for start in range(
            0,
            len(media),
            10,
        ):

            chunk = media[
                start:start + 10
            ]

            await context.bot.send_media_group(
                chat_id=chat_id,
                media=chunk,
            )

        return

    # --------------------------------------------------------
    # ВІДЕО + ТЕКСТ
    # --------------------------------------------------------

    if videos and source_text:

        caption = create_caption(
            source_text
        )

        if len(videos) == 1:

            await context.bot.send_video(
                chat_id=chat_id,
                video=videos[0],
                caption=caption,
                parse_mode="HTML",
            )

            return

        media = []

        for index, file_id in enumerate(
            videos
        ):

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
                chat_id=chat_id,
                media=chunk,
            )

        return

    # --------------------------------------------------------
    # ТІЛЬКИ ТЕКСТ
    # --------------------------------------------------------

    if source_text:

        caption = create_caption(
            source_text
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode="HTML",
        )

        return


# ============================================================
# ТАЙМЕР 10 СЕКУНД
# ============================================================

async def start_batch_timer(
    chat_id,
    context,
):

    await asyncio.sleep(
        WAIT_SECONDS
    )

    await process_batch(
        chat_id,
        context,
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

    # Шукаємо текст/caption
    texts = []

    for message in messages:

        text = get_message_text(
            message
        )

        if text:
            texts.append(text)

    source_text = "\n".join(
        texts
    ).strip()

    photos = []

    videos = []

    for message in messages:

        photo_id = get_photo_file_id(
            message
        )

        if photo_id:
            photos.append(photo_id)

        video_id = get_video_file_id(
            message
        )

        if video_id:
            videos.append(video_id)

    # Якщо album уже має текст
    if source_text:

        caption = create_caption(
            source_text
        )

        media = []

        for index, file_id in enumerate(
            photos
        ):

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

        for index, file_id in enumerate(
            videos
        ):

            if not media:

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

    # Якщо album без тексту —
    # додаємо його в загальний пакет
    chat_id = messages[0].chat_id

    if chat_id not in message_batches:

        message_batches[chat_id] = []

    message_batches[chat_id].extend(
        messages
    )

    if chat_id not in batch_tasks:

        task = asyncio.create_task(
            start_batch_timer(
                chat_id,
                context,
            )
        )

        batch_tasks[chat_id] = task


# ============================================================
# ГОЛОВНИЙ HANDLER
# ============================================================

async def handle_message(
    update,
    context,
):

    message = update.message

    if not message:
        return

    # --------------------------------------------------------
    # ДІАГНОСТИКА
    # --------------------------------------------------------

    logging.info(
        "MESSAGE: photo=%s video=%s document=%s "
        "text=%s caption=%s forwarded=%s",
        bool(message.photo),
        bool(message.video),
        bool(message.document),
        bool(message.text),
        bool(message.caption),
        bool(message.forward_origin),
    )

    # --------------------------------------------------------
    # ALBUM
    # --------------------------------------------------------

    if message.media_group_id:

        group_id = message.media_group_id

        if group_id not in albums:

            albums[group_id] = []

        albums[group_id].append(
            message
        )

        if len(albums[group_id]) == 1:

            asyncio.create_task(
                process_album(
                    group_id,
                    context,
                )
            )

        return

    # --------------------------------------------------------
    # ДОДАЄМО ПОВІДОМЛЕННЯ В ПАКЕТ
    # --------------------------------------------------------

    chat_id = message.chat_id

    if chat_id not in message_batches:

        message_batches[chat_id] = []

    message_batches[chat_id].append(
        message
    )

    logging.info(
        "Added message to batch: "
        "chat_id=%s",
        chat_id,
    )

    # --------------------------------------------------------
    # ЗАПУСКАЄМО 10-СЕКУНДНИЙ ТАЙМЕР
    # --------------------------------------------------------

    if chat_id not in batch_tasks:

        task = asyncio.create_task(
            start_batch_timer(
                chat_id,
                context,
            )
        )

        batch_tasks[chat_id] = task


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
