import os
import re
import random
import sqlite3
import asyncio
import logging
import time

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# ------------------ LOGGING ------------------
logging.basicConfig(level=logging.INFO)
logging.info("🚀 bot.py started")

# ------------------ TOKEN ------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

# ------------------ BOT ------------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ------------------ /start ------------------
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("✅ Бот жив. Рейтинг работает.")

# ------------------ DATABASE (VOLUME) ------------------
conn = sqlite3.connect("/data/ratings.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS ratings (
    chat_id INTEGER,
    user_id INTEGER,
    rating INTEGER,
    PRIMARY KEY (chat_id, user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS cooldowns (
    chat_id INTEGER,
    voter_id INTEGER,
    last_time INTEGER,
    PRIMARY KEY (chat_id, voter_id)
)
""")

conn.commit()

# ------------------ RATING LOGIC ------------------
def change_rating(chat_id: int, user_id: int, delta: int) -> int:
    cursor.execute(
        "SELECT rating FROM ratings WHERE chat_id=? AND user_id=?",
        (chat_id, user_id)
    )
    row = cursor.fetchone()

    if row is None:
        rating = delta
        cursor.execute(
            "INSERT INTO ratings VALUES (?, ?, ?)",
            (chat_id, user_id, rating)
        )
    else:
        rating = row[0] + delta
        cursor.execute(
            "UPDATE ratings SET rating=? WHERE chat_id=? AND user_id=?",
            (rating, chat_id, user_id)
        )

    conn.commit()
    return rating

# ------------------ EMOJIS ------------------
POSITIVE = ["😎", "🔥", "💪", "🚀", "✨", "😁", "👏"]
NEGATIVE = ["😡", "💀", "🤡", "👎", "😬", "🥶"]

# ------------------ PARSER ------------------
RATING_PATTERN = re.compile(r"([+-])\s*(\d{1,3})")
COOLDOWN_SECONDS = 300  # 5 минут

@dp.message()
async def rating_handler(message: types.Message):
    # ❗ ТОЛЬКО reply
    if not message.reply_to_message:
        return

    if not message.text:
        return

    match = RATING_PATTERN.search(message.text)
    if not match:
        return

    sign, amount_str = match.groups()
    amount = int(amount_str)

    if not 1 <= amount <= 100:
        await message.reply("Можно менять рейтинг только от 1 до 100 😎")
        return

    voter = message.from_user
    target = message.reply_to_message.from_user

    if voter.id == target.id:
        await message.reply("Сам себе рейтинг крутить нельзя 😏")
        return

    # ---------- COOLDOWN ----------
    now = int(time.time())
    cursor.execute(
        "SELECT last_time FROM cooldowns WHERE chat_id=? AND voter_id=?",
        (message.chat.id, voter.id)
    )
    row = cursor.fetchone()

    if row and now - row[0] < COOLDOWN_SECONDS:
        wait = COOLDOWN_SECONDS - (now - row[0])
        await message.reply(f"⏳ Подожди {wait} сек перед следующим голосом")
        return

    cursor.execute(
        "REPLACE INTO cooldowns VALUES (?, ?, ?)",
        (message.chat.id, voter.id, now)
    )
    conn.commit()
    # ------------------------------

    delta = amount if sign == "+" else -amount
    new_rating = change_rating(message.chat.id, target.id, delta)

    emoji = random.choice(POSITIVE if delta > 0 else NEGATIVE)
    delta_text = f"+{amount}" if delta > 0 else f"-{amount}"

   await message.answer(
        f"👤 {voter_name} изменил рейтинг {target_name} {delta_text}\n"
        f"🏆 Общий рейтинг {target_name} в чате НОСА: {new_rating} {emoji}"
    )

# ------------------ /rating ------------------
@dp.message(Command("rating"))
async def show_rating(message: types.Message):
    cursor.execute(
        "SELECT user_id, rating FROM ratings WHERE chat_id=? ORDER BY rating DESC",
        (message.chat.id,)
    )
    rows = cursor.fetchall()

    if not rows:
        await message.answer("📊 В чате пока нет рейтингов")
        return

    text = "🏆 Рейтинг чата:\n\n"
    for i, (user_id, rating) in enumerate(rows, start=1):
        try:
            member = await bot.get_chat_member(message.chat.id, user_id)
            name = member.user.first_name
        except:
            name = "Пользователь"

        text += f"{i}. {name} — {rating}\n"

    await message.answer(text)

# ------------------ RUN ------------------
async def main():
    logging.info("🤖 starting polling")
    await dp.start_polling(bot, allowed_updates=["message"])

if __name__ == "__main__":
    asyncio.run(main())


