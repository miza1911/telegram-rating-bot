import os
import re
import random
import sqlite3
import asyncio
import logging
import time
from datetime import datetime

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

# ------------------ DATABASE ------------------
conn = sqlite3.connect("ratings.db")
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
CREATE TABLE IF NOT EXISTS actions (
    chat_id INTEGER,
    voter_id INTEGER,
    type TEXT,
    amount INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_negative (
    chat_id INTEGER,
    user_id INTEGER,
    date TEXT,
    total INTEGER,
    announced INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id, date)
)
""")

conn.commit()

# ------------------ CONSTANTS ------------------
RATING_PATTERN = re.compile(r"([+-])\s*(\d{1,3})")
NEGATIVE_LIMIT = 500

POSITIVE_EMOJI = ["😎", "🔥", "💪", "🚀", "✨", "😁", "👏"]
NEGATIVE_EMOJI = ["😡", "💀", "🤡", "👎", "😬", "🥶"]

SHAME_EMOJI = ["🪦", "🚨", "💀", "🤡", "👎", "😬", "🧻"]

SHAME_JOKES = [
    "Чат в шоке.",
    "Это уже диагноз.",
    "Так даже враги не делают.",
    "Рекорд, но со знаком минус.",
    "История будет помнить.",
    "Соболезнуем.",
    "Никто не ожидал, но все знали.",
    "Сегодня не твой день.",
    "Интернет всё помнит.",
    "Даже клавиатура плачет.",
    "Это было больно.",
    "Минус за минусом.",
    "Чат напрягся.",
    "Без комментариев.",
    "Лучше бы молчал.",
    "Остановись.",
    "Это фиаско.",
    "Поздравляем, ты смог.",
    "Такое не отмывается.",
    "Мама, я в телевизоре."
]

# ------------------ HELPERS ------------------
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


def today():
    return datetime.utcnow().strftime("%Y-%m-%d")

# ------------------ COMMANDS ------------------
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("✅ Бот жив. Рейтинг считается.")


@dp.message(Command("rating"))
async def rating(message: types.Message):
    cursor.execute(
        "SELECT user_id, rating FROM ratings WHERE chat_id=? ORDER BY rating DESC",
        (message.chat.id,)
    )
    rows = cursor.fetchall()

    if not rows:
        await message.answer("📊 В чате пока нет рейтинга")
        return

    text = "🏆 **Рейтинг чата:**\n\n"
    for i, (uid, rating) in enumerate(rows, 1):
        try:
            member = await bot.get_chat_member(message.chat.id, uid)
            name = member.user.first_name
        except:
            name = "Пользователь"
        text += f"{i}. {name} — {rating}\n"

    await message.answer(text)


@dp.message(Command("top_plus"))
async def top_plus(message: types.Message):
    cursor.execute("""
        SELECT voter_id, SUM(amount) FROM actions
        WHERE chat_id=? AND type='plus'
        GROUP BY voter_id
        ORDER BY SUM(amount) DESC
        LIMIT 5
    """, (message.chat.id,))
    rows = cursor.fetchall()

    if not rows:
        await message.answer("😇 Пока никто не ставил плюсы")
        return

    text = "💖 **Самые добрые:**\n\n"
    for i, (uid, total) in enumerate(rows, 1):
        try:
            member = await bot.get_chat_member(message.chat.id, uid)
            name = member.user.first_name
        except:
            name = "Пользователь"
        text += f"{i}. {name} — +{total}\n"

    await message.answer(text)


@dp.message(Command("top_minus"))
async def top_minus(message: types.Message):
    cursor.execute("""
        SELECT voter_id, SUM(amount) FROM actions
        WHERE chat_id=? AND type='minus'
        GROUP BY voter_id
        ORDER BY SUM(amount) DESC
        LIMIT 5
    """, (message.chat.id,))
    rows = cursor.fetchall()

    if not rows:
        await message.answer("😇 Пока никто не ставил минусы")
        return

    text = "💀 **Главные хейтеры:**\n\n"
    for i, (uid, total) in enumerate(rows, 1):
        try:
            member = await bot.get_chat_member(message.chat.id, uid)
            name = member.user.first_name
        except:
            name = "Пользователь"
        text += f"{i}. {name} — −{total}\n"

    await message.answer(text)

# ------------------ RATING HANDLER ------------------
@dp.message()
async def rating_handler(message: types.Message):
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
        return

    voter = message.from_user
    target = message.reply_to_message.from_user

    if not target or voter.id == target.id:
        return

    delta = amount if sign == "+" else -amount
    change_rating(message.chat.id, target.id, delta)

    cursor.execute(
        "INSERT INTO actions VALUES (?, ?, ?, ?)",
        (message.chat.id, voter.id, "plus" if delta > 0 else "minus", amount)
    )

    # ---- DAILY SHAME ----
    if delta < 0:
        d = today()
        cursor.execute("""
            SELECT total, announced FROM daily_negative
            WHERE chat_id=? AND user_id=? AND date=?
        """, (message.chat.id, target.id, d))
        row = cursor.fetchone()

        total = amount
        announced = 0

        if row:
            total += row[0]
            announced = row[1]

            cursor.execute("""
                UPDATE daily_negative SET total=?
                WHERE chat_id=? AND user_id=? AND date=?
            """, (total, message.chat.id, target.id, d))
        else:
            cursor.execute("""
                INSERT INTO daily_negative VALUES (?, ?, ?, ?, 0)
            """, (message.chat.id, target.id, d, total))

        if total >= NEGATIVE_LIMIT and not announced:
            joke = random.choice(SHAME_JOKES)
            emoji = random.choice(SHAME_EMOJI)

            await message.answer(
                f"{emoji} **ПОЗОР ДНЯ** {emoji}\n"
                f"{target.first_name} получил −{total} за сутки.\n"
                f"{joke}"
            )

            cursor.execute("""
                UPDATE daily_negative SET announced=1
                WHERE chat_id=? AND user_id=? AND date=?
            """, (message.chat.id, target.id, d))

    conn.commit()

# ------------------ RUN ------------------
async def main():
    logging.info("🤖 starting polling")
    await dp.start_polling(bot, allowed_updates=["message"])

if __name__ == "__main__":
    asyncio.run(main())
