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

# ============================================================
# НАЛАШТУВАННЯ
# ============================================================

WAIT_SECONDS = 10

# Тут тимчасово зберігаємо повідомлення,
# які прийшли від одного користувача
message_batches = {}

# Таймери для кожного чату
batch_tasks = {}

# Альбоми Telegram
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

    # Спочатку шукаємо hashtag
    for line in lines:

        if line.startswith("#"):
            return clean_brand(
                line.split()[0]
            )

    # Якщо hashtag немає —
    # шукаємо звичайну назву бренду
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

    # Знижуємо знижку на 10 процентних пунктів
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
# ОБРОБКА ПАКЕТА ПОВІДОМЛЕНЬ
# ============================================================

async def process_batch(
    chat_id,
    context,
):

    # Беремо всі повідомлення,
    # які прийшли протягом 10 секунд
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
        f"Обробка пакета: "
        f"chat_id={chat_id}, "
        f"кількість={len(batch)}"
    )

    # ========================================================
    # ЗНАХОДИМО ТЕКСТ
    # ========================================================

    text_messages = []

    for message in batch:

        if message.text:

            text_messages.append(
                message.text
            )

    # Об'єднуємо весь текст пакета
    source_text = "\n".join(
        text_messages
    ).strip()

    # ========================================================
    # ЗНАХОДИМО ФОТО
    # ========================================================

    photos = []

    videos = []

    for message in batch:

        if message.photo:

            photos.append(
                message.photo[-1].file_id
            )

        elif message.video:

            videos.append(
                message.video.file_id
            )

    # ========================================================
    # ЯКЩО Є ФОТО + ТЕКСТ
    # ========================================================

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

    # ========================================================
    # ЯКЩО Є ВІДЕО + ТЕКСТ
    # ========================================================

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

    # ========================================================
    # ЯКЩО БУВ ЛИШЕ ТЕКСТ
    # ========================================================

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
# ЗАПУСК 10-СЕКУНДНОГО ТАЙМЕРА
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
# ОКРЕМЕ ПОВІДОМЛЕННЯ
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

        return

    # ========================================================
    # ДОДАЄМО ПОВІДОМЛЕННЯ В ПАКЕТ
    # ========================================================

    chat_id = message.chat_id

    if chat_id not in message_batches:

        message_batches[chat_id] = []

    message_batches[chat_id].append(
        message
    )

    logging.info(
        f"Повідомлення додано в пакет: "
        f"chat_id={chat_id}"
    )

    # ========================================================
    # ПЕРШЕ ПОВІДОМЛЕННЯ ЗАПУСКАЄ ТАЙМЕР
    # ========================================================

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
