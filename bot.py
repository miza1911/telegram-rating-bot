import os
import re
import random
import sqlite3
import asyncio
from aiogram import Bot, Dispatcher, types

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

# --- Bot ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Database ---
conn = sqlite3.connect("ratings.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS ratings (
    chat_id INTEGER,
    user_id INTEGER,
    rating INTEGER,
    PRIMARY KEY (chat_id, user_id)
)
""")
conn.commit()

def change_rating(chat_id: int, user_id: int, delta: int) -> int:
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

# --- Emojis ---
POSITIVE = ["😎", "🔥", "💪", "🚀", "✨", "😁", "👏"]
NEGATIVE = ["😡", "💀", "🤡", "👎", "😬", "🥶"]

def random_positive():
    return random.choice(POSITIVE)

def random_negative():
    return random.choice(NEGATIVE)

# --- Rating logic ---
RATING_PATTERN = re.compile(r"^([+-])(\d{1,3})$")

async def rating_handler(message: types.Message):
    if not message.reply_to_message:
        return

    match = RATING_PATTERN.match(message.text.strip())
    if not match:
        return

    sign, amount_str = match.groups()
    amount = int(amount_str)

    if not 1 <= amount <= 100:
        await message.reply("Можно менять рейтинг только от 1 до 100 😎")
        return

    voter = message.from_user
    target = message.reply_to_message.from_user

    if voter.id == target.id:
        await message.reply("Сам себе рейтинг крутить нельзя 😏")
        return

    delta = amount if sign == "+" else -amount
    new_rating = change_rating(message.chat.id, target.id, delta)

    emoji = random_positive() if delta > 0 else random_negative()
    delta_text = f"+{amount}" if delta > 0 else f"-{amount}"

    voter_name = f"@{voter.username}" if voter.username else voter.full_name
    target_name = f"@{target.username}" if target.username else target.full_name

    await message.answer(
        f"👤 {voter_name} изменил рейтинг пользователю {target_name} {delta_text}\n"
        f"📊 Общий рейтинг в чате НОСА: {new_rating} {emoji}"
    )

# --- Run ---
async def main():
    dp.message.register(rating_handler)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
