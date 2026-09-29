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

# Зберігаємо альбоми, які ще збираються
media_groups = {}


# -------------------------------------------------
# PRICE
# -------------------------------------------------

def find_price(text):

    patterns = [
        r"(\d+(?:[.,]\d+)?)\s*€",
        r"(\d+(?:[.,]\d+)?)\s*€?\s*[\-–—]\s*\d+\s*%",
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


# -------------------------------------------------
# DISCOUNT
# -------------------------------------------------

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


# -------------------------------------------------
# BRAND
# -------------------------------------------------

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

    brand = re.sub(
        r"[&']",
        "",
        brand,
    )

    brand = re.sub(
        r"[\s-]+",
        "",
        brand,
    )

    return brand


# -------------------------------------------------
# SIZES
# -------------------------------------------------

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

    words = re.findall(
        r"[A-ZА-ЯІЇЄҐ]+",
        cleaned,
    )

    if words and all(
        word in SIZE_WORDS
        for word in words
    ):
        return True

    numbers = re.findall(
        r"\b\d{2}\b",
        cleaned,
    )

    if numbers:

        other = re.sub(
            r"[\d\s/.,;:-]",
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

    # Буквені розміри
    for line in lines:

        if re.search(
            r"\b(?:XXXS|XXS|XS|S|M|L|XL|XXL|XXXL)\b",
            line,
            re.IGNORECASE,
        ):

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

    # Числові розміри
    for line in lines:

        numbers = re.findall(
            r"\b\d{2}\b",
            line,
        )

        if numbers:

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

            cleaned = re.sub(
                r"[\d\s/.,;:-]",
                "",
                line,
            )

            if not cleaned:

                return "/".join(numbers)

    return ""


# -------------------------------------------------
# CREATE CAPTION
# -------------------------------------------------

def create_caption(text):

    price = find_price(text)
    discount = find_discount(text)
    brand = find_brand(text)
    sizes = normalize_sizes(text)

    if price is None:

        return (
            "⚠️ Не вдалося знайти ціну."
        )

    if discount is None:

        return (
            "⚠️ Не вдалося знайти знижку."
        )

    if not brand:

        brand = "brand"

    # Мінус 10 процентних пунктів
    new_discount = max(
        discount - 10,
        0,
    )

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


# -------------------------------------------------
# SEND SINGLE MEDIA
# -------------------------------------------------

async def send_single_media(
    message,
    caption,
):

    if message.photo:

        await message.reply_photo(
            photo=message.photo[-1].file_id,
            caption=caption,
            parse_mode="HTML",
        )

    elif message.video:

        await message.reply_video(
            video=message.video.file_id,
            caption=caption,
            parse_mode="HTML",
        )


# -------------------------------------------------
# SEND MEDIA GROUP
# -------------------------------------------------

async def send_media_group(
    message,
    messages,
):

    media = []

    caption_added = False

    for item in messages:

        # Фото
        if item.photo:

            file_id = item.photo[-1].file_id

            if not caption_added:

                media.append(
                    InputMediaPhoto(
                        media=file_id,
                        caption=create_caption(
                            item.caption or ""
                        ),
                        parse_mode="HTML",
                    )
                )

                caption_added = True

            else:

                media.append(
                    InputMediaPhoto(
                        media=file_id,
                    )
                )

        # Відео
        elif item.video:

            file_id = item.video.file_id

            if not caption_added:

                media.append(
                    InputMediaVideo(
                        media=file_id,
                        caption=create_caption(
                            item.caption or ""
                        ),
                        parse_mode="HTML",
                    )
                )

                caption_added = True

            else:

                media.append(
                    InputMediaVideo(
                        media=file_id,
                    )
                )

    if media:

        # Telegram дозволяє максимум 10
        # фото/відео в одному media group
        for i in range(
            0,
            len(media),
            10,
        ):

            chunk = media[i:i + 10]

            await message.reply_media_group(
                media=chunk,
            )


# -------------------------------------------------
# PROCESS ALBUM
# -------------------------------------------------

async def process_media_group(
    media_group_id,
    message,
    context,
):

    await asyncio.sleep(1.5)

    group = media_groups.pop(
        media_group_id,
        [],
    )

    if not group:
        return

    # Сортуємо за message_id,
    # щоб зберегти порядок
    group.sort(
        key=lambda x: x.message_id
    )

    await send_media_group(
        message,
        group,
    )


# -------------------------------------------------
# HANDLE MESSAGE
# -------------------------------------------------

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.message

    if not message:
        return

    # ---------------------------------------------
    # АЛЬБОМ
    # ---------------------------------------------

    if message.media_group_id:

        group_id = message.media_group_id

        if group_id not in media_groups:

            media_groups[group_id] = []

        media_groups[group_id].append(
            message
        )

        # Запускаємо обробку тільки один раз
        if len(media_groups[group_id]) == 1:

            asyncio.create_task(
                process_media_group(
                    group_id,
                    message,
                    context,
                )
            )

        return

    # ---------------------------------------------
    # ОДНЕ ФОТО / ВІДЕО
    # ---------------------------------------------

    if message.photo or message.video:

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

        await send_single_media(
            message,
            caption,
        )

        return

    # ---------------------------------------------
    # ЗВИЧАЙНИЙ ТЕКСТ
    # ---------------------------------------------

    if message.text:

        caption = create_caption(
            message.text
        )

        await message.reply_text(
            caption,
            parse_mode="HTML",
        )


# -------------------------------------------------
# START BOT
# -------------------------------------------------

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
