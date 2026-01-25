import os
import re
import random
import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta, timezone

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
    date TEXT,
    PRIMARY KEY (chat_id, user_id)
);
""")
conn.commit()

# ------------------ CONSTANTS ------------------
DAILY_BALANCE = 200
SHAME_LIMIT = -500

RATING_PATTERN = re.compile(r"([+-])\s*(\d{1,3})")

SHAME_JOKES = [
    "Интернет всё помнит.",
    "Чат в шоке.",
    "Это уже диагноз.",
    "Лучше бы промолчал.",
    "История запомнит этот день."
]

# ------------------ TIME (MOSCOW) ------------------
MSK = timezone(timedelta(hours=3))

def today():
    return datetime.now(MSK).strftime("%Y-%m-%d")

# ------------------ HELPERS ------------------
def get_balance(chat_id, user_id):
    cursor.execute(
        "SELECT plus_left, date FROM daily_balance WHERE chat_id=? AND user_id=?",
        (chat_id, user_id)
    )
    row = cursor.fetchone()

    if not row or row[1] != today():
        cursor.execute(
            "REPLACE INTO daily_balance VALUES (?, ?, ?, ?)",
            (chat_id, user_id, DAILY_BALANCE, today())
        )
        conn.commit()
        return DAILY_BALANCE

    return row[0]

def update_balance(chat_id, user_id, plus):
    cursor.execute(
        "UPDATE daily_balance SET plus_left=? WHERE chat_id=? AND user_id=?",
        (plus, chat_id, user_id)
    )
    conn.commit()

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

# ------------------ COMMANDS ------------------
@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer(
        "✅ Бот активен\n"
        "🎯 У каждого 200 баллов в сутки\n"
        "🔄 Обновление — каждый день в 00:00 по Москве"
    )

@dp.message(Command("me"))
async def me(m: types.Message):
    balance = get_balance(m.chat.id, m.from_user.id)

    cursor.execute(
        "SELECT rating FROM ratings WHERE chat_id=? AND user_id=?",
        (m.chat.id, m.from_user.id)
    )
    rating = cursor.fetchone()
    rating = rating[0] if rating else 0

    cursor.execute(
        "SELECT SUM(amount) FROM actions WHERE chat_id=? AND from_id=? AND amount>0",
        (m.chat.id, m.from_user.id)
    )
    given = cursor.fetchone()[0] or 0

    cursor.execute(
        "SELECT SUM(amount) FROM actions WHERE chat_id=? AND from_id=? AND amount<0",
        (m.chat.id, m.from_user.id)
    )
    taken = abs(cursor.fetchone()[0] or 0)

    await m.answer(
        f"📊 <b>Твоя статистика</b>\n\n"
        f"👤 {m.from_user.first_name}\n"
        f"⭐ Рейтинг: {rating}\n"
        f"🎯 Осталось баллов: {balance}/200\n\n"
        f"💰 Отдал: +{given}\n"
        f"😈 Забрал: −{taken}",
        parse_mode="HTML"
    )

@dp.message(Command("top"))
async def top(m: types.Message):
    cursor.execute(
        "SELECT user_id, rating FROM ratings WHERE chat_id=? ORDER BY rating DESC",
        (m.chat.id,)
    )
    rows = cursor.fetchall()

    if not rows:
        await m.answer("📊 Пока пусто")
        return

    text = "🏆 <b>Общий рейтинг</b>\n\n"
    for i, (uid, r) in enumerate(rows, 1):
        try:
            member = await bot.get_chat_member(m.chat.id, uid)
            name = member.user.first_name
        except:
            name = "Пользователь"
        text += f"{i}. {name} — {r}\n"

    await m.answer(text, parse_mode="HTML")

@dp.message(Command("rich"))
async def rich(m: types.Message):
    cursor.execute(
        "SELECT from_id, SUM(amount) FROM actions "
        "WHERE chat_id=? AND amount>0 "
        "GROUP BY from_id ORDER BY SUM(amount) DESC LIMIT 5",
        (m.chat.id,)
    )
    rows = cursor.fetchall()

    text = "💸 <b>Самые щедрые</b>\n\n"
    for i, (uid, s) in enumerate(rows, 1):
        try:
            member = await bot.get_chat_member(m.chat.id, uid)
            name = member.user.first_name
        except:
            name = "Пользователь"
        text += f"{i}. {name} — +{s}\n"

    await m.answer(text or "Нет данных", parse_mode="HTML")

@dp.message(Command("hate"))
async def hate(m: types.Message):
    cursor.execute(
        "SELECT from_id, SUM(amount) FROM actions "
        "WHERE chat_id=? AND amount<0 "
        "GROUP BY from_id ORDER BY SUM(amount) ASC LIMIT 5",
        (m.chat.id,)
    )
    rows = cursor.fetchall()

    text = "😈 <b>Хейтеры</b>\n\n"
    for i, (uid, s) in enumerate(rows, 1):
        try:
            member = await bot.get_chat_member(m.chat.id, uid)
            name = member.user.first_name
        except:
            name = "Пользователь"
        text += f"{i}. {name} — {abs(s)}\n"

    await m.answer(text or "Тишина", parse_mode="HTML")

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

    if voter.id == target.id:
        return

    balance = get_balance(m.chat.id, voter.id)

    if balance < amount:
        await m.reply("❌ Недостаточно баллов.")
        return

    delta = amount if sign == "+" else -amount

    update_balance(m.chat.id, voter.id, balance - amount)
    change_rating(m.chat.id, target.id, delta)
    log_action(m.chat.id, voter.id, target.id, delta)

    cursor.execute(
        "SELECT SUM(amount) FROM actions WHERE chat_id=? AND to_id=? AND ts > ?",
        (m.chat.id, target.id,
         int((datetime.utcnow() - timedelta(days=1)).timestamp()))
    )
    day_sum = cursor.fetchone()[0] or 0

    if day_sum <= SHAME_LIMIT:
        await m.answer(
            f"🚨 ПОЗОР ДНЯ 🚨\n"
            f"{target.first_name} за сутки набрал {day_sum}\n"
            f"{random.choice(SHAME_JOKES)}"
        )

# ------------------ RUN ------------------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("🤖 polling started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

