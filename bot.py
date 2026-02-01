import os
import re
import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ChatPermissions

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
""")
conn.commit()

# ------------------ CONSTANTS ------------------
MAX_PER_ACTION = 200
SHAME_LIMIT = -500

# 🚫 Заблокированный пользователь (по username и имени)
BLOCKED_MINUS_USERNAME = "kuhelklopf"   
BLOCKED_MINUS_NAME = "Вера Гжель"       

RATING_PATTERN = re.compile(r"([+-])\s*(\d{1,3})")

SHAME_JOKES = [
    "Интернет всё помнит.",
    "Чат в шоке."
]

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
        "✅ Бот активен\n"
        "➕➖ Меняй рейтинг реплаем: +10, -5\n"
        f"⚠️ За один раз не больше {MAX_PER_ACTION}"
    )

@dp.message(Command("me"))
async def me(m: types.Message):
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
        f"⭐ Рейтинг: {rating}\n\n"
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
        name = await get_name(m.chat.id, uid)
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

    if not rows:
        await m.answer("💸 Пока никто не щедрил")
        return

    text = "💸 <b>Самые щедрые</b>\n\n"
    for i, (uid, s) in enumerate(rows, 1):
        name = await get_name(m.chat.id, uid)
        text += f"{i}. {name} — +{s}\n"

    await m.answer(text, parse_mode="HTML")

@dp.message(Command("hate"))
async def hate(m: types.Message):
    cursor.execute(
        "SELECT from_id, SUM(amount) FROM actions "
        "WHERE chat_id=? AND amount<0 "
        "GROUP BY from_id ORDER BY SUM(amount) ASC LIMIT 5",
        (m.chat.id,)
    )
    rows = cursor.fetchall()

    if not rows:
        await m.answer("😇 Хейтеров нет")
        return

    text = "😈 <b>Хейтеры</b>\n\n"
    for i, (uid, s) in enumerate(rows, 1):
        name = await get_name(m.chat.id, uid)
        text += f"{i}. {name} — {abs(s)}\n"

    await m.answer(text, parse_mode="HTML")

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

    if not 1 <= amount <= MAX_PER_ACTION:
        await m.reply(f"⚠️ Можно менять не больше {MAX_PER_ACTION} за раз.")
        return

    voter = m.from_user
    target = m.reply_to_message.from_user

    if not target or voter.id == target.id:
        return

    # 🚫 ОСОБОЕ ПРАВИЛО ДЛЯ ВЕРЫ
    if sign == "-" and (
        voter.username == BLOCKED_MINUS_USERNAME
        or voter.first_name == BLOCKED_MINUS_NAME
    ):
        try:
            await bot.restrict_chat_member(
                chat_id=m.chat.id,
                user_id=voter.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.utcnow() + timedelta(hours=1)
            )
        except Exception as e:
            logging.warning(f"Не удалось замьютить: {e}")

        await m.reply("🚫 Минусы тебе запрещены. Мьют на 1 час.")
        return

    delta = amount if sign == "+" else -amount

    change_rating(m.chat.id, target.id, delta)
    log_action(m.chat.id, voter.id, target.id, delta)

# ------------------ RUN ------------------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("🤖 polling started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


