import os
import sqlite3
import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

logging.basicConfig(level=logging.INFO)

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
""")
conn.commit()

# ---------------- EMOJI ----------------
LAUGH = {"😂","🤣","😹","😆","😅","😄","😁"}
HEARTS = {"❤","❤️","💖","💗","💘","💝","💕"}
LIKES = {"👍","👌","👏"}
WOW = {"😮","😲","😯"}
NEGATIVE = {"💩","🤮","👎","😡","😠","🤡","🤢"}

# ---------------- HELPERS ----------------
def change_rating(chat_id, user_id, delta):
    cursor.execute(
        "INSERT INTO ratings VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET rating = rating + ?",
        (chat_id, user_id, delta, delta)
    )
    conn.commit()

def status_emoji(score):
    if score >= 300: return "😎"
    elif score >= 0: return "🙂"
    elif score <= -300: return "💀"
    elif score <= -100: return "🤡"
    return ""

# ---------------- COMMANDS ----------------
@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer("Бот работает 😈")

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

    text = "🏆 Топ чата:\n\n"
    medals = ["🥇","🥈","🥉"]

    for i, (uid, rating) in enumerate(rows, 1):
        try:
            member = await bot.get_chat_member(m.chat.id, uid)
            name = member.user.first_name
        except:
            name = "user"

        prefix = medals[i-1] if i <= 3 else f"{i}."
        text += f"{prefix} {name} — {rating}\n"

    await m.answer(text)

# ---------------- REACTIONS ----------------
@dp.message_reaction()
async def reactions(event: types.MessageReactionUpdated):
    logging.info("🔥 reaction received")

    if not event.user:
        return

    chat_id = event.chat.id
    voter_id = event.user.id
    message_id = event.message_id

    # получаем автора сообщения
    try:
        forwarded = await bot.forward_message(
            chat_id=chat_id,
            from_chat_id=chat_id,
            message_id=message_id
        )
    except Exception as e:
        logging.info(f"forward error: {e}")
        return

    if not forwarded.forward_from:
        await bot.delete_message(chat_id, forwarded.message_id)
        return

    target_id = forwarded.forward_from.id

    # удаляем пересланное сообщение
    await bot.delete_message(chat_id, forwarded.message_id)

    if voter_id == target_id:
        return

    for r in event.new_reaction:
        emoji = r.emoji

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
            logging.info(f"+{score} added")

# ---------------- RUN ----------------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

