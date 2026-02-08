import os
import re
import sqlite3
import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# ------------------ LOGGING ------------------
logging.basicConfig(level=logging.INFO)
logging.info("🚀 rofl-bot started")

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

cursor.executescript("""
CREATE TABLE IF NOT EXISTS ratings (
    chat_id INTEGER,
    user_id INTEGER,
    rating INTEGER,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS actions (
    chat_id INTEGER,
    from_id INTEGER,
    to_id INTEGER,
    amount INTEGER,
    ts INTEGER
);
""")
conn.commit()

# ------------------ CONSTANTS ------------------
MAX_PER_ACTION = 200
MINUS_PATTERN = re.compile(r"-\s*(\d{1,3})")

# ------------------ HELPERS ------------------
def change_rating(chat_id, user_id, delta):
    cursor.execute(
        "INSERT INTO ratings VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET rating = rating + ?",
        (chat_id, user_id, delta, delta)
    )
    conn.commit()

def log_action(chat_id, f, t, amt):
    cursor.execute(
        "INSERT INTO actions VALUES (?, ?, ?, ?, ?)",
        (chat_id, f, t, amt, int(datetime.utcnow().timestamp()))
    )
    conn.commit()

async def get_name(chat_id, user_id):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.user.first_name
    except:
        return "Пользователь"

# ------------------ COMMANDS ------------------
@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer(
        "😈 БОТ АКТИВЕН\n\n"
        "— считаются ТОЛЬКО минусы\n"
        "— плюсы игнорируются\n"
        "— минус ставится ТОЛЬКО реплаем\n\n"
        "Пример:  ахаха -10"
    )

@dp.message(Command("me"))
async def me(m: types.Message):
    cursor.execute(
        "SELECT rating FROM ratings WHERE chat_id=? AND user_id=?",
        (m.chat.id, m.from_user.id)
    )
    row = cursor.fetchone()
    rating = row[0] if row else 0

    cursor.execute(
        "SELECT COUNT(*) FROM actions WHERE chat_id=? AND to_id=?",
        (m.chat.id, m.from_user.id)
    )
    hits = cursor.fetchone()[0]

    await m.answer(
        f"📉 <b>Твоя статистика</b>\n\n"
        f"👤 {m.from_user.first_name}\n"
        f"💀 Минус-рейтинг: {rating}\n"
        f"🧾 Сколько раз минусовали: {hits}",
        parse_mode="HTML"
    )

@dp.message(Command("top"))
async def top(m: types.Message):
    cursor.execute(
        "SELECT user_id, rating FROM ratings "
        "WHERE chat_id=? ORDER BY rating ASC",
        (m.chat.id,)
    )
    rows = cursor.fetchall()

    if not rows:
        await m.answer("😇 Пока все чисты")
        return

    text = "🏴‍☠️ <b>Доска позора</b>\n\n"
    for i, (uid, r) in enumerate(rows, 1):
        name = await get_name(m.chat.id, uid)
        text += f"{i}. {name} — {r}\n"

    await m.answer(text, parse_mode="HTML")

# ------------------ RATING HANDLER ------------------
@dp.message()
async def rating_handler(m: types.Message):
    if not m.reply_to_message or not m.text:
        return

    match = MINUS_PATTERN.search(m.text)
    if not match:
        return  # плюсы и всё остальное игнорируем

    amount = int(match.group(1))
    if not 1 <= amount <= MAX_PER_ACTION:
        return

    voter = m.from_user
    target = m.reply_to_message.from_user

    if not target or voter.id == target.id:
        return

    delta = -amount

    change_rating(m.chat.id, target.id, delta)
    log_action(m.chat.id, voter.id, target.id, delta)

# ------------------ RUN ------------------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("🤖 polling started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
