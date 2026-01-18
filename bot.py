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

CREATE TABLE IF NOT EXISTS daily_actions (
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
    minus_free INTEGER,
    date TEXT,
    PRIMARY KEY (chat_id, user_id)
);
""")
conn.commit()

# ---------- CONST ----------
DAILY_PLUS = 100
DAILY_MINUS_FREE = 50
SHAME_LIMIT = -500

LOW_BALANCE_PHRASES = [
    "⚠️ Осторожно, щедрость на исходе",
    "🪫 Баллы тают быстрее доверия",
    "💸 Ты почти нищий… баллами",
    "😬 Осталось меньше 50, держись",
    "🧮 Математика намекает остановиться",
    "🥲 Скоро придётся смотреть, а не ставить",
    "🚨 Баланс краснеет",
    "🐭 Эконом-режим включён",
    "🫠 Баллы испаряются",
    "⚖️ Справедливость требует паузы",
    "🎭 Осталось мало аплодисментов",
    "📉 График идёт вниз",
    "🧊 Остываешь, дружище",
    "🕯 Последние искры плюсов",
    "🪙 Монет почти нет",
    "🤏 Щепотка баллов осталась",
    "📦 Пустеющий склад",
    "🚪 Баллы собираются уходить",
    "🫥 Скоро ничего не сможешь",
    "⌛ Почти всё потрачено"
]

RATING_RE = re.compile(r"([+-])\s*(\d{1,3})")

# ---------- HELPERS ----------
def today():
    return datetime.utcnow().strftime("%Y-%m-%d")

def get_name(user: types.User):
    return user.first_name

def get_daily(chat_id, user_id):
    cursor.execute(
        "SELECT plus_left, minus_free, date FROM daily_balance WHERE chat_id=? AND user_id=?",
        (chat_id, user_id)
    )
    row = cursor.fetchone()

    if not row or row[2] != today():
        cursor.execute(
            "REPLACE INTO daily_balance VALUES (?, ?, ?, ?, ?)",
            (chat_id, user_id, DAILY_PLUS, DAILY_MINUS_FREE, today())
        )
        conn.commit()
        return DAILY_PLUS, DAILY_MINUS_FREE

    return row[0], row[1]

def update_daily(chat_id, user_id, plus, minus):
    cursor.execute(
        "UPDATE daily_balance SET plus_left=?, minus_free=? WHERE chat_id=? AND user_id=?",
        (plus, minus, chat_id, user_id)
    )
    conn.commit()

def change_rating(chat_id, user_id, delta):
    cursor.execute(
        "INSERT INTO rating VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET rating = rating + ?",
        (chat_id, user_id, delta, delta)
    )
    conn.commit()

def log_action(chat_id, f, t, amt):
    cursor.execute(
        "INSERT INTO daily_actions VALUES (?, ?, ?, ?, ?)",
        (chat_id, f, t, amt, int(datetime.utcnow().timestamp()))
    )
    conn.commit()

def given_to(chat_id, f, t):
    cursor.execute(
        "SELECT SUM(amount) FROM daily_actions "
        "WHERE chat_id=? AND from_id=? AND to_id=? AND amount>0",
        (chat_id, f, t)
    )
    return cursor.fetchone()[0] or 0

# ---------- HANDLERS ----------
@dp.message()
async def rating(m: types.Message):
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
        await m.reply("🤡 Сам себе — запрещено.")
        return

    plus_left, minus_free = get_daily(m.chat.id, voter.id)

    if sign == "+":
        if plus_left < amount:
            await m.reply("💸 Баллов не хватает.")
            return
        plus_left -= amount
        delta = amount

    else:
        # минус
        used_free = min(minus_free, amount)
        remaining = amount - used_free

        minus_free -= used_free

        if remaining > 0:
            given = given_to(m.chat.id, voter.id, target.id)
            if given < remaining:
                await m.reply("🐍 Сначала дай, потом забирай.")
                return
            plus_left += remaining  # ВОЗВРАТ
        delta = -amount

    update_daily(m.chat.id, voter.id, plus_left, minus_free)
    change_rating(m.chat.id, target.id, delta)
    log_action(m.chat.id, voter.id, target.id, delta)

    if plus_left < 50:
        await m.reply(random.choice(LOW_BALANCE_PHRASES))

    cursor.execute(
        "SELECT SUM(amount) FROM daily_actions WHERE chat_id=? AND to_id=? AND ts > ?",
        (m.chat.id, target.id, int((datetime.utcnow()-timedelta(days=1)).timestamp()))
    )
    total = cursor.fetchone()[0] or 0

    if total <= SHAME_LIMIT:
        await m.answer(
            f"🚨 ПОЗОР ДНЯ 🚨\n{get_name(target)} за сутки набрал {total}."
        )

# ---------- COMMANDS ----------
@dp.message(Command("me"))
async def me(m: types.Message):
    plus, minus = get_daily(m.chat.id, m.from_user.id)
    await m.answer(
        f"👤 {get_name(m.from_user)}\n"
        f"➕ Плюсы: {plus}\n"
        f"➖ Минусы: {minus}/50"
    )

@dp.message(Command("rich"))
async def rich(m: types.Message):
    cursor.execute(
        "SELECT from_id, SUM(amount) FROM daily_actions "
        "WHERE chat_id=? AND amount>0 GROUP BY from_id ORDER BY SUM(amount) DESC LIMIT 5",
        (m.chat.id,)
    )
    rows = cursor.fetchall()
    text = "💎 Самые щедрые:\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. {r[1]}\n"
    await m.answer(text)

@dp.message(Command("hate"))
async def hate(m: types.Message):
    cursor.execute(
        "SELECT from_id, SUM(amount) FROM daily_actions "
        "WHERE chat_id=? AND amount<0 GROUP BY from_id ORDER BY SUM(amount) ASC LIMIT 5",
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

# ---------- RUN ----------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

