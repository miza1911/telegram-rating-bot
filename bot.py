import os
import re
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

def change_rating(chat_id, user_id, delta):
    cursor.execute(
        "INSERT INTO ratings VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET rating = rating + ?",
        (chat_id, user_id, delta, delta)
    )
    conn.commit()

# ---------------- COMMANDS ----------------
@dp.message(Command("me"))
async def me(m: types.Message):
    cursor.execute(
        "SELECT rating FROM ratings WHERE chat_id=? AND user_id=?",
        (m.chat.id, m.from_user.id)
    )
    row = cursor.fetchone()
    rating = row[0] if row else 0
    await m.answer(f"⭐ {rating}")

# ---------------- DEBUG: ВСЕ ОБНОВЛЕНИЯ ----------------
@dp.update()
async def debug_updates(update: types.Update):
    if update.message_reaction:
        logging.info("🔥 REACTION UPDATE ARRIVED")

# ---------------- REACTIONS ----------------
@dp.message_reaction()
async def reactions(event: types.MessageReactionUpdated):

    logging.info("🔥 HANDLER TRIGGERED")

    if not event.user:
        return

    chat_id = event.chat.id
    voter_id = event.user.id
    message_id = event.message_id

    # получаем сообщение через API
    try:
        msg = await bot.get_message(chat_id, message_id)
    except Exception as e:
        logging.info(f"cannot fetch message: {e}")
        return

    if not msg.from_user:
        logging.info("no author")
        return

    target_id = msg.from_user.id

    if target_id == voter_id:
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

    # ВКЛЮЧАЕМ ВСЕ ОБНОВЛЕНИЯ
    await dp.start_polling(bot, allowed_updates=None)

if __name__ == "__main__":
    asyncio.run(main())

