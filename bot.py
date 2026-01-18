import os
import re
import random
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

# ---------- DB ----------
conn = sqlite3.connect("ratings.db")
cursor = conn.cursor()

cursor.executescript("""
CREATE TABLE IF NOT EXISTS rating (
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

# ---------- CONST ----------
DAILY_PLUS = 100
DAILY_MINUS = 50
SHAME_LIMIT = -500

RATING_RE = re.compile(r"([+-])\s*(\d{1,3})")

LOW_PLUS_WARNINGS = [
    "⚠️ Осторожно, щедрость на исходе",
    "💸 Плюсы тают, как морожка на солнце",
    "🫣 Ты почти нищий по плюсам",
    "😬 Осталось меньше 50, держись",
    "📉 Щедрость уходит в минус-муд"
]

# ---------- HELPERS ----------
def today():
    return datetime.utcnow().strftime("%Y-%m-%d")

def name(u: types.User):
    return u.first_name

def get_balance(chat_id, user_id):
    cursor.execute(
        "SELECT plus_left, minus_left, warned, date FROM daily_balance WHERE chat_id=? AND user_id=?",
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
        "UPDATE daily_balance SET plus_left=?, minus_left=?, warned=? WHERE chat_id=? AND user_id=?",
        (plus, minus, warned, chat_id, user_id)
    )
    conn.commit()

def add_rating(chat_id, user_id, delta):
    cursor.execute(
        "INSERT INTO rating VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET rating = rating + ?",
        (chat_id, user_id, delta, delta)
    )
    conn.commit()

def log(chat_id, f, t, amt):
    cursor.execute(
        "INSERT INTO actions VALUES (?, ?, ?, ?, ?)",
        (chat_id, f, t, amt, int(datetime.utcnow().timestamp()))
    )
    conn.commit()

def given_before(chat_id, f, t):
    cursor.execute(
        "SELECT SUM(amount) FROM actions WHERE chat_id=? AND from_id=? AND to_id=? AND amount>0",
        (chat_id, f, t)
    )
    return cursor.fetchone()[0] or 0

# ---------- HANDLER ----------
@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer("🤖 Рейтинговый бот запущен.")

@dp.message()
async def rate(m: types.Message):
    if not m.reply_to_message or not m.text:
        return

    match = RATING_RE.search(m.text)
    if not match:
        return

    sign, num = match.groups()
    amount = int(num)

    voter = m.from_user
    target = m.reply_to_message.from_user

    if voter.id == target.id:
        await m.reply("🤨 Сам себе — запрещено.")
        return

    plus, minus, warned = get_balance(m.chat.id, voter.id)

    if sign == "+":
        if plus < amount:
            await m.reply("💸 Плюсов не хватает.")
            return
        plus -= amount
        add_rating(m.chat.id, target.id, amount)
        log(m.chat.id, voter.id, target.id, amount)

    else:
        given = given_before(m.chat.id, voter.id, target.id)
        rollback = min(given, amount)

        if rollback > 0:
            plus += rollback
            log(m.chat.id, voter.id, target.id, -rollback)

        real_minus = amount - rollback

        if real_minus > 0:
            if minus >= real_minus:
                minus -= real_minus
            else:
                if given < amount:
                    await m.reply("🐍 Сначала дай, потом забирай.")
                    return
        add_rating(m.chat.id, target.id, -real_minus)

    if plus < 50 and not warned:
        await m.reply(random.choice(LOW_PLUS_WARNINGS))
        warned = 1

    update_balance(m.chat.id, voter.id, plus, minus, warned)

    cursor.execute(
        "SELECT SUM(amount) FROM actions WHERE chat_id=? AND to_id=? AND ts > ?",
        (m.chat.id, target.id, int((datetime.utcnow()-timedelta(days=1)).timestamp()))
    )
    day_total = cursor.fetchone()[0] or 0

    if day_total <= SHAME_LIMIT:
        await m.answer(
            f"🚨 ПОЗОР ДНЯ 🚨\n{ name(target) } за сутки набрал {day_total}."
        )

# ---------- COMMANDS ----------
@dp.message(Command("me"))
async def me(m: types.Message):
    plus, minus, _ = get_balance(m.chat.id, m.from_user.id)
    await m.answer(
        f"👤 {name(m.from_user)}\n"
        f"➕ Плюсы: {plus}\n"
        f"➖ Минусы: {minus}/50"
    )

@dp.message(Command("rich"))
async def rich(m: types.Message):
    cursor.execute(
        "SELECT from_id, SUM(amount) FROM actions WHERE chat_id=? AND amount>0 GROUP BY from_id ORDER BY SUM(amount) DESC LIMIT 5",
        (m.chat.id,)
    )
    rows = cursor.fetchall()
    text = "💸 Щедрецы:\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. {r[1]}\n"
    await m.answer(text)

@dp.message(Command("hate"))
async def hate(m: types.Message):
    cursor.execute(
        "SELECT from_id, SUM(amount) FROM actions WHERE chat_id=? AND amount<0 GROUP BY from_id ORDER BY SUM(amount) ASC LIMIT 5",
        (m.chat.id,)
    )
    rows = cursor.fetchall()
    text = "😈 Хейтеры:\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. {abs(r[1])}\n"
    await m.answer(text)

@dp.message(Command("top"))
async def top(m: types.Message):
    cursor.execute(
        "SELECT user_id, rating FROM rating WHERE chat_id=? ORDER BY rating DESC LIMIT 10",
        (m.chat.id,)
    )
    rows = cursor.fetchall()
    text = "🏆 Рейтинг:\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. {r[1]}\n"
    await m.answer(text)

@dp.message(Command("stat"))
async def stat(m: types.Message):
    cursor.execute(
        "SELECT COUNT(*), SUM(amount) FROM actions WHERE chat_id=?",
        (m.chat.id,)
    )
    c, s = cursor.fetchone()
    await m.answer(f"📊 Всего действий: {c}\n🔢 Сумма: {s or 0}")

# ---------- RUN ----------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
