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

# ------------------ TOKEN ------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

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

# ------------------ REACTIONS ------------------
LAUGH = {"😂","🤣","😹","😆","😅","😄","😁","😸","😺"}
HEARTS = {"❤️","🧡","💛","💚","💙","💜","🖤","🤍","🤎","💖","💘","💝","💗","💓","💞","💕","💟"}
POOP = {"💩","🗑","🤮","👎","😡","😠","😤","🤢"}

REACTION_SCORES = {
    "🔥": 30,
    "💯": 30,
    "😎": 15,
    "🤡": -20,
}

WOW = {"😮","😲","😯"}

# текстовые реакции
ORU = re.compile(r"\bору+\b", re.IGNORECASE)
AHAH = re.compile(r"(ах){2,}", re.IGNORECASE)

# ------------------ HELPERS ------------------
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
    if score >= 300: return "😎"
    if score >= 0: return "🙂"
    if score <= -500: return "☠️"
    if score <= -300: return "💀"
    if score <= -100: return "🤡"
    return ""

# ------------------ COMMANDS ------------------
@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer(
        "😈 Рофл-бот активен\n\n"
        "😂 реакции дают очки\n"
        "ору / ахахах (реплай) → +50\n"
        "Самые популярные сообщения попадают в рейтинг"
    )

@dp.message(Command("me"))
async def me(m: types.Message):
    cursor.execute(
        "SELECT rating FROM ratings WHERE chat_id=? AND user_id=?",
        (m.chat.id, m.from_user.id)
    )
    r = cursor.fetchone()
    rating = r[0] if r else 0

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

    # лидер сообщений
    cursor.execute("""
        SELECT message_id, to_id, COUNT(*) as c
        FROM actions
        WHERE chat_id=?
        GROUP BY message_id
        ORDER BY c DESC
        LIMIT 1
    """,(m.chat.id,))
    best = cursor.fetchone()

    if best:
        msg_id, uid, count = best
        try:
            msg = await bot.forward_message(m.chat.id, m.chat.id, msg_id)
            name = await get_name(m.chat.id, uid)
            time = datetime.fromtimestamp(msg.date.timestamp(), MSK).strftime("%H:%M")

            text += (
                "\n🔥 Самое обсуждаемое сообщение\n\n"
                f"👤 {name}\n"
                f"🕒 {time} (МСК)\n"
                f"Всего реакций: {count}"
            )
        except:
            pass

    await m.answer(text)

# ------------------ TEXT REACTIONS ------------------
@dp.message()
async def text_reactions(m: types.Message):
    if not m.reply_to_message or not m.text:
        return

    target = m.reply_to_message.from_user
    if not target:
        return

    score = 0

    if ORU.search(m.text):
        score += 50
    if AHAH.search(m.text):
        score += 50

    if score:
        change_rating(m.chat.id, target.id, score)
        log_action(m.chat.id, m.reply_to_message.message_id, m.from_user.id, target.id, score)

# ------------------ REACTION HANDLER ------------------
@dp.message_reaction()
async def reactions(event: types.MessageReactionUpdated):
    chat_id = event.chat.id
    user_id = event.user.id
    message_id = event.message_id

    for reaction in event.new_reaction:
        emoji = reaction.emoji
        score = 0

        if emoji in LAUGH:
            score = 40
        elif emoji in HEARTS:
            score = 10
        elif emoji in WOW:
            score = 20
        elif emoji in POOP:
            score = -30
        elif emoji in REACTION_SCORES:
            score = REACTION_SCORES[emoji]

        if score != 0:
            msg = await bot.get_message(chat_id, message_id)
            target = msg.from_user
            if target:
                change_rating(chat_id, target.id, score)
                log_action(chat_id, message_id, user_id, target.id, score)

# ------------------ RUN ------------------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
