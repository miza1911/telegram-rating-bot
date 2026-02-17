import os
import re
import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------------- DATABASE ----------------
conn = sqlite3.connect("ratings.db", check_same_thread=False)
cursor = conn.cursor()

cursor.executescript("""
CREATE TABLE IF NOT EXISTS ratings (
    chat_id INTEGER,
    user_id INTEGER,
    rating INTEGER,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS actions (
    chat_id INTEGER,
    user_id INTEGER,
    amount INTEGER,
    ts INTEGER
);
""")
conn.commit()

# ---------------- REGEX ----------------
LAUGH_REGEX = re.compile(r"(ору+)|(ах)+", re.IGNORECASE)
PLUS_REGEX = re.compile(r"\+\s*(\d*)")

# ---------------- HELPERS ----------------
def change_rating(chat_id, user_id, delta):
    cursor.execute(
        "INSERT INTO ratings VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET rating = rating + ?",
        (chat_id, user_id, delta, delta)
    )

    cursor.execute(
        "INSERT INTO actions VALUES (?, ?, ?, ?)",
        (chat_id, user_id, delta, int(datetime.utcnow().timestamp()))
    )

    conn.commit()

def get_name(chat_id, uid):
    try:
        return uid
    except:
        return "user"

# ---------------- COMMANDS ----------------
@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer("Социальный рейтинг активен 😈")

@dp.message(Command("me"))
async def me(m: types.Message):
    cursor.execute(
        "SELECT rating FROM ratings WHERE chat_id=? AND user_id=?",
        (m.chat.id, m.from_user.id)
    )
    row = cursor.fetchone()
    rating = row[0] if row else 0

    await m.answer(f"⭐ Твой рейтинг: {rating}")

# ---------------- REPLY RATING ----------------
@dp.message()
async def reply_rating(m: types.Message):

    if not m.reply_to_message or not m.text:
        return

    author = m.reply_to_message.from_user
    voter = m.from_user

    if not author or author.id == voter.id:
        return

    text = m.text.lower()
    score = 0

    # ищем +баллы
    matches = PLUS_REGEX.findall(text)
    for match in matches:
        score += int(match) if match else 1

    # смех
    if LAUGH_REGEX.search(text):
        score += 50

    # максимум за сообщение
    if score > 100:
        score = 100

    if score <= 0:
        return

    change_rating(m.chat.id, author.id, score)
    logging.info(f"{voter.id} gave +{score} to {author.id}")

# ---------------- TOP DAY ----------------
@dp.message(Command("top"))
async def top_today(m: types.Message):

    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    ts = int(start.timestamp())

    cursor.execute("""
        SELECT user_id, SUM(amount)
        FROM actions
        WHERE chat_id=? AND ts>=?
        GROUP BY user_id
        ORDER BY SUM(amount) DESC
        LIMIT 10
    """, (m.chat.id, ts))

    rows = cursor.fetchall()

    if not rows:
        await m.answer("Сегодня активности нет")
        return

    text = "Социальный рейтинг дня в чате носа(2)\n\n"
    medals = ["🥇","🥈","🥉"]

    for i, (uid, score) in enumerate(rows, 1):
        try:
            member = await bot.get_chat_member(m.chat.id, uid)
            name = member.user.first_name
        except:
            name = "user"

        prefix = medals[i-1] if i <= 3 else f"{i}."
        text += f"{prefix} {name:<10} +{score}\n"

    await m.answer(f"<pre>{text}</pre>", parse_mode="HTML")

# ---------------- TOP WEEK ----------------
@dp.message(Command("topw"))
async def top_week(m: types.Message):

    start = datetime.utcnow() - timedelta(days=7)
    ts = int(start.timestamp())

    cursor.execute("""
        SELECT user_id, SUM(amount)
        FROM actions
        WHERE chat_id=? AND ts>=?
        GROUP BY user_id
        ORDER BY SUM(amount) DESC
        LIMIT 10
    """, (m.chat.id, ts))

    rows = cursor.fetchall()

    if not rows:
        await m.answer("За неделю активности нет")
        return

    text = "Социальный рейтинг недели в чате носа(2)\n\n"
    medals = ["🥇","🥈","🥉"]

    for i, (uid, score) in enumerate(rows, 1):
        try:
            member = await bot.get_chat_member(m.chat.id, uid)
            name = member.user.first_name
        except:
            name = "user"

        prefix = medals[i-1] if i <= 3 else f"{i}."
        text += f"{prefix} {name:<10} +{score}\n"

    await m.answer(f"<pre>{text}</pre>", parse_mode="HTML")

# ---------------- RUN ----------------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
