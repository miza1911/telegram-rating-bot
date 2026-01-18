import asyncio
import re
from datetime import datetime, date
from collections import defaultdict

from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command, Text
from aiogram.enums import ParseMode
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

TOKEN = "PASTE_YOUR_TOKEN_HERE"

bot = Bot(TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ──────────────── КОНСТАНТЫ ────────────────
DAILY_PLUS = 100
DAILY_MINUS = 50
SHAME_LIMIT = -500

LOW_BALANCE_PHRASES = [
    "😬 Осторожно, баллы на исходе",
    "🪫 Ты почти пуст",
    "🐭 Балансовая диета",
    "⚠️ Ещё немного — и всё",
    "🥲 Баллы тают",
    "📉 Финансовый кризис",
    "🧮 Математика плачет",
    "💸 Почти банкрот",
    "😏 Щедрость дорого стоит",
    "🪦 Тут похоронены баллы",
    "🫠 Осталось совсем чуть-чуть",
    "😮‍💨 Последние силы",
    "📛 Балльный SOS",
    "🪙 Мелочь звенит",
    "😈 Баланс страдает",
    "🥴 Почти ноль",
    "🧠 Подумай, прежде чем тратить",
    "🫣 Стыдно мало",
    "🦴 Грызёшь остатки",
    "⚰️ Баллам плохо"
]

# ──────────────── ХРАНИЛИЩЕ ────────────────
users = defaultdict(lambda: {
    "rating": 0,
    "given": defaultdict(int),  # кому сколько дал
    "plus_left": DAILY_PLUS,
    "minus_left": DAILY_MINUS,
    "daily_delta": 0,
    "last_reset": date.today(),
    "given_total": 0,
    "taken_total": 0
})


# ──────────────── ВСПОМОГАТЕЛЬНОЕ ────────────────
def reset_if_new_day(uid):
    u = users[uid]
    if u["last_reset"] != date.today():
        u["plus_left"] = DAILY_PLUS
        u["minus_left"] = DAILY_MINUS
        u["daily_delta"] = 0
        u["last_reset"] = date.today()


def keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Моя статистика"), KeyboardButton(text="🏆 Общий рейтинг")],
            [KeyboardButton(text="💰 Самые щедрые"), KeyboardButton(text="😈 Хейтеры")],
            [KeyboardButton(text="📅 Статистика за сутки")],
            [KeyboardButton(text="📜 Правила")]
        ],
        resize_keyboard=True
    )


# ──────────────── СТАРТ ────────────────
@router.message(Command("start"))
async def start(m: types.Message):
    await m.answer("✅ Бот жив. Рейтинг работает.", reply_markup=keyboard())


# ──────────────── РЕЙТИНГ ЧЕРЕЗ REPLY ────────────────
@router.message()
async def rating_handler(m: types.Message):
    if not m.reply_to_message:
        return

    match = re.search(r'([+-]\d+)', m.text or "")
    if not match:
        return

    amount = int(match.group(1))
    giver = m.from_user.id
    receiver = m.reply_to_message.from_user.id

    if giver == receiver:
        await m.reply("🤡 Сам себе — запрещено.")
        return

    reset_if_new_day(giver)
    reset_if_new_day(receiver)

    g = users[giver]
    r = users[receiver]

    # ───── ПЛЮС ─────
    if amount > 0:
        if g["plus_left"] < amount:
            await m.reply("😏 Баллов не хватит, щедрец.")
            return

        g["plus_left"] -= amount
        g["given"][receiver] += amount
        g["given_total"] += amount

        r["rating"] += amount
        r["daily_delta"] += amount

    # ───── МИНУС ─────
    else:
        take = abs(amount)

        # сначала бесплатные минусы
        free = min(g["minus_left"], take)
        g["minus_left"] -= free
        take -= free

        # возврат плюсов
        if take > 0:
            if g["given"][receiver] < take:
                await m.reply("😈 Сначала дай — потом забирай.")
                return
            g["given"][receiver] -= take
            g["plus_left"] += take

        r["rating"] -= abs(amount)
        r["daily_delta"] -= abs(amount)
        g["taken_total"] += abs(amount)

    if g["plus_left"] < 50:
        import random
        await m.reply(random.choice(LOW_BALANCE_PHRASES))

    if r["daily_delta"] <= SHAME_LIMIT:
        await m.answer(f"🧻 <b>ПОЗОР</b>\n{m.reply_to_message.from_user.first_name} набрал больше −500 за сутки.")


# ──────────────── КОМАНДЫ / КНОПКИ ────────────────
@router.message(Command("me"))
@router.message(Text("📊 Моя статистика"))
async def me(m: types.Message):
    u = users[m.from_user.id]
    reset_if_new_day(m.from_user.id)
    await m.answer(
        f"📊 <b>Твоя статистика</b>\n"
        f"⭐ Рейтинг: {u['rating']}\n"
        f"➕ Осталось плюсов: {u['plus_left']}\n"
        f"➖ Минус-баланс: {u['minus_left']}\n"
        f"💰 Отдал всего: {u['given_total']}\n"
        f"😈 Забрал всего: {u['taken_total']}"
    )


@router.message(Command("top"))
@router.message(Text("🏆 Общий рейтинг"))
async def top(m: types.Message):
    top = sorted(users.items(), key=lambda x: x[1]["rating"], reverse=True)[:10]
    text = "🏆 <b>Топ рейтинга</b>\n"
    for i, (uid, u) in enumerate(top, 1):
        text += f"{i}. {uid} — {u['rating']}\n"
    await m.answer(text)


@router.message(Command("rich"))
@router.message(Text("💰 Самые щедрые"))
async def rich(m: types.Message):
    top = sorted(users.items(), key=lambda x: x[1]["given_total"], reverse=True)[:10]
    text = "💰 <b>Самые щедрые</b>\n"
    for i, (uid, u) in enumerate(top, 1):
        text += f"{i}. {uid} — {u['given_total']}\n"
    await m.answer(text)


@router.message(Command("hate"))
@router.message(Text("😈 Хейтеры"))
async def hate(m: types.Message):
    top = sorted(users.items(), key=lambda x: x[1]["taken_total"], reverse=True)[:10]
    text = "😈 <b>Хейтеры</b>\n"
    for i, (uid, u) in enumerate(top, 1):
        text += f"{i}. {uid} — {u['taken_total']}\n"
    await m.answer(text)


@router.message(Command("day"))
@router.message(Text("📅 Статистика за сутки"))
async def day(m: types.Message):
    text = "📅 <b>Сутки</b>\n"
    for uid, u in users.items():
        if u["daily_delta"] != 0:
            text += f"{uid}: {u['daily_delta']}\n"
    await m.answer(text or "😴 Сегодня тихо.")


@router.message(Command("rules"))
@router.message(Text("📜 Правила"))
async def rules(m: types.Message):
    await m.answer(
        "📜 <b>Система баллов</b>\n\n"
        "➕ У каждого 100 плюсов в сутки\n"
        "➖ 50 минусов — бесплатно\n"
        "♻️ Потом минусы возвращают плюсы\n"
        "🚫 Нельзя забирать у тех, кому не давал\n"
        "🤡 Сам себе — нельзя\n"
        
    )


# ──────────────── ЗАПУСК ────────────────
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
