import os
import re
import sqlite3
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# ------------------ LOGGING ------------------
logging.basicConfig(level=logging.INFO)
logging.info("🚀 rofl-bot started")

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ------------------ DATABASE ------------------
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

# ------------------ TIME ------------------
MSK = timezone(timedelta(hours=3))

# ------------------ EMOJI GROUPS ------------------
LAUGH = {"😂","🤣","😹","😆","😅","😄","😁","😸","😺"}
HEARTS = {"❤","❤️","💖","💗","💘","💝","💓","💞","💕","💟","🫶"}
LIKES = {"👍","👌","👏"}
WOW = {"😮","😲","😯"}
NEGATIVE = {"💩","🤮","👎","😡","😠","🤡","🤢"}

ORU = re.compile(r"ору+", re.IGNORECASE)
AHAH = re.compile(r"(ах)+", re.IGNORECASE)

# ------------------ HELPERS ------------------
def normalize_emoji(e: str) -> str:
    modifiers = ["🏻","🏼","🏽","🏾","🏿","️"]
    for m in modifiers:
        e = e.replace(m, "")
    return e

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

async def get_name(chat_id, user_id):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.user.first_name
    except:
        return "Пользователь"

def status_emoji(score):
    if score >= 1000: return "🔥"
    elif score >= 300: return "😎"
    elif score >= 0: return "🙂"
    elif score <= -500: return "☠️"
    elif score <= -300: return "💀"
    elif score <= -100: return "🤡"
    return ""

# ------------------ COMMANDS ------------------
@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer(
        "😈 Бот активен\n\n"
        "😂 реакции дают очки\n"
        "❤️ поддержка = плюс\n"
        "🤡 негатив = минус\n"
        "ору / ахахах (реплай) → +50"
    )

@dp.message(Command("me"))
async def me(m: types.Message):
    cursor.execute(
        "SELECT rating FROM ratings WHERE chat_id=? AND user_id=?",
        (m.chat.id, m.from_user.id)
    )
    row = cursor.fetchone()
    rating = row[0] if row else 0

    await m.answer(
        f"👤 {m.from_user.first_name}\n"
        f"⭐ Рейтинг: {rating} {status_emoji(rating)}"
    )

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

    medals = ["🥇","🥈","🥉"]
    text = "🏆 Рейтинг чата\n\n"

    for i,(uid,r) in enumerate(rows,1):
        name = await get_name(m.chat.id, uid)
        prefix = medals[i-1] if i<=3 else f"{i}️⃣"
        text += f"{prefix} {name} — {r} {status_emoji(r)}\n"

    await m.answer(text)

# ------------------ TEXT REACTIONS ------------------
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

# ------------------ REACTIONS ------------------
@dp.message_reaction()
async def reactions(event: types.MessageReactionUpdated):
    logging.info("🔥 reaction update received")

    if not event.user:
        return

    chat_id = event.chat.id
    voter_id = event.user.id
    message_id = event.message_id

    try:
        msg = await bot.get_message(chat_id, message_id)
        target_id = msg.from_user.id
    except Exception as e:
        logging.warning(f"Cannot fetch message: {e}")
        return

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
        elif emoji in {"🔥","💯"}:
            score = 30
        elif emoji in NEGATIVE:
            score = -30

        if score:
            change_rating(chat_id, target_id, score)
            log_action(chat_id, message_id, voter_id, target_id, score)

# ------------------ RUN ------------------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)

    await dp.start_polling(
        bot,
        allowed_updates=[
            "message",
            "message_reaction",
            "message_reaction_count"
        ]
    )

if __name__ == "__main__":
    asyncio.run(main())


