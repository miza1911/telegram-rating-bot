import os
import re
import sqlite3
import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)
logging.info("BOT STARTED")

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
    message_id INTEGER,
    from_id INTEGER,
    to_id INTEGER,
    amount INTEGER,
    ts INTEGER
);
""")
conn.commit()

# ---------------- EMOJI GROUPS ----------------
LAUGH = {"😂","🤣","😹","😆","😅","😄","😁"}
HEARTS = {"❤","❤️","💖","💗","💘","💝","💕"}
LIKES = {"👍","👌","👏"}
WOW = {"😮","😲","😯"}
NEGATIVE = {"💩","🤮","👎","😡","😠","🤡","🤢"}

ORU = re.compile(r"ору+", re.IGNORECASE)
AHAH = re.compile(r"(ах)+", re.IGNORECASE)

# ---------------- HELPERS ----------------
def normalize_emoji(e: str) -> str:
    return e.replace("️", "")

def change_rating(chat_id, user_id, delta):
    cursor.execute(
        "INSERT INTO ratings VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET rating = rating + ?",
        (chat_id, user_id, delta, delta)
    )
    conn.commit()

def log_action(chat_id, message_id, f, t, amt):
    cursor.execute(
        "INSERT INTO actions VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, message_id, f, t, amt, int(datetime.utcnow().timestamp()))
    )
    conn.commit()

# ---------------- COMMANDS ----------------
@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer(
        "😈 Бот активен\n\n"
        "😂 = +40\n"
        "❤️ = +10\n"
        "👍 = +15\n"
        "😮 = +20\n"
        "🤡 = -30\n"
        "ору / ахах (реплай) = +50"
    )

@dp.message(Command("me"))
async def me(m: types.Message):
    cursor.execute(
        "SELECT rating FROM ratings WHERE chat_id=? AND user_id=?",
        (m.chat.id, m.from_user.id)
    )
    row = cursor.fetchone()
    rating = row[0] if row else 0
    await m.answer(f"⭐ Рейтинг: {rating}")

@dp.message(Command("top"))
async def top(m: types.Message):
    cursor.execute(
        "SELECT user_id, rating FROM ratings WHERE chat_id=? ORDER BY rating DESC LIMIT 10",
        (m.chat.id,)
    )
    rows = cursor.fetchall()

    if not rows:
        await m.answer("Пока пусто")
        return

    text = "🏆 Топ чата:\n\n"
    medals = ["🥇","🥈","🥉"]

    for i,(uid,r) in enumerate(rows,1):
        try:
            member = await bot.get_chat_member(m.chat.id, uid)
            name = member.user.first_name
        except:
            name = "user"

        prefix = medals[i-1] if i<=3 else f"{i}."
        text += f"{prefix} {name} — {r}\n"

    await m.answer(text)

# ---------------- TEXT REACTIONS ----------------
@dp.message()
async def text_reactions(m: types.Message):
    if not m.reply_to_message or not m.text:
        return

    target = m.reply_to_message.from_user
    if not target or target.id == m.from_user.id:
        return

    score = 0
    if ORU.search(m.text):
        score += 50
    if AHAH.search(m.text):
        score += 50

    if score:
        change_rating(m.chat.id, target.id, score)
        log_action(m.chat.id, m.reply_to_message.message_id, m.from_user.id, target.id, score)

# ---------------- REACTIONS ----------------
@dp.message_reaction()
async def reactions(event: types.MessageReactionUpdated):
    logging.info("REACTION RECEIVED")

    if not event.user:
        return

    chat_id = event.chat.id
    voter_id = event.user.id
    message_id = event.message_id

    # стабильное получение автора сообщения
    try:
        forwarded = await bot.forward_message(
            chat_id=chat_id,
            from_chat_id=chat_id,
            message_id=message_id
        )
    except:
        return

    if not forwarded.forward_from:
        return

    target_id = forwarded.forward_from.id

    if voter_id == target_id:
        return

    for reaction in event.new_reaction:
        emoji = normalize_emoji(reaction.emoji)

        score = 0
        if emoji in LAUGH:
            score = 40
        elif emoji in HEARTS:
            score = 10
        elif emoji in LIKES:
            score = 15
        elif emoji in WOW:
            score = 20
        elif emoji in NEGATIVE:
            score = -30

        if score:
            change_rating(chat_id, target_id, score)
            log_action(chat_id, message_id, voter_id, target_id, score)

# ---------------- RUN ----------------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)

    # allowed_updates=None — критично для реакций
    await dp.start_polling(bot, allowed_updates=None)

if __name__ == "__main__":
    asyncio.run(main())

