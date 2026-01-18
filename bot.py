import os
import re
import random
import sqlite3
import asyncio
import logging
from datetime import date

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# ----------------- CONFIG -----------------
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

DAILY_PLUS_LIMIT = 100
DAILY_MINUS_LIMIT = 50
LOW_BALANCE_THRESHOLD = 50
SHAME_THRESHOLD = -500

# ----------------- BOT -----------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ----------------- DATABASE -----------------
conn = sqlite3.connect("ratings.db")
cursor = conn.cursor()

cursor.executescript("""
CREATE TABLE IF NOT EXISTS ratings (
    chat_id INTEGER,
    user_id INTEGER,
    rating INTEGER,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS daily_balance (
    chat_id INTEGER,
    user_id INTEGER,
    day TEXT,
    plus_left INTEGER,
    minus_left INTEGER,
    warned INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id, day)
);

CREATE TABLE IF NOT EXISTS transfers (
    chat_id INTEGER,
    from_user INTEGER,
    to_user INTEGER,
    given INTEGER,
    PRIMARY KEY (chat_id, from_user, to_user)
);
""")
conn.commit()

# ----------------- TEXTS -----------------
LOW_BALANCE_TEXTS = [
    "Баллы тают. Осталось меньше 50. Дальше - осознанно.",
    "Баланс худеет. Пора выбирать любимчиков.",
    "Ты входишь в зону риска. Баллов становится мало.",
    "Осталось меньше 50. Срач становится дорогим.",
    "Баллы заканчиваются, характер - нет.",
    "Теперь каждый реплай имеет цену.",
    "Баланс почти пуст. Время настоящих решений.",
    "Ты уже не щедрый. Ты избирательный.",
    "Баллы на исходе. Осторожнее с эмоциями.",
    "Ниже 50 - это когда начинаешь думать.",
    "Эконом-режим активирован.",
    "Баллов всё меньше. Репутация дороже.",
    "Ты приближаешься к финансовой тишине.",
    "Каждый плюс теперь чувствуется.",
    "Баланс проседает. Паники нет, но…",
    "Дальше - только по любви.",
    "Минусовать можно, но осторожно.",
    "Баллы не бесконечны. Увы.",
    "Расточительность - враг рейтинга.",
    "Конец халяве. Началась математика."
]

SHAME_TEXT = (
    "🚨 ПОЗОР ДНЯ 🚨\n\n"
    "{name} набрал {rating} за сутки.\n"
    "Коллектив официально недоволен."
)

# ----------------- HELPERS -----------------
def today():
    return date.today().isoformat()

def get_or_create_balance(chat_id, user_id):
    cursor.execute("""
        SELECT plus_left, minus_left, warned
        FROM daily_balance
        WHERE chat_id=? AND user_id=? AND day=?
    """, (chat_id, user_id, today()))
    row = cursor.fetchone()

    if row:
        return row

    cursor.execute("""
        INSERT INTO daily_balance (chat_id, user_id, day, plus_left, minus_left)
        VALUES (?, ?, ?, ?, ?)
    """, (chat_id, user_id, today(), DAILY_PLUS_LIMIT, DAILY_MINUS_LIMIT))
    conn.commit()
    return DAILY_PLUS_LIMIT, DAILY_MINUS_LIMIT, 0

def update_balance(chat_id, user_id, plus_left, minus_left, warned):
    cursor.execute("""
        UPDATE daily_balance
        SET plus_left=?, minus_left=?, warned=?
        WHERE chat_id=? AND user_id=? AND day=?
    """, (plus_left, minus_left, warned, chat_id, user_id, today()))
    conn.commit()

def change_rating(chat_id, user_id, delta):
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

def remember_transfer(chat_id, from_id, to_id, amount):
    cursor.execute("""
        INSERT INTO transfers (chat_id, from_user, to_user, given)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id, from_user, to_user)
        DO UPDATE SET given = given + ?
    """, (chat_id, from_id, to_id, amount, amount))
    conn.commit()

def has_given_before(chat_id, from_id, to_id):
    cursor.execute("""
        SELECT given FROM transfers
        WHERE chat_id=? AND from_user=? AND to_user=? AND given > 0
    """, (chat_id, from_id, to_id))
    return cursor.fetchone() is not None

# ----------------- COMMANDS -----------------
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("✅ Бот жив. Система баллов активна.")

@dp.message(Command("me"))
async def me(message: types.Message):
    chat_id = message.chat.id
    user = message.from_user

    cursor.execute(
        "SELECT rating FROM ratings WHERE chat_id=? AND user_id=?",
        (chat_id, user.id)
    )
    rating = cursor.fetchone()
    rating = rating[0] if rating else 0

    plus_left, minus_left, _ = get_or_create_balance(chat_id, user.id)

    await message.answer(
        f"🐾 Твоя статистика\n\n"
        f"Имя: {user.first_name}\n"
        f"Общий рейтинг: {rating}\n\n"
        f"Сегодня:\n"
        f"➕ Осталось плюсов: {plus_left}/100\n"
        f"➖ Минусы: {minus_left}/50"
    )

# ----------------- RATING HANDLER -----------------
RATING_PATTERN = re.compile(r"([+-])(\d{1,3})")

@dp.message()
async def rating_handler(message: types.Message):
    if not message.reply_to_message or not message.text:
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
    chat_id = message.chat.id

    if voter.id == target.id:
        await message.reply("Сам себе - это терапия, а не рейтинг 😏")
        return

    plus_left, minus_left, warned = get_or_create_balance(chat_id, voter.id)

    # ---------- PLUS ----------
    if sign == "+":
        if plus_left < amount:
            await message.reply("У тебя столько плюсов нет. Экономь 😌")
            return

        plus_left -= amount
        remember_transfer(chat_id, voter.id, target.id, amount)
        new_rating = change_rating(chat_id, target.id, amount)

    # ---------- MINUS ----------
    else:
        if minus_left >= amount:
            minus_left -= amount
        else:
            if not has_given_before(chat_id, voter.id, target.id):
                await message.reply(
                    "Прежде чем забирать - надо сначала дать 😏"
                )
                return

        new_rating = change_rating(chat_id, target.id, -amount)

    # ---------- WARN LOW BALANCE ----------
    if plus_left < LOW_BALANCE_THRESHOLD and not warned:
        warned = 1
        await message.answer(
            random.choice(LOW_BALANCE_TEXTS)
        )

    update_balance(chat_id, voter.id, plus_left, minus_left, warned)

    # ---------- SHAME ----------
    if new_rating <= SHAME_THRESHOLD:
        await message.answer(
            SHAME_TEXT.format(
                name=target.first_name,
                rating=new_rating
            )
        )

# ----------------- RUN -----------------
async def main():
    logging.info("🤖 Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
