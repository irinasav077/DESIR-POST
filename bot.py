import os
import re
import asyncio
import logging

from telegram import Update, InputMediaPhoto, InputMediaVideo
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

# Окремі повідомлення, які приходять від користувача
pending_messages = {}

# Вже зібрані альбоми
albums = {}


# =========================
# PRICE
# =========================

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


# =========================
# DISCOUNT
# =========================

def find_discount(text):
    match = re.search(r"-?\s*(\d{1,2})\s*%", text)

    if match:
        return int(match.group(1))

    return None


# =========================
# BRAND
# =========================

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

    # Потім звичайну назву бренду
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


# =========================
# SIZES
# =========================

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

    # XS / S / M / L
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

    # Цифрові розміри
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

        # Одна цифра типу "2" — не розмір
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


# =========================
# CAPTION
# =========================

def create_caption(text):

    price = find_price(text)
    discount = find_discount(text)
    brand = find_brand(text)
    sizes = normalize_sizes(text)

    if price is None:
        return "<i>⚠️ Не вдалося знайти ціну.</i>"

    if discount is None:
        return "<i>⚠️ Не вдалося знайти знижку.</i>"

    if not brand:
        brand = "brand"

    # Мінус 10% від початкової знижки
    new_discount = max(discount - 10, 0)

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


# =========================
# TEXT FROM MESSAGE
# =========================

def get_message_text(message):

    if message.caption:
        return message.caption

    if message.text:
        return message.text

    return ""


# =========================
# MEDIA FROM MESSAGE
# =========================

def get_media(message):

    if message.photo:

        return (
            "photo",
            message.photo[-1].file_id,
        )

    if message.video:

        return (
            "video",
            message.video.file_id,
        )

    # Якщо фото прийшло як документ
    if message.document:

        mime = message.document.mime_type or ""

        if mime.startswith("image/"):

            return (
                "photo",
                message.document.file_id,
            )

    return None, None


# =========================
# PROCESS ALBUM
# =========================

async def process_album(chat_id, group_id):

    await asyncio.sleep(WAIT_SECONDS)

    key = (chat_id, group_id)

    messages = albums.pop(key, [])

    if not messages:
        return

    # Сортуємо в правильному порядку
    messages.sort(
        key=lambda m: m.message_id
    )

    logging.info(
        "PROCESS ALBUM chat=%s group=%s messages=%s",
        chat_id,
        group_id,
        len(messages),
    )

    # -------------------------
    # Шукаємо текст
    # -------------------------

    source_text = ""

    for message in messages:

        text = get_message_text(message)

        if text:
            source_text = text
            break

    # Якщо тексту в самому альбомі немає,
    # шукаємо текст серед pending messages
    if not source_text:

        pending_key = chat_id

        pending = pending_messages.get(
            pending_key,
            [],
        )

        for item in pending:

            text = item.get("text", "")

            if text:

                source_text = text
                break

    if not source_text:

        await messages[0].reply_text(
            "⚠️ Не знайшов текст із брендом, ціною та знижкою."
        )

        return

    caption = create_caption(source_text)

    # -------------------------
    # Формуємо медіа
    # -------------------------

    media = []

    for index, message in enumerate(messages):

        media_type, file_id = get_media(message)

        if not file_id:
            continue

        if media_type == "photo":

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

        elif media_type == "video":

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

    if not media:
        return

    # Telegram дозволяє максимум 10 медіа
    for start in range(0, len(media), 10):

        chunk = media[start:start + 10]

        await messages[0].reply_media_group(
            media=chunk
        )

    # Після обробки видаляємо використаний текст
    pending_messages.pop(
        chat_id,
        None,
    )


# =========================
# PROCESS SEPARATE MESSAGES
# =========================

async def process_pending(chat_id):

    await asyncio.sleep(WAIT_SECONDS)

    items = pending_messages.pop(
        chat_id,
        [],
    )

    if not items:
        return

    media_items = []
    source_text = ""

    # -------------------------
    # Збираємо текст і медіа
    # -------------------------

    for item in items:

        message = item["message"]

        text = get_message_text(message)

        if text:
            source_text = text

        media_type, file_id = get_media(message)

        if file_id:

            media_items.append(
                (
                    media_type,
                    file_id,
                    message,
                )
            )

    if not media_items:
        return

    if not source_text:

        await items[0]["message"].reply_text(
            "⚠️ Не знайшов текст із брендом, ціною та знижкою."
        )

        return

    caption = create_caption(
        source_text
    )

    # -------------------------
    # Одне фото
    # -------------------------

    if len(media_items) == 1:

        media_type, file_id, message = media_items[0]

        if media_type == "photo":

            await message.reply_photo(
                photo=file_id,
                caption=caption,
                parse_mode="HTML",
            )

        elif media_type == "video":

            await message.reply_video(
                video=file_id,
                caption=caption,
                parse_mode="HTML",
            )

        return

    # -------------------------
    # Кілька окремих фото
    # -------------------------

    media = []

    for index, (
        media_type,
        file_id,
        message,
    ) in enumerate(media_items):

        if media_type == "photo":

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

        elif media_type == "video":

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

        chunk = media[start:start + 10]

        await items[0]["message"].reply_media_group(
            media=chunk
        )


# =========================
# MAIN HANDLER
# =========================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.message

    if not message:
        return

    chat_id = message.chat_id

    logging.info(
        "MESSAGE id=%s photo=%s video=%s document=%s "
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

    # ==================================================
    # АЛЬБОМ
    # ==================================================

    if message.media_group_id:

        group_id = message.media_group_id

        key = (chat_id, group_id)

        if key not in albums:

            albums[key] = []

            asyncio.create_task(
                process_album(
                    chat_id,
                    group_id,
                )
            )

        albums[key].append(message)

        return

    # ==================================================
    # ЗВИЧАЙНЕ ПОВІДОМЛЕННЯ
    # ==================================================

    # Якщо це одиночне фото / відео / документ
    media_type, file_id = get_media(message)

    text = get_message_text(message)

    # Створюємо чергу для 10 секунд
    if chat_id not in pending_messages:

        pending_messages[chat_id] = []

    pending_messages[chat_id].append(
        {
            "message": message,
            "text": text,
        }
    )

    # Якщо це перше повідомлення,
    # запускаємо обробку через 10 секунд
    if len(pending_messages[chat_id]) == 1:

        asyncio.create_task(
            process_pending(chat_id)
        )


# =========================
# START
# =========================

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

    # ВАЖЛИВО:
    # Document.ALL доданий спеціально для випадків,
    # коли переслане фото приходить як document.

    application.add_handler(
        MessageHandler(
            filters.PHOTO
            | filters.VIDEO
            | filters.Document.ALL
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
