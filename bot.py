import os
import re
import asyncio
import logging

from telegram import (
    Update,
    InputMediaPhoto,
    InputMediaVideo,
)

from telegram.ext import (
    Application,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")

WAIT_SECONDS = 10


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# BATCH STORAGE
# =========================================================

# Усі повідомлення одного користувача/чату,
# які прийшли протягом 10 секунд
batches = {}

# Таймери обробки
batch_tasks = {}


# =========================================================
# PRICE
# =========================================================

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


# =========================================================
# DISCOUNT
# =========================================================

def find_discount(text):

    match = re.search(
        r"-?\s*(\d{1,2})\s*%",
        text,
    )

    if match:

        return int(match.group(1))

    return None


# =========================================================
# BRAND
# =========================================================

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

    # -------------------------
    # Hashtag
    # -------------------------

    for line in lines:

        if line.startswith("#"):

            return clean_brand(
                line.split()[0]
            )

    # -------------------------
    # Назва бренду текстом
    # -------------------------

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

    # Буквені розміри

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

    # Цифрові розміри

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

    # -------------------------
    # XS / S / M / L
    # -------------------------

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

    # -------------------------
    # Цифрові
    # -------------------------

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

        # Одиночна цифра типу "2" —
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

    # Зменшуємо знижку на 10%
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
# GET TEXT
# =========================================================

def get_text(message):

    if message.caption:
        return message.caption

    if message.text:
        return message.text

    return ""


# =========================================================
# GET MEDIA
# =========================================================

def get_media(message):

    # Фото
    if message.photo:

        return (
            "photo",
            message.photo[-1].file_id,
        )

    # Відео
    if message.video:

        return (
            "video",
            message.video.file_id,
        )

    # Якщо переслане фото Telegram передав
    # як document
    if message.document:

        mime = message.document.mime_type or ""

        if mime.startswith("image/"):

            return (
                "photo",
                message.document.file_id,
            )

        if mime.startswith("video/"):

            return (
                "video",
                message.document.file_id,
            )

    return (
        None,
        None,
    )


# =========================================================
# ADD MESSAGE TO BATCH
# =========================================================

async def add_to_batch(message):

    chat_id = message.chat_id

    if chat_id not in batches:

        batches[chat_id] = []

    batches[chat_id].append(message)

    logger.info(
        "ADDED TO BATCH: "
        "id=%s photo=%s video=%s document=%s "
        "text=%s caption=%s media_group=%s",
        message.message_id,
        bool(message.photo),
        bool(message.video),
        bool(message.document),
        bool(message.text),
        bool(message.caption),
        message.media_group_id,
    )

    # Якщо вже був таймер —
    # скасовуємо його
    old_task = batch_tasks.get(chat_id)

    if old_task:

        old_task.cancel()

    # Створюємо новий таймер
    batch_tasks[chat_id] = asyncio.create_task(
        wait_and_process(chat_id)
    )


# =========================================================
# WAIT 10 SECONDS
# =========================================================

async def wait_and_process(chat_id):

    try:

        await asyncio.sleep(
            WAIT_SECONDS
        )

    except asyncio.CancelledError:

        return

    await process_batch(chat_id)


# =========================================================
# PROCESS BATCH
# =========================================================

async def process_batch(chat_id):

    messages = batches.pop(
        chat_id,
        [],
    )

    batch_tasks.pop(
        chat_id,
        None,
    )

    if not messages:
        return

    # -------------------------
    # Сортуємо за message_id
    # -------------------------

    messages.sort(
        key=lambda m: m.message_id
    )

    logger.info(
        "PROCESSING BATCH: chat=%s messages=%s",
        chat_id,
        len(messages),
    )

    # -------------------------
    # Збираємо весь текст
    # -------------------------

    text_parts = []

    for message in messages:

        text = get_text(message)

        if text:

            text_parts.append(
                text
            )

    source_text = "\n".join(
        text_parts
    ).strip()

    # -------------------------
    # Збираємо всі медіа
    # -------------------------

    media_items = []

    seen_file_ids = set()

    for message in messages:

        media_type, file_id = get_media(
            message
        )

        if not file_id:
            continue

        # Не додаємо одне й те саме фото двічі
        if file_id in seen_file_ids:
            continue

        seen_file_ids.add(file_id)

        media_items.append(
            (
                media_type,
                file_id,
                message,
            )
        )

    logger.info(
        "FOUND MEDIA=%s TEXT=%s",
        len(media_items),
        bool(source_text),
    )

    # -------------------------
    # Якщо немає медіа
    # -------------------------

    if not media_items:

        if source_text:

            # Просто текст —
            # нічого не робимо
            logger.info(
                "TEXT ONLY - waiting for media"
            )

        return

    # -------------------------
    # Якщо немає тексту
    # -------------------------

    if not source_text:

        await messages[0].reply_text(
            "⚠️ Не знайшов текст із брендом, "
            "ціною, знижкою та розмірами."
        )

        return

    # -------------------------
    # Створюємо caption
    # -------------------------

    caption = create_caption(
        source_text
    )

    # =====================================================
    # ОДНЕ МЕДІА
    # =====================================================

    if len(media_items) == 1:

        media_type, file_id, original_message = (
            media_items[0]
        )

        if media_type == "photo":

            await original_message.reply_photo(
                photo=file_id,
                caption=caption,
                parse_mode="HTML",
            )

            return

        if media_type == "video":

            await original_message.reply_video(
                video=file_id,
                caption=caption,
                parse_mode="HTML",
            )

            return

    # =====================================================
    # АЛЬБОМ
    # =====================================================

    media = []

    for index, (
        media_type,
        file_id,
        original_message,
    ) in enumerate(media_items):

        # Caption ставимо тільки на перше фото
        if index == 0:

            if media_type == "photo":

                media.append(
                    InputMediaPhoto(
                        media=file_id,
                        caption=caption,
                        parse_mode="HTML",
                    )
                )

            elif media_type == "video":

                media.append(
                    InputMediaVideo(
                        media=file_id,
                        caption=caption,
                        parse_mode="HTML",
                    )
                )

        else:

            if media_type == "photo":

                media.append(
                    InputMediaPhoto(
                        media=file_id
                    )
                )

            elif media_type == "video":

                media.append(
                    InputMediaVideo(
                        media=file_id
                    )
                )

    # Telegram дозволяє максимум 10
    # елементів у одному media group
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

    logger.info(
        "ALBUM SENT: %s media",
        len(media_items),
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

    logger.info(
        "INCOMING: "
        "id=%s photo=%s video=%s document=%s "
        "text=%s caption=%s media_group=%s forwarded=%s",
        message.message_id,
        bool(message.photo),
        bool(message.video),
        bool(message.document),
        bool(message.text),
        bool(message.caption),
        message.media_group_id,
        bool(message.forward_origin),
    )

    await add_to_batch(
        message
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

    # Ловимо ВСІ типи повідомлень,
    # включно з forwarded documents.
    application.add_handler(
        MessageHandler(
            filters.ALL,
            handle_message,
        )
    )

    logger.info(
        "DESIR POST BOT started"
    )

    application.run_polling()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
