import os
import re
import random
import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta

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

CREATE TABLE IF NOT EXISTS daily_balance (
    chat_id INTEGER,
    user_id INTEGER,
    plus_left INTEGER,
    minus_left INTEGER,
    warned INTEGER,
    date TEXT,
    PRIMARY KEY (chat_id, user_id)
);
""")
conn.commit()

# ------------------ CONSTANTS ------------------
DAILY_PLUS = 100
DAILY_MINUS = 50
SHAME_LIMIT = -500

RATING_PATTERN = re.compile(r"([+-])\s*(\d{1,3})")

LOW_PLUS_WARNINGS = [
    "⚠️ Плюсы на исходе",
    "💸 Осталось меньше 50 плюсов",
    "😬 Щедрость заканчивается",
    "📉 Плюсов почти нет",
    "🫣 Ты почти нищий по плюсам"
]

SHAME_JOKES = [
    "Интернет всё помнит.",
    "Чат в шоке.",
    "Это уже диагноз.",
    "Лучше бы промолчал.",
    "История запомнит этот день."
]

# ------------------ HELPERS ------------------
def today():
    return datetime.utcnow().strftime("%Y-%m-%d")

def get_balance(chat_id, user_id):
    cursor.execute(
        "SELECT plus_left, minus_left, warned, date FROM daily_balance "
        "WHERE chat_id=? AND user_id=?",
        (chat_id, user_id)
    )
    row = cursor.fetchone()

    if not row or row[3] != today():
        cursor.execute(
            "REPLACE INTO daily_balance VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, user_id, DAILY_PLUS, DAILY_MINUS, 0, today())
        )
        conn.commit()
        return DAILY_PLUS, DAILY_MINUS, 0

    return row[0], row[1], row[2]

def update_balance(chat_id, user_id, plus, minus, warned):
    cursor.execute(
        "UPDATE daily_balance SET plus_left=?, minus_left=?, warned=? "
        "WHERE chat_id=? AND user_id=?",
        (plus, minus, warned, chat_id, user_id)
    )
    conn.commit()

def change_rating(chat_id, user_id, delta):
    cursor.execute(
        "SELECT rating FROM ratings WHERE chat_id=? AND user_id=?",
        (chat_id, user_id)
    )
    row = cursor.fetchone()

    if row is None:
        cursor.execute(
            "INSERT INTO ratings VALUES (?, ?, ?)",
            (chat_id, user_id, delta)
        )
    else:
        cursor.execute(
            "UPDATE ratings SET rating=? WHERE chat_id=? AND user_id=?",
            (row[0] + delta, chat_id, user_id)
        )
    conn.commit()

def log_action(chat_id, f, t, amt):
    cursor.execute(
        "INSERT INTO actions VALUES (?, ?, ?, ?, ?)",
        (chat_id, f, t, amt, int(datetime.utcnow().timestamp()))
    )
    conn.commit()

def total_given(chat_id, f, t):
    cursor.execute(
        "SELECT SUM(amount) FROM actions "
        "WHERE chat_id=? AND from_id=? AND to_id=? AND amount>0",
        (chat_id, f, t)
    )
    return cursor.fetchone()[0] or 0

# ------------------ COMMANDS ------------------
@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer("✅ Бот жив. Рейтинг считается.")

@dp.message(Command("me"))
async def me(m: types.Message):
    plus, minus, _ = get_balance(m.chat.id, m.from_user.id)
    await m.answer(
        f"👤 {m.from_user.first_name}\n"
        f"➕ Плюсы: {plus}\n"
        f"➖ Минусы: {minus}/50"
    )

@dp.message(Command("top"))
async def top(m: types.Message):
    cursor.execute(
        "SELECT user_id, rating FROM ratings "
        "WHERE chat_id=? ORDER BY rating DESC",
        (m.chat.id,)
    )
    rows = cursor.fetchall()
    if not rows:
        await m.answer("📊 Пока пусто")
        return

    text = "🏆 Рейтинг:\n\n"
    for i, (uid, r) in enumerate(rows, 1):
        try:
            member = await bot.get_chat_member(m.chat.id, uid)
            name = member.user.first_name
        except:
            name = "Пользователь"
        text += f"{i}. {name} — {r}\n"

    await m.answer(text)

@dp.message(Command("rich"))
async def rich(m: types.Message):
    cursor.execute(
        "SELECT from_id, SUM(amount) FROM actions "
        "WHERE chat_id=? AND amount>0 "
        "GROUP BY from_id ORDER BY SUM(amount) DESC LIMIT 5",
        (m.chat.id,)
    )
    rows = cursor.fetchall()
    text = "💸 Щедрые:\n\n"
    for i, (uid, s) in enumerate(rows, 1):
        text += f"{i}. +{s}\n"
    await m.answer(text)

@dp.message(Command("hate"))
async def hate(m: types.Message):
    cursor.execute(
        "SELECT from_id, SUM(amount) FROM actions "
        "WHERE chat_id=? AND amount<0 "
        "GROUP BY from_id ORDER BY SUM(amount) ASC LIMIT 5",
        (m.chat.id,)
    )
    rows = cursor.fetchall()
    text = "😈 Хейтеры:\n\n"
    for i, (uid, s) in enumerate(rows, 1):
        text += f"{i}. {abs(s)}\n"
    await m.answer(text)

@dp.message(Command("stat"))
async def stat(m: types.Message):
    cursor.execute(
        "SELECT COUNT(*), SUM(amount) FROM actions WHERE chat_id=?",
        (m.chat.id,)
    )
    c, s = cursor.fetchone()
    await m.answer(f"📊 Действий: {c}\n🔢 Сумма: {s or 0}")

# ------------------ RATING HANDLER ------------------
@dp.message()
async def rating_handler(m: types.Message):
    if not m.reply_to_message or not m.text:
        return

    match = RATING_PATTERN.search(m.text)
    if not match:
        return

    sign, num = match.groups()
    amount = int(num)
    if not 1 <= amount <= 100:
        return

    voter = m.from_user
    target = m.reply_to_message.from_user
    if not target or voter.id == target.id:
        return

    plus, minus, warned = get_balance(m.chat.id, voter.id)

    # -------- PLUS --------
    if sign == "+":
        if plus < amount:
            await m.reply("💸 Плюсов не хватает")
            return

        plus -= amount
        change_rating(m.chat.id, target.id, amount)
        log_action(m.chat.id, voter.id, target.id, amount)

    # -------- MINUS -

