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
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# BOT TOKEN
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")


# =========================================================
# SETTINGS
# =========================================================

# Скільки секунд чекати текст після медіа
TEXT_WAIT_SECONDS = 3


# =========================================================
# STORAGE
# =========================================================

# Альбоми, які зараз збираються
albums = {}

# Окремі фото/відео, які чекають наступного текстового повідомлення
pending_media = {}


# =========================================================
# PRICE
# =========================================================

def find_price(text):

    patterns = [

        # -------------------------------------------------
        # 3.600 € / 3,600 €
        # 36.000 € / 36,000 €
        # -------------------------------------------------

        r"(\d{1,3}(?:[.,]\d{3})+)\s*€",

        # -------------------------------------------------
        # 3600 € / 3600€
        # 999.99 € / 999,99 €
        # -------------------------------------------------

        r"(\d+(?:[.,]\d+)?)\s*€",

        # -------------------------------------------------
        # 3.600 - 20%
        # 3600 - 20%
        # -------------------------------------------------

        r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s*[-–—]\s*\d+\s*%",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
        )

        if not match:
            continue

        value = match.group(1)

        # -------------------------------------------------
        # Якщо це роздільник тисяч:
        #
        # 3.600 → 3600
        # 3,600 → 3600
        # 12.500 → 12500
        # -------------------------------------------------

        if re.fullmatch(
            r"\d{1,3}(?:[.,]\d{3})+",
            value,
        ):

            value = re.sub(
                r"[.,]",
                "",
                value,
            )

            return float(value)

        # -------------------------------------------------
        # Якщо це звичайне десяткове число:
        #
        # 999.99 → 999.99
        # 999,99 → 999.99
        # -------------------------------------------------

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

    # -----------------------------------------------------
    # Hashtag
    # -----------------------------------------------------

    for line in lines:

        if line.startswith("#"):

            return clean_brand(
                line.split()[0]
            )

    # -----------------------------------------------------
    # Назва бренду
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

    # -----------------------------------------------------
    # Літерні розміри
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Числові розміри
    # -----------------------------------------------------

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

        # Самотнє число менше 30
        # не вважаємо розміром
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
# CREATE CAPTION
# =========================================================

def create_caption(text):

    price = find_price(text)
    discount = find_discount(text)
    brand = find_brand(text)
    sizes = normalize_sizes(text)

    # -----------------------------------------------------
    # Якщо немає ціни
    # -----------------------------------------------------

    if price is None:

        return (
            "<i>⚠️ Не вдалося знайти ціну.</i>"
        )

    # -----------------------------------------------------
    # Якщо немає знижки
    # -----------------------------------------------------

    if discount is None:

        return (
            "<i>⚠️ Не вдалося знайти знижку.</i>"
        )

    # -----------------------------------------------------
    # Якщо бренд не знайдено
    # -----------------------------------------------------

    if not brand:

        brand = "brand"

    # -----------------------------------------------------
    # Твоя логіка:
    #
    # магазин дає X%
    # ми показуємо на 10% меншу знижку
    #
    # Наприклад:
    # 20% → 10%
    # 30% → 20%
    # -----------------------------------------------------

    new_discount = max(
        discount - 10,
        0,
    )

    # -----------------------------------------------------
    # Нова ціна
    # -----------------------------------------------------

    new_price = round(
        price * (
            1 - new_discount / 100
        )
    )

    # -----------------------------------------------------
    # Якщо розмірів немає,
    # не залишаємо порожній рядок
    # -----------------------------------------------------

    if sizes:

        size_line = (
            f"<i>{sizes}</i>\n\n"
        )

    else:

        size_line = "\n"

    return (
        f"<i>#{brand}</i>\n"
        f"{size_line}"
        f"<i>🏷️{price:g}€-{discount}%={new_price}€</i>\n"
        f"<i>+ доставка 📦</i>\n\n"
        f"<i>Для консультації та замовлення:</i>\n"
        f"<i>💌@irasavchenkoo</i>"
    )


# =========================================================
# CHECK MEDIA
# =========================================================

def is_media_message(message):

    return bool(
        message.photo
        or message.video
    )


# =========================================================
# BUILD MEDIA GROUP
# =========================================================

def build_media_group(
    messages,
    caption,
):

    media = []

    for index, message in enumerate(
        messages
    ):

        # -------------------------------------------------
        # PHOTO
        # -------------------------------------------------

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

        # -------------------------------------------------
        # VIDEO
        # -------------------------------------------------

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

    return media


# =========================================================
# SEND MEDIA GROUP
# =========================================================

async def send_media_group(
    messages,
    text,
):

    if not messages:
        return

    caption = create_caption(
        text
    )

    media = build_media_group(
        messages,
        caption,
    )

    if not media:
        return

    # Telegram дозволяє максимум 10
    # елементів в одному media group.
    #
    # Але залишаємо поділ на chunks,
    # щоб код був стабільним і для більших
    # альбомів.

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
# SEND SINGLE PHOTO
# =========================================================

async def send_single_photo(
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
# SEND SINGLE VIDEO
# =========================================================

async def send_single_video(
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
# WAIT FOR TEXT
# =========================================================

async def wait_for_text(
    user_id,
    pending_id,
):

    await asyncio.sleep(
        TEXT_WAIT_SECONDS
    )

    pending = pending_media.get(
        user_id
    )

    if not pending:
        return

    # -----------------------------------------------------
    # Перевіряємо, що це саме той pending
    # -----------------------------------------------------

    if pending["id"] != pending_id:
        return

    # -----------------------------------------------------
    # Видаляємо очікування
    # -----------------------------------------------------

    pending_media.pop(
        user_id,
        None,
    )

    # -----------------------------------------------------
    # Якщо текст так і не прийшов
    # -----------------------------------------------------

    try:

        await pending["message"].reply_text(
            "⚠️ Не знайшов текст із брендом, ціною та знижкою."
        )

    except Exception as error:

        logger.error(
            "Error sending waiting message: %s",
            error,
        )


# =========================================================
# PROCESS SINGLE MEDIA
# =========================================================

async def process_single_media(
    message,
):

    user_id = message.from_user.id

    # -----------------------------------------------------
    # Якщо caption вже є
    # -----------------------------------------------------

    if message.caption:

        if message.photo:

            await send_single_photo(
                message,
                message.caption,
            )

            return

        if message.video:

            await send_single_video(
                message,
                message.caption,
            )

            return

    # -----------------------------------------------------
    # Caption немає.
    # Чекаємо наступне текстове повідомлення.
    # -----------------------------------------------------

    pending_id = (
        f"{message.chat_id}:"
        f"{message.message_id}"
    )

    pending_media[user_id] = {
        "id": pending_id,
        "type": "single",
        "message": message,
    }

    asyncio.create_task(
        wait_for_text(
            user_id,
            pending_id,
        )
    )


# =========================================================
# PROCESS ALBUM
# =========================================================

async def process_album(
    group_id,
):

    # -----------------------------------------------------
    # Чекаємо, поки Telegram передасть
    # всі повідомлення альбому.
    # -----------------------------------------------------

    await asyncio.sleep(
        1
    )

    messages = albums.pop(
        group_id,
        [],
    )

    if not messages:
        return

    # -----------------------------------------------------
    # Сортуємо за message_id
    # -----------------------------------------------------

    messages.sort(
        key=lambda message:
        message.message_id
    )

    # -----------------------------------------------------
    # Шукаємо caption
    # -----------------------------------------------------

    source_text = ""

    for message in messages:

        if message.caption:

            source_text = message.caption

            break

    # -----------------------------------------------------
    # Якщо caption є
    # -----------------------------------------------------

    if source_text:

        await send_media_group(
            messages,
            source_text,
        )

        return

    # -----------------------------------------------------
    # Якщо caption немає —
    # чекаємо окремий текст.
    # -----------------------------------------------------

    first_message = messages[0]

    user_id = first_message.from_user.id

    pending_id = (
        f"{first_message.chat_id}:"
        f"{group_id}"
    )

    pending_media[user_id] = {
        "id": pending_id,
        "type": "album",
        "messages": messages,
        "message": first_message,
    }

    asyncio.create_task(
        wait_for_text(
            user_id,
            pending_id,
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

        # -------------------------------------------------
        # Якщо є медіа, яке чекає текст
        # -------------------------------------------------

        if pending:

            pending_media.pop(
                user_id,
                None,
            )

            text = message.text

            # ---------------------------------------------
            # SINGLE PHOTO / VIDEO
            # ---------------------------------------------

            if pending["type"] == "single":

                source_message = (
                    pending["message"]
                )

                if source_message.photo:

                    await send_single_photo(
                        source_message,
                        text,
                    )

                    return

                if source_message.video:

                    await send_single_video(
                        source_message,
                        text,
                    )

                    return

            # ---------------------------------------------
            # ALBUM
            # ---------------------------------------------

            if pending["type"] == "album":

                await send_media_group(
                    pending["messages"],
                    text,
                )

                return

        # -------------------------------------------------
        # Звичайний текст БЕЗ медіа
        #
        # Нічого не робимо.
        # -------------------------------------------------

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

        # -------------------------------------------------
        # Запускаємо process_album тільки
        # для першого повідомлення альбому.
        # -------------------------------------------------

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

        await process_single_media(
            message
        )

        return

    # =====================================================
    # SINGLE VIDEO
    # =====================================================

    if message.video:

        await process_single_media(
            message
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

    # -----------------------------------------------------
    # Обробляємо:
    # - фото
    # - відео
    # - текст
    # -----------------------------------------------------

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


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
