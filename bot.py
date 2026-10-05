import os
import re
import asyncio
import logging

from telegram import (
    Update,
    InputMediaPhoto,
    InputMediaVideo,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

ALLOWED_USERS = [
    493563129
]

# =========================================================
# STORAGE
# =========================================================

albums = {}
pending_media = {}


# =========================================================
# PRICE
# =========================================================

def find_price(text):

    patterns = [
        # 1.200€ / 3.500€ / 1,200€
        r"(\d{1,3}(?:[.,]\d{3})+)\s*€",

        # 1200€ / 3500€ / 1200,50€
        r"(\d+(?:[.,]\d+)?)\s*€",

        # 1.200 - 20% / 3.500 - 30%
        r"(\d{1,3}(?:[.,]\d{3})+)\s*[-–—]\s*\d+\s*%",

        # 1200 - 20% / 3500 - 30%
        r"(\d+(?:[.,]\d+)?)\s*[-–—]\s*\d+\s*%",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
        )

        if match:

            value = match.group(1)

            # 1.200 / 3.500 / 1,200 → 1200 / 3500 / 1200
            if re.fullmatch(
                r"\d{1,3}(?:[.,]\d{3})+",
                value,
            ):

                value = re.sub(
                    r"[.,]",
                    "",
                    value,
                )

            else:

                value = value.replace(
                    ",",
                    ".",
                )

            return float(value)

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
# AUTO PRICE
# =========================================================

def calculate_auto_price(
    price,
    discount,
):

    # Якщо є знижка —
    # стара логіка: мінус 10 процентних пунктів

    if discount is not None:

        new_discount = max(
            discount - 10,
            0,
        )

        return round(
            price * (
                1 - new_discount / 100
            )
        )

    # Якщо знижки немає:
    # до 1000€ включно +100€
    # від 1001€ +15%

    if price <= 1000:

        return round(
            price + 100
        )

    return round(
        price * 1.15
    )


# =========================================================
# BUTTONS
# =========================================================

def price_keyboard(
    price,
    discount,
):

    discount_value = (
        str(discount)
        if discount is not None
        else "none"
    )

    price_value = str(
        round(price, 2)
    )

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "+100€",
                    callback_data=(
                        f"price|100|{price_value}|{discount_value}"
                    ),
                ),
                InlineKeyboardButton(
                    "+150€",
                    callback_data=(
                        f"price|150|{price_value}|{discount_value}"
                    ),
                ),
            ],
            [
                InlineKeyboardButton(
                    "+15%",
                    callback_data=(
                        f"price|15p|{price_value}|{discount_value}"
                    ),
                ),
                InlineKeyboardButton(
                    "+10%",
                    callback_data=(
                        f"price|10p|{price_value}|{discount_value}"
                    ),
                ),
            ],
            [
                InlineKeyboardButton(
                    "↩️ Авто",
                    callback_data=(
                        f"price|auto|{price_value}|{discount_value}"
                    ),
                ),
            ],
        ]
    )


# =========================================================
# CREATE CAPTION
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

    if not brand:

        brand = "brand"

    new_price = calculate_auto_price(
        price,
        discount,
    )

    # =====================================================
    # РЯДОК ЦІНИ
    # =====================================================

    if discount is not None:

        price_line = (
            f"<i>🏷️{price:g}€-%={new_price}€</i>"
        )

    else:

        price_line = (
            f"<i>🏷️{new_price}€</i>"
        )

    return (
        f"<i>#{brand}</i>\n"
        f"<i>{sizes}</i>\n\n"
        f"{price_line}\n"
        f"<i>+ доставка 📦</i>\n\n"
        f"<i>Для консультації та замовлення:</i>\n"
        f"<i>💌@irasavchenkoo</i>"
    )


# =========================================================
# GET PRICE INFO
# =========================================================

def get_price_info(text):

    price = find_price(text)
    discount = find_discount(text)

    return price, discount


# =========================================================
# REPLACE PRICE IN CAPTION
# =========================================================

def replace_price_in_caption(
    caption,
    new_price,
):

    # Telegram повертає message.caption
    # БЕЗ HTML-тегів <i>...</i>.
    #
    # Тому шукаємо просто рядок,
    # який починається з 🏷️
    # і закінчується перед переносом рядка.

    pattern = r"🏷️[^\n]*"

    replacement = (
        f"🏷️{new_price}€"
    )

    return re.sub(
        pattern,
        replacement,
        caption,
        count=1,
    )


# =========================================================
# CALLBACK BUTTONS
# =========================================================

async def handle_price_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    user_id = query.from_user.id

    if user_id not in ALLOWED_USERS:
        await query.answer()
        return

    data = query.data

    if not data:
        await query.answer()
        return

    if not data.startswith(
        "price|"
    ):
        await query.answer()
        return

    parts = data.split("|")

    if len(parts) != 4:
        await query.answer(
            "Помилка даних кнопки."
        )
        return

    action = parts[1]

    try:

        price = float(
            parts[2]
        )

    except ValueError:

        await query.answer(
            "Помилка ціни."
        )
        return

    discount_text = parts[3]

    if discount_text == "none":

        discount = None

    else:

        try:

            discount = int(
                discount_text
            )

        except ValueError:

            discount = None

    # =====================================================
    # РОЗРАХУНОК
    # =====================================================

    if action == "auto":

        new_price = calculate_auto_price(
            price,
            discount,
        )

    elif action == "100":

        new_price = round(
            price + 100
        )

    elif action == "150":

        new_price = round(
            price + 150
        )

    elif action == "15p":

        new_price = round(
            price * 1.15
        )

    elif action == "10p":

        new_price = round(
            price * 1.10
        )

    else:

        await query.answer(
            "Невідома кнопка."
        )
        return

    message = query.message

    if not message:

        await query.answer()
        return

    # =====================================================
    # ОНОВЛЮЄМО CAPTION
    # =====================================================

    if message.caption:

        new_caption = replace_price_in_caption(
            message.caption,
            new_price,
        )

        try:

            await message.edit_caption(
                caption=new_caption,
                parse_mode="HTML",
                reply_markup=price_keyboard(
                    price,
                    discount,
                ),
            )

            await query.answer(
                f"Ціна: {new_price}€"
            )

        except Exception as error:

            logging.error(
                f"Caption edit error: {error}"
            )

            await query.answer(
                "Не вдалося змінити ціну."
            )

    # =====================================================
    # ТЕКСТОВЕ ПОВІДОМЛЕННЯ
    # =====================================================

    elif message.text:

        new_text = replace_price_in_caption(
            message.text,
            new_price,
        )

        try:

            await message.edit_text(
                text=new_text,
                parse_mode="HTML",
                reply_markup=price_keyboard(
                    price,
                    discount,
                ),
            )

            await query.answer(
                f"Ціна: {new_price}€"
            )

        except Exception as error:

            logging.error(
                f"Text edit error: {error}"
            )

            await query.answer(
                "Не вдалося змінити ціну."
            )

    else:

        await query.answer(
            "Не вдалося знайти підпис."
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

    price, discount = get_price_info(
        text
    )

    keyboard = None

    if price is not None:

        keyboard = price_keyboard(
            price,
            discount,
        )

    await message.reply_photo(
        photo=message.photo[-1].file_id,
        caption=caption,
        parse_mode="HTML",
        reply_markup=keyboard,
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

    price, discount = get_price_info(
        text
    )

    keyboard = None

    if price is not None:

        keyboard = price_keyboard(
            price,
            discount,
        )

    await message.reply_video(
        video=message.video.file_id,
        caption=caption,
        parse_mode="HTML",
        reply_markup=keyboard,
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
# ALBUM
# =========================================================

async def process_album(
    group_id,
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

    # Якщо caption немає —
    # чекаємо окреме текстове повідомлення

    if not source_text:

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

        return

    caption = create_caption(
        source_text
    )

    price, discount = get_price_info(
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

    sent_messages = []

    for start in range(
        0,
        len(media),
        10,
    ):

        chunk = media[
            start:start + 10
        ]

        result = await messages[0].reply_media_group(
            media=chunk
        )

        sent_messages.extend(
            result
        )

    # =====================================================
    # КНОПКИ ПІД ПЕРШИМ ФОТО АЛЬБОМУ
    # =====================================================

    if (
        sent_messages
        and price is not None
    ):

        try:

            await sent_messages[0].edit_caption(
                caption=caption,
                parse_mode="HTML",
                reply_markup=price_keyboard(
                    price,
                    discount,
                ),
            )

        except Exception as error:

            logging.error(
                f"Album button error: {error}"
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

    if user_id not in ALLOWED_USERS:
        return

    # =====================================================
    # ТЕКСТ ПІСЛЯ ФОТО / ВІДЕО / АЛЬБОМУ
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

            # -------------------------------------------------
            # Одне фото
            # -------------------------------------------------

            if pending["type"] == "photo":

                await send_photo(
                    pending["message"],
                    text,
                )

                return

            # -------------------------------------------------
            # Одне відео
            # -------------------------------------------------

            if pending["type"] == "video":

                await send_video(
                    pending["message"],
                    text,
                )

                return

            # -------------------------------------------------
            # Альбом
            # -------------------------------------------------

            if pending["type"] == "album":

                messages = pending[
                    "messages"
                ]

                caption = create_caption(
                    text
                )

                price, discount = get_price_info(
                    text
                )

                media = []

                for index, item in enumerate(
                    messages
                ):

                    if item.photo:

                        file_id = (
                            item.photo[-1].file_id
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

                    elif item.video:

                        file_id = (
                            item.video.file_id
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

                sent_messages = []

                for start in range(
                    0,
                    len(media),
                    10,
                ):

                    chunk = media[
                        start:start + 10
                    ]

                    result = await messages[0].reply_media_group(
                        media=chunk
                    )

                    sent_messages.extend(
                        result
                    )

                # Додаємо кнопки під першим фото

                if (
                    sent_messages
                    and price is not None
                ):

                    try:

                        await sent_messages[0].edit_caption(
                            caption=caption,
                            parse_mode="HTML",
                            reply_markup=price_keyboard(
                                price,
                                discount,
                            ),
                        )

                    except Exception as error:

                        logging.error(
                            f"Album button error: {error}"
                        )

                return

        # =================================================
        # Звичайний текст
        # =================================================

        caption = create_caption(
            message.text
        )

        price, discount = get_price_info(
            message.text
        )

        keyboard = None

        if price is not None:

            keyboard = price_keyboard(
                price,
                discount,
            )

        await message.reply_text(
            caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

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

        if len(
            albums[group_id]
        ) == 1:

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
        # працюємо одразу

        if message.caption:

            await send_photo(
                message,
                message.caption,
            )

            return

        # Якщо caption немає —
        # запам'ятовуємо фото

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

    # =====================================================
    # CALLBACK КНОПОК
    # =====================================================

    application.add_handler(
        CallbackQueryHandler(
            handle_price_button,
            pattern=r"^price\|",
        )
    )

    # =====================================================
    # ПОВІДОМЛЕННЯ
    # =====================================================

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
