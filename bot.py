import os
import re
import random
import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart

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
    "💸 Баллы тают быстрее доверия",
    "😬 Осталось меньше 50, держись",
    "🫠 Баллы испаряются",
    "📦 Пустеющий склад",
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

def progress_bar(current, total, length=10):
    filled = int(current / total * length) if total else 0
    empty = length - filled
    return "🟩"*filled + "⬜"*empty

# ---------- HANDLERS ----------
@dp.message(CommandStart())
async def start(m: types.Message):
    await m.answer("🐾 Рейтинговый бот активен. Используй /me, /top, /rich, /hate")

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
        used_free = min(minus_free, amount)
        remaining = amount - used_free
        minus_free -= used_free

        if remaining > 0:
            given = given_to(m.chat.id, voter.id, target.id)
            if given < remaining:
                await m.reply("🐍 Сначала дай, потом забирай.")
                return
            plus_left += remaining
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
        await m.answer(f"🚨 ПОЗОР ДНЯ 🚨\n{get_name(target)} за сутки набрал {total}.")

# ---------- COMMANDS ----------
@dp.message(Command(commands=["me"]))
async def me(m: types.Message):
    plus, minus = get_daily(m.chat.id, m.from_user.id)

    cursor.execute(
        "SELECT rating FROM rating WHERE chat_id=? AND user_id=?",
        (m.chat.id, m.from_user.id)
    )
    rating = cursor.fetchone()
    rating = rating[0] if rating else 0

    cursor.execute(
        "SELECT SUM(amount) FROM daily_actions WHERE chat_id=? AND from_id=? AND amount>0",
        (m.chat.id, m.from_user.id)
    )
    given_total = cursor.fetchone()[0] or 0

    cursor.execute(
        "SELECT SUM(amount) FROM daily_actions WHERE chat_id=? AND from_id=? AND amount<0",
        (m.chat.id, m.from_user.id)
    )
    taken_total = abs(cursor.fetchone()[0] or 0)

    text = (
        f"📊 <b>Твоя статистика</b>\n"
        f"⭐ <b>Рейтинг:</b> {rating}\n"
        f"➕ <b>Осталось плюсов:</b> {plus} {progress_bar(plus, DAILY_PLUS)}\n"
        f"➖ <b>Минус-баланс:</b> {minus} {progress_bar(minus, DAILY_MINUS_FREE)}\n"
        f"💰 <b>Отдал всего:</b> {given_total}\n"
        f"😈 <b>Забрал всего:</b> {taken_total}"
    )
    await m.answer(text, parse_mode="HTML")

@dp.message(Command(commands=["top"]))
async def top(m: types.Message):
    cursor.execute(
        "SELECT user_id, rating FROM rating WHERE chat_id=? ORDER BY rating DESC LIMIT 10",
        (m.chat.id,)
    )
    rows = cursor.fetchall()
    if not rows:
        await m.answer("Рейтинг пока пуст 😔")
        return

    max_rating = max([r[1] for r in rows], default=1)
    text = "🏆 <b>Топ участников</b>:\n\n"
    medals = ["🥇", "🥈", "🥉"]

    for i, (user_id, rating) in enumerate(rows, 1):
        try:
            user = await bot.get_chat_member(m.chat.id, user_id)
            name = user.user.first_name
        except:
            name = f"User {user_id}"
        bar = progress_bar(rating, max_rating)
        medal = medals[i-1] if i <= 3 else f"{i}."
        text += f"{medal} {name} — {rating} {bar}\n"

    await m.answer(text, parse_mode="HTML")

@dp.message(Command(commands=["rich"]))
async def rich(m: types.Message):
    cursor.execute(
        "SELECT from_id, SUM(amount) FROM daily_actions "
        "WHERE chat_id=? AND amount>0 GROUP BY from_id ORDER BY SUM(amount) DESC LIMIT 5",
        (m.chat.id,)
    )
    rows = cursor.fetchall()
    if not rows:
        await m.answer("Пока никто не раздавал плюсы 😔")
        return
    max_val = max([r[1] for r in rows], default=1)
    text = "💎 <b>Самые щедрые за сутки</b>:\n"
    for i, r in enumerate(rows, 1):
        try:
            user = await bot.get_chat_member(m.chat.id, r[0])
            name = user.user.first_name
        except:
            name = f"User {r[0]}"
        bar = progress_bar(r[1], max_val)
        text += f"{i}. {name} — {r[1]} {bar}\n"
    await m.answer(text, parse_mode="HTML")

@dp.message(Command(commands=["hate"]))
async def hate(m: types.Message):
    cursor.execute(
        "SELECT from_id, SUM(amount) FROM daily_actions "
        "WHERE chat_id=? AND amount<0 GROUP BY from_id ORDER BY SUM(amount) ASC LIMIT 5",
        (m.chat.id,)
    )
    rows = cursor.fetchall()
    if not rows:
        await m.answer("Пока никто не раздавал минусы 😔")
        return
    max_val = max([abs(r[1]) for r in rows], default=1)
    text = "😈 <b>Хейтеры за сутки</b>:\n"
    for i, r in enumerate(rows, 1):
        try:
            user = await bot.get_chat_member(m.chat.id, r[0])
            name = user.user.first_name
        except:
            name = f"User {r[0]}"
        bar = progress_bar(abs(r[1]), max_val)
        text += f"{i}. {name} — {abs(r[1])} {bar}\n"
    await m.answer(text, parse_mode="HTML")

# ---------- RUN ----------
async def main():
    print("⚡️ Polling started...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

