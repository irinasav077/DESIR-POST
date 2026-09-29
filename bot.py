import os
import re
import asyncio
import logging
import time
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
# Альбоми:
# (chat_id, media_group_id) -> messages
albums = {}
# Таймери альбомів
album_tasks = {}
# Окремий текст, який може прийти разом з альбомом
# chat_id -> [(message, timestamp)]
pending_text = {}
# =========================================================
# PRICE
# =========================================================
def parse_price(value):
    """
    650      -> 650
    650.50   -> 650.5
    3.500    -> 3500
    3,500    -> 3500
    12.500   -> 12500
    12,500   -> 12500
    """
    value = value.strip()
    # Якщо є і крапка/кома, і рівно 3 цифри після неї,
    # це сприймаємо як розділювач тисяч:
    #
    # 3.500 -> 3500
    # 3,500 -> 3500
    #
    # Якщо після розділювача не 3 цифри,
    # тоді це десяткове число.
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
    value = value.replace(
        ",",
        ".",
    )
    return float(value)
def find_price(text):
    # Наприклад:
    # 650€
    # 650 €
    # 650-25%
    # 650 -25%
    # 650€. -20%
    # 3.500€
    # 3,500€
    # 3.500-25%
    # 3,500-25%
    patterns = [
        # Ціна з €
        r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s*€",
        # Ціна перед знижкою
        r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s*€?\s*[-–—]\s*\d+\s*%",
    ]
    for pattern in patterns:
        match = re.search(
            pattern,
            text,
        )
        if match:
            return parse_price(
                match.group(1)
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
    # Прибираємо emoji
    brand = re.sub(
        r"[^a-zа-яіїєґ0-9\s&'-]",
        "",
        brand,
    )
    # Прибираємо &
    brand = brand.replace(
        "&",
        "",
    )
    # Прибираємо апострофи
    brand = brand.replace(
        "'",
        "",
    )
    # Прибираємо пробіли та дефіси
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
    # Потім шукаємо назву бренду
    for line in lines:
        # Не бренд, якщо це ціна
        if re.search(
            r"\d+\s*€",
            line,
        ):
            continue
        # Не бренд, якщо це знижка
        if re.search(
            r"\d+\s*%",
            line,
        ):
            continue
        # Не бренд, якщо тільки цифри
        if re.fullmatch(
            r"[\d\s./,-]+",
            line,
        ):
            continue
        # Не бренд, якщо це розміри
        if is_size_line(line):
            continue
        # Не бренд, якщо це FW / NEW / SALE
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
    # S M L XL
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
    # Числові розміри
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
    # 1. БУКВЕНІ РОЗМІРИ
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
    # 2. ЧИСЛОВІ РОЗМІРИ
    # -----------------------------------------------------
    for line in lines:
        # Не чіпаємо рядок зі знижкою
        if re.search(
            r"\d+\s*%",
            line,
        ):
            continue
        # Не чіпаємо рядок з €
        if "€" in line:
            continue
        numbers = re.findall(
            r"\d+(?:[.,]\d+)?",
            line,
        )
        if not numbers:
            continue
        # Якщо це просто "2" —
        # це не розмір
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
        # Перевіряємо, що крім чисел
        # немає стороннього тексту
        cleaned = re.sub(
            r"\d+(?:[.,]\d+)?",
            "",
            line,
        )
        cleaned = re.sub(
            r"[\s/;:,.+\-]+",
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
    # Зменшуємо знижку
    # на 10 процентних пунктів
    new_discount = max(
        discount - 10,
        0,
    )
    # Рахуємо кінцеву ціну
    new_price = round(
        price * (
            1 - new_discount / 100
        )
    )
    # Для 3500 не показуємо .0
    price_text = f"{price:g}"
    return (
        f"<i>#{brand}</i>\n"
        f"<i>{sizes}</i>\n\n"
        f"<i>🏷️{price_text}€-%={new_price}€</i>\n"
        f"<i>+ доставка 📦</i>\n\n"
        f"<i>Для консультації та замовлення:</i>\n"
        f"<i>💌@irasavchenkoo</i>"
    )
# =========================================================
# SINGLE PHOTO
# =========================================================
async def handle_photo(
    message,
):
    text = message.caption or ""
    if not text:
        await message.reply_text(
            "⚠️ Не знайшов текст для обробки."
        )
        return
    caption = create_caption(
        text
    )
    photo_file_id = (
        message.photo[-1].file_id
    )
    await message.reply_photo(
        photo=photo_file_id,
        caption=caption,
        parse_mode="HTML",
    )
# =========================================================
# SINGLE VIDEO
# =========================================================
async def handle_video(
    message,
):
    text = message.caption or ""
    if not text:
        await message.reply_text(
            "⚠️ Не знайшов текст для обробки."
        )
        return
    caption = create_caption(
        text
    )
    await message.reply_video(
        video=message.video.file_id,
        caption=caption,
        parse_mode="HTML",
    )
# =========================================================
# CLEAN OLD TEXT
# =========================================================
def get_pending_text(
    chat_id,
):
    items = pending_text.get(
        chat_id,
        [],
    )
    if not items:
        return ""
    now = time.time()
    # Залишаємо тільки текст,
    # який прийшов за останні 15 секунд
    fresh = [
        item
        for item in items
        if now - item[1] <= 15
    ]
    pending_text[chat_id] = fresh
    if not fresh:
        return ""
    # Беремо останній текст
    return fresh[-1][0].text or ""
# =========================================================
# ALBUM
# =========================================================
async def process_album(
    chat_id,
    group_id,
):
    key = (
        chat_id,
        group_id,
    )
    # Чекаємо 10 секунд,
    # щоб Telegram встиг передати
    # весь альбом + окремий текст
    await asyncio.sleep(10)
    messages = albums.pop(
        key,
        [],
    )
    album_tasks.pop(
        key,
        None,
    )
    if not messages:
        return
    # Правильний порядок
    messages.sort(
        key=lambda m: m.message_id
    )
    # -----------------------------------------------------
    # ШУКАЄМО CAPTION ВСЕРЕДИНІ АЛЬБОМУ
    # -----------------------------------------------------
    source_text = ""
    for message in messages:
        if message.caption:
            source_text = message.caption
            break
    # -----------------------------------------------------
    # ЯКЩО CAPTION НЕМАЄ —
    # ШУКАЄМО ОКРЕМИЙ ТЕКСТ
    # -----------------------------------------------------
    if not source_text:
        source_text = get_pending_text(
            chat_id
        )
    if not source_text:
        await messages[0].reply_text(
            "⚠️ Не знайшов текст для обробки."
        )
        return
    caption = create_caption(
        source_text
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
    # Telegram: максимум 10 елементів
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
    # -----------------------------------------------------
    # АЛЬБОМ
    # -----------------------------------------------------
    if message.media_group_id:
        group_id = message.media_group_id
        key = (
            chat_id,
            group_id,
        )
        if key not in albums:
            albums[key] = []
        albums[key].append(
            message
        )
        # Якщо вже був таймер —
        # скасовуємо його і запускаємо
        # новий, щоб дочекатися всіх елементів
        old_task = album_tasks.get(
            key
        )
        if old_task:
            old_task.cancel()
        album_tasks[key] = asyncio.create_task(
            process_album(
                chat_id,
                group_id,
            )
        )
        return
    # -----------------------------------------------------
    # ОДНЕ ФОТО
    # -----------------------------------------------------
    if message.photo:
        await handle_photo(
            message
        )
        return
    # -----------------------------------------------------
    # ОДНЕ ВІДЕО
    # -----------------------------------------------------
    if message.video:
        await handle_video(
            message
        )
        return
    # -----------------------------------------------------
    # ТЕКСТ
    # -----------------------------------------------------
    if message.text:
        # Якщо в цьому чаті зараз збирається
        # альбом — не обробляємо текст окремо.
        #
        # Зберігаємо його, щоб process_album()
        # використав його як caption.
        active_album = any(
            key[0] == chat_id
            for key in albums.keys()
        )
        if active_album:
            if chat_id not in pending_text:
                pending_text[chat_id] = []
            pending_text[chat_id].append(
                (
                    message,
                    time.time(),
                )
            )
            return
        # Звичайний окремий текст
        caption = create_caption(
            message.text
        )
        await message.reply_text(
            caption,
            parse_mode="HTML",
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
