import os
import re
import sqlite3
import asyncio
import logging
from datetime import date
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# --- CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set")

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

def today():
    return date.today().isoformat()

# --- DB ---
conn = sqlite3.connect("ratings.db")
cursor = conn.cursor()

cursor.executescript("""
CREATE TABLE IF NOT EXISTS rating (
    chat_id INTEGER,
    user_id INTEGER,
    score INTEGER DEFAULT 0,
    PRIMARY KEY(chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS daily (
    chat_id INTEGER,
    user_id INTEGER,
    day TEXT,
    plus_left INTEGER DEFAULT 100,
    minus_left INTEGER DEFAULT 50,
    PRIMARY KEY(chat_id, user_id, day)
);

CREATE TABLE IF NOT EXISTS given (
    chat_id INTEGER,
    from_id INTEGER,
    to_id INTEGER,
    amount INTEGER,
    PRIMARY KEY(chat_id, from_id, to_id)
);

CREATE TABLE IF NOT EXISTS stats (
    chat_id INTEGER,
    user_id INTEGER,
    day TEXT,
    given INTEGER DEFAULT 0,
    taken INTEGER DEFAULT 0,
    PRIMARY KEY(chat_id, user_id, day)
);
""")
conn.commit()

# --- HELPERS ---
POINT_RE = re.compile(r"([+-])\s*(\d{1,3})")

WARNINGS = [
    "⚠️ Осторожно, баллы тают быстрее чем доверие",
    "⚠️ Ещё чуть-чуть и будешь в минусовой нищете",
    "⚠️ Ты почти банкрот, подумай",
    "⚠️ Баланс скрипит, как старая табуретка",
    "⚠️ Щедрость — хорошо, но не до нуля",
    "⚠️ Осталось мало, потом будешь жалеть",
    "⚠️ Экономь, олигарх из тебя так себе",
]

def get_name(user: types.User):
    return user.full_name

def ensure_daily(chat_id, user_id):
    cursor.execute("""
    INSERT OR IGNORE INTO daily VALUES (?, ?, ?, 100, 50)
    """, (chat_id, user_id, today()))
    conn.commit()

# --- START ---
@dp.message(Command("start"))
async def start(msg: types.Message):
    await msg.answer("🤖 Бот рейтинга жив. Используй /rules")

# --- RATING ---
@dp.message()
async def rating(msg: types.Message):
    if not msg.reply_to_message or not msg.text:
        return

    m = POINT_RE.search(msg.text)
    if not m:
        return

    sign, num = m.groups()
    amount = int(num)
    if amount < 1 or amount > 100:
        return

    voter = msg.from_user
    target = msg.reply_to_message.from_user

    if voter.id == target.id:
        await msg.reply("🤡 Сам себе — это клиника")
        return

    chat = msg.chat.id
    ensure_daily(chat, voter.id)

    cursor.execute("""
    SELECT plus_left, minus_left FROM daily
    WHERE chat_id=? AND user_id=? AND day=?
    """, (chat, voter.id, today()))
    plus_left, minus_left = cursor.fetchone()

    # --- PLUS ---
    if sign == "+":
        if plus_left < amount:
            await msg.reply("💸 У тебя нет столько баллов")
            return

        cursor.execute("""
        UPDATE daily SET plus_left=plus_left-?
        WHERE chat_id=? AND user_id=? AND day=?
        """, (amount, chat, voter.id, today()))

        cursor.execute("""
        INSERT INTO rating VALUES (?, ?, ?)
        ON CONFLICT(chat_id,user_id)
        DO UPDATE SET score=score+?
        """, (chat, target.id, amount, amount))

        cursor.execute("""
        INSERT INTO given VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id,from_id,to_id)
        DO UPDATE SET amount=amount+?
        """, (chat, voter.id, target.id, amount, amount))

        cursor.execute("""
        INSERT INTO stats VALUES (?, ?, ?, ?, 0)
        ON CONFLICT(chat_id,user_id,day)
        DO UPDATE SET given=given+?
        """, (chat, voter.id, today(), amount, amount))

    # --- MINUS ---
    else:
        cursor.execute("""
        SELECT amount FROM given
        WHERE chat_id=? AND from_id=? AND to_id=?
        """, (chat, voter.id, target.id))
        row = cursor.fetchone()
        given_before = row[0] if row else 0

        if minus_left > 0:
            used = min(minus_left, amount)
            cursor.execute("""
            UPDATE daily SET minus_left=minus_left-?
            WHERE chat_id=? AND user_id=? AND day=?
            """, (used, chat, voter.id, today()))
            amount -= used

        if amount > 0:
            if given_before < amount:
                await msg.reply("😏 Сначала дай — потом забирай")
                return

            cursor.execute("""
            UPDATE given SET amount=amount-?
            WHERE chat_id=? AND from_id=? AND to_id=?
            """, (amount, chat, voter.id, target.id))

            cursor.execute("""
            UPDATE daily SET plus_left=plus_left+?
            WHERE chat_id=? AND user_id=? AND day=?
            """, (amount, chat, voter.id, today()))

        cursor.execute("""
        UPDATE rating SET score=score-?
        WHERE chat_id=? AND user_id=?
        """, (int(num), chat, target.id))

        cursor.execute("""
        INSERT INTO stats VALUES (?, ?, ?, 0, ?)
        ON CONFLICT(chat_id,user_id,day)
        DO UPDATE SET taken=taken+?
        """, (chat, voter.id, today(), int(num), int(num)))

    conn.commit()

    if plus_left - amount < 50:
        await msg.reply(WARNINGS[hash(voter.id) % len(WARNINGS)])

# --- COMMANDS ---
@dp.message(Command("bal"))
async def bal(msg):
    ensure_daily(msg.chat.id, msg.from_user.id)
    cursor.execute("""
    SELECT plus_left, minus_left FROM daily
    WHERE chat_id=? AND user_id=? AND day=?
    """, (msg.chat.id, msg.from_user.id, today()))
    p, m = cursor.fetchone()
    await msg.answer(f"💰 Баланс\n➕ {p}\n➖ {m}")

@dp.message(Command("me"))
async def me(msg):
    cursor.execute("""
    SELECT score FROM rating WHERE chat_id=? AND user_id=?
    """, (msg.chat.id, msg.from_user.id))
    score = cursor.fetchone()
    score = score[0] if score else 0
    await msg.answer(f"👤 {get_name(msg.from_user)}\n🏆 Рейтинг: {score}")

@dp.message(Command("rich"))
async def rich(msg):
    cursor.execute("""
    SELECT user_id, given FROM stats
    WHERE chat_id=? AND day=?
    ORDER BY given DESC LIMIT 10
    """, (msg.chat.id, today()))
    rows = cursor.fetchall()
    text = "🤑 Щедрецы\n\n"
    for i, (u, g) in enumerate(rows, 1):
        user = await bot.get_chat_member(msg.chat.id, u)
        text += f"{i}. {user.user.full_name} — {g}\n"
    await msg.answer(text or "💤 Тишина")

@dp.message(Command("hate"))
async def hate(msg):
    cursor.execute("""
    SELECT user_id, taken FROM stats
    WHERE chat_id=? AND day=?
    ORDER BY taken DESC LIMIT 10
    """, (msg.chat.id, today()))
    rows = cursor.fetchall()
    text = "😈 Хейтеры\n\n"
    for i, (u, t) in enumerate(rows, 1):
        user = await bot.get_chat_member(msg.chat.id, u)
        text += f"{i}. {user.user.full_name} — {t}\n"
    await msg.answer(text or "🌸 Все добрые")

@dp.message(Command("rules"))
async def rules(msg):
    await msg.answer(
        "📜 **Правила**\n\n"
        "➕ 100 баллов в сутки\n"
        "➖ 50 минус-баллов\n"
        "Минусы сначала жрут минус-баланс\n"
        "Потом — только тем, кому давал плюсы\n"
        "Самому себе нельзя\n"
        "Реплай обязателен\n"
        "Баллы — сила, думай\n"
    )

# --- RUN ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
