import os
import re
import logging
from telegram import Update
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


def calculate_price(price, discount):
    new_discount = max(discount - 10, 0)
    new_price = round(price * (1 - new_discount / 100))
    return new_discount, new_price


def make_hashtag(brand):
    brand = brand.lower()
    brand = re.sub(r"[^a-zа-яіїєґ0-9]", "", brand)
    return f"#{brand}"


def create_caption(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    price_match = re.search(r"(\d+(?:[.,]\d+)?)\s*€", text)
    discount_match = re.search(r"-?\s*(\d+)\s*%", text)

    if not price_match:
        return "⚠️ Не вдалося знайти ціну в €."

    if not discount_match:
        return "⚠️ Не вдалося знайти знижку."

    price = float(price_match.group(1).replace(",", "."))
    discount = int(discount_match.group(1))

    # Поки беремо бренд із першого рядка
    brand = lines[0]

    # Шукаємо рядок із розмірами
    sizes = ""
    for line in lines:
        if re.search(r"\b(?:XXS|XS|S|M|L|XL|XXL|\d{2}(?:/\d{2})*)\b", line, re.I):
            if "€" not in line and "%" not in line:
                sizes = line
                break

    new_discount, new_price = calculate_price(price, discount)
    hashtag = make_hashtag(brand)

    caption = (
        f"{hashtag}\n"
        f"{sizes}\n\n"
        f"🏷️{price:g}€-%={new_price}€\n"
        f"+ доставка 📦\n\n"
        f"Для консультації та замовлення:\n"
        f"💌@irasavchenkoo"
    )

    return caption


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message

    if not message:
        return

    text = message.caption or message.text or ""

    if not text:
        await message.reply_text("⚠️ У повідомленні немає тексту для обробки.")
        return

    caption = create_caption(text)

    await message.reply_text(
        caption,
        parse_mode="Markdown"
    )


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(
        MessageHandler(
            filters.PHOTO | filters.VIDEO | filters.TEXT,
            handle_message
        )
    )

    print("DESIR bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
