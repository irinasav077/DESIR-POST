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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Тимчасове сховище для альбомів
media_groups = {}


# =================================================
# PRICE
# =================================================

def find_price(text):

    patterns = [
        r"(\d+(?:[.,]\d+)?)\s*€",
        r"(\d+(?:[.,]\d+)?)\s*€?\s*[\-–—]\s*\d+\s*%",
    ]

    for pattern in patterns:

        match = re.search(pattern, text)

        if match:
            return float(
                match.group(1).replace(",", ".")
            )

    return None


# =================================================
# DISCOUNT
# =================================================

def find_discount(text):

    match = re.search(
        r"-?\s*(\d{1,2})\s*%",
        text,
    )

    if match:
        return int(match.group(1))

    return None


# =================================================
# BRAND
# =================================================

def find_brand(text):

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    # Спочатку шукаємо hashtag
    for line in lines:

        if line.startswith("#"):

            brand = line.split()[0]

            return clean_brand(brand)

    # Потім шукаємо назву бренду
    for line in lines:

        # Ціна
        if re.search(
            r"\d+\s*€",
            line,
        ):
            continue

        # Знижка
        if re.search(
            r"\d+\s*%",
            line,
        ):
            continue

        # Тільки числа
        if re.fullmatch(
            r"[\d\s./,-]+",
            line,
        ):
            continue

        # Розміри
        if is_size_line(line):
            continue

        # FW / SS / NEW / SALE тощо
        if re.search(
            r"\b(FW|SS|NEW|SALE|DROP|COLLECTION)\d*",
            line,
            re.IGNORECASE,
        ):
            continue

        return clean_brand(line)

    return None


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

    # Прибираємо & та апострофи
    brand = re.sub(
        r"[&']",
        "",
        brand,
    )

    # Пробіли та дефіси прибираємо
    brand = re.sub(
        r"[\s-]+",
        "",
        brand,
    )

    return brand


# =================================================
# SIZES
# =================================================

SIZE_WORDS = {
    "XXXS",
    "XXS",
    "XS",
    "S",
    "M",
    "L",
    "XL",
    "XXL",
    "XXXL",
}


def is_size_line(line):

    cleaned = line.upper().strip()

    # S. M. L. XL.
    words = re.findall(
        r"[A-ZА-ЯІЇЄҐ]+",
        cleaned,
    )

    if words and all(
        word in SIZE_WORDS
        for word in words
    ):
        return True

    # Числові розміри:
    # 36 37 38
    # 37.5 38 38.5
    # 36/37/38
    numbers = re.findall(
        r"\b\d+(?:[.,]\d+)?\b",
        cleaned,
    )

    if numbers:

        other = re.sub(
            r"[\d\s/.,;:+-]",
            "",
            cleaned,
        )

        if not other:
            return True

    return False


def normalize_sizes(text):

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    # ---------------------------------------------
    # БУКВЕНІ РОЗМІРИ
    # ---------------------------------------------

    for line in lines:

        sizes = re.findall(
            r"\b(?:XXXS|XXS|XS|S|M|L|XL|XXL|XXXL)\b",
            line,
            re.IGNORECASE,
        )

        if sizes:

            return "/".join(
                size.upper()
                for size in sizes
            )

    # ---------------------------------------------
    # ЧИСЛОВІ РОЗМІРИ
    # ---------------------------------------------

    for line in lines:

        # Не беремо ціну
        if re.search(
            r"\d+\s*€",
            line,
        ):
            continue

        # Не беремо знижку
        if re.search(
            r"\d+\s*%",
            line,
        ):
            continue

        # Шукаємо:
        # 37
        # 37.5
        # 38
        # 38.5
        # 37/37.5/38/38.5
        # 36-37-38
        numbers = re.findall(
            r"\b\d+(?:[.,]\d+)?\b",
            line,
        )

        if not numbers:
            continue

        # Не беремо одиночне число 2
        if len(numbers) == 1:

            number = float(
                numbers[0].replace(",", ".")
            )

            if number < 30:
                continue

        # Перевіряємо, що рядок складається
        # тільки з чисел та розділових знаків
        cleaned = re.sub(
            r"[\d\s/.,;:+-]",
            "",
            line,
        )

        if not cleaned:

            result = []

            for number in numbers:

                number = number.replace(
                    ",",
                    ".",
                )

                result.append(number)

            return "/".join(result)

    return ""


# =================================================
# CREATE CAPTION
# =================================================

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

    # Рахуємо нову ціну
    new_price = round(
        price * (
            1 - new_discount / 100
        )
    )

    caption = (
        f"<i>#{brand}</i>\n"
        f"<i>{sizes}</i>\n\n"
        f"<i>🏷️{price:g}€-%={new_price}€</i>\n"
        f"<i>+ доставка 📦</i>\n\n"
        f"<i>Для консультації та замовлення:</i>\n"
        f"<i>💌@irasavchenkoo</i>"
    )

    return caption


# =================================================
# SINGLE PHOTO
# =================================================

async def send_photo(
    message,
    caption,
):

    await message.reply_photo(
        photo=message.photo[-1].file_id,
        caption=caption,
        parse_mode="HTML",
    )


# =================================================
# SINGLE VIDEO
# =================================================

async def send_video(
    message,
    caption,
):

    await message.reply_video(
        video=message.video.file_id,
        caption=caption,
        parse_mode="HTML",
    )


# =================================================
# MEDIA GROUP
# =================================================

async def send_album(
    first_message,
    messages,
):

    # Сортуємо медіа в правильному порядку
    messages.sort(
        key=lambda message: message.message_id
    )

    # Шукаємо caption.
    # У Telegram він зазвичай є тільки
    # в одному повідомленні альбому.
    source_text = ""

    for message in messages:

        if message.caption:

            source_text = message.caption

            break

    # Створюємо наш підпис
    caption = create_caption(
        source_text
    )

    media = []

    for index, message in enumerate(messages):

        # -----------------------------------------
        # PHOTO
        # -----------------------------------------

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

        # -----------------------------------------
        # VIDEO
        # -----------------------------------------

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

    # Telegram дозволяє максимум 10
    # медіафайлів в одному альбомі
    for start in range(
        0,
        len(media),
        10,
    ):

        chunk = media[
            start:start + 10
        ]

        # Якщо це друга частина альбому,
        # додаємо caption до першого файлу
        # цієї частини не потрібно.
        if start > 0:

            for item in chunk:

                item.caption = None

        await first_message.reply_media_group(
            media=chunk,
        )


# =================================================
# PROCESS ALBUM
# =================================================

async def process_album(
    group_id,
    first_message,
):

    # Чекаємо, поки Telegram
    # передасть усі елементи альбому
    await asyncio.sleep(2)

    messages = media_groups.pop(
        group_id,
        [],
    )

    if not messages:
        return

    await send_album(
        first_message,
        messages,
    )


# =================================================
# HANDLE MESSAGE
# =================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.message

    if not message:
        return

    # ---------------------------------------------
    # ALBUM
    # ---------------------------------------------

    if message.media_group_id:

        group_id = message.media_group_id

        if group_id not in media_groups:

            media_groups[group_id] = []

        media_groups[group_id].append(
            message
        )

        # Перший елемент запускає таймер
        if len(media_groups[group_id]) == 1:

            asyncio.create_task(
                process_album(
                    group_id,
                    message,
                )
            )

        return

    # ---------------------------------------------
    # SINGLE PHOTO
    # ---------------------------------------------

    if message.photo:

        text = (
            message.caption
            or ""
        )

        if not text:

            await message.reply_text(
                "⚠️ Не знайшов текст для обробки."
            )

            return

        caption = create_caption(
            text
        )

        await send_photo(
            message,
            caption,
        )

        return

    # ---------------------------------------------
    # SINGLE VIDEO
    # ---------------------------------------------

    if message.video:

        text = (
            message.caption
            or ""
        )

        if not text:

            await message.reply_text(
                "⚠️ Не знайшов текст для обробки."
            )

            return

        caption = create_caption(
            text
        )

        await send_video(
            message,
            caption,
        )

        return

    # ---------------------------------------------
    # TEXT
    # ---------------------------------------------

    if message.text:

        caption = create_caption(
            message.text
        )

        await message.reply_text(
            caption,
            parse_mode="HTML",
        )


# =================================================
# START
# =================================================

def main():

    if not BOT_TOKEN:

        raise ValueError(
            "BOT_TOKEN is not set"
        )

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
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

    app.run_polling()


if __name__ == "__main__":

    main()
