import os
import asyncio
import subprocess
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (Message, InlineKeyboardMarkup, InlineKeyboardButton,
                           CallbackQuery, ReplyKeyboardMarkup, KeyboardButton)
from aiogram.enums import ChatAction

import database
import parser
import sm2

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Отримуємо ID адміна з .env (якщо немає, ставимо 0, щоб ніхто не мав доступу)
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# --- КЛАВІАТУРИ ---

def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎓 Вчити слова")],
            [KeyboardButton(text="🔄 Синхронізація"), KeyboardButton(text="📊 Статистика")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )


def get_show_answer_kb(card_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👀 Показати переклад", callback_data=f"show_{card_id}")]
    ])


def get_rating_kb(card_id: int, rep, ef, ivl):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔴 Забув(ла)", callback_data=f"rate_{card_id}_0_{rep}_{ef}_{ivl}"),
            InlineKeyboardButton(text="🟡 Важко", callback_data=f"rate_{card_id}_1_{rep}_{ef}_{ivl}")
        ],
        [
            InlineKeyboardButton(text="🟢 Добре", callback_data=f"rate_{card_id}_2_{rep}_{ef}_{ivl}"),
            InlineKeyboardButton(text="🔵 Легко", callback_data=f"rate_{card_id}_3_{rep}_{ef}_{ivl}")
        ]
    ])


# --- ЛОГІКА ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("Привіт! Я **LexiPal 🇬🇧** — твій особистий помічник для вивчення англійської.\n"
                         "Обери дію в меню нижче 👇",
                         reply_markup=get_main_menu(), parse_mode="Markdown")


# --- АДМІНКА: АВТООНОВЛЕННЯ ---
@dp.message(Command("update"))
async def cmd_update(message: Message):
    if message.from_user.id != ADMIN_ID:
        return  # Ігноруємо, якщо пише не адмін

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    msg = await message.answer("🔄 Завантажую оновлення з GitHub...")

    try:
        result = subprocess.run(["git", "pull", "origin", "main"], capture_output=True, text=True, check=True)
        await msg.edit_text(f"✅ Код успішно оновлено!\n\n`{result.stdout}`\n\n♻️ Перезапускаю LexiPal...",
                            parse_mode="Markdown")
        # Вбиваємо процес. Docker автоматично підніме його з новим кодом.
        os._exit(0)
    except Exception as e:
        await msg.edit_text(f"❌ Помилка оновлення:\n`{e}`", parse_mode="Markdown")


# --- СИНХРОНІЗАЦІЯ ---
@dp.message(F.text == "🔄 Синхронізація")
@dp.message(Command("sync"))
async def cmd_sync_all(message: Message):
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    msg = await message.answer("🔄 Шукаю нові слова в Obsidian та локальній базі...")

    cards_obsidian = await asyncio.to_thread(parser.parse_cloudflare_obsidian)
    added_obsidian = await database.add_cards_to_db(cards_obsidian) if cards_obsidian else 0

    cards_csv = parser.parse_local_csv()
    added_csv = await database.add_cards_to_db(cards_csv) if cards_csv else 0

    total_added = added_obsidian + added_csv

    await msg.edit_text(f"✅ Синхронізацію завершено!\n\n"
                        f"☁️ Значень в Obsidian: {len(cards_obsidian) if cards_obsidian else 0}\n"
                        f"📄 Значень у CSV: {len(cards_csv)}\n"
                        f"🆕 Нових слів додано: {total_added}")


# --- НАВЧАННЯ ---
async def send_next_card(user_id: int, message_or_call):
    card = await database.get_due_card(user_id)

    if not card:
        text = "🎉 На сьогодні все! Ти повторив(ла) всі слова.\nПовертайся завтра або натисни «Синхронізація»."
        if isinstance(message_or_call, Message):
            await message_or_call.answer(text, reply_markup=get_main_menu())
        else:
            await message_or_call.message.edit_text(text)
        return

    text = f"🇬🇧 **{card['front']}**"
    kb = get_show_answer_kb(card['id'])

    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await message_or_call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


@dp.message(F.text == "🎓 Вчити слова")
@dp.message(Command("learn"))
async def cmd_learn(message: Message):
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    await send_next_card(message.from_user.id, message)


@dp.callback_query(F.data.startswith("show_"))
async def show_answer(call: CallbackQuery):
    await call.answer()
    card_id = int(call.data.split("_")[1])
    user_id = call.from_user.id
    card = await database.get_due_card(user_id)

    if not card:
        await call.message.edit_text("ℹ️ Картка більше не актуальна.")
        return

    text = f"🇬🇧 **{card['front']}**\n\n🇺🇦 {card['back']}"
    kb = get_rating_kb(card_id, card['repetitions'], card['ease_factor'], card['interval'])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


@dp.callback_query(F.data.startswith("rate_"))
async def rate_card(call: CallbackQuery):
    await call.answer()
    _, card_id, quality, rep, ef, ivl = call.data.split("_")

    new_rep, new_ef, new_ivl, next_rev = sm2.calculate_next_review(
        int(quality), int(rep), float(ef), int(ivl)
    )

    await database.update_card_progress(
        call.from_user.id, int(card_id), new_rep, new_ef, new_ivl, next_rev
    )

    await send_next_card(call.from_user.id, call)


# --- СТАТИСТИКА ---
@dp.message(F.text == "📊 Статистика")
@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    total, due = await database.get_stats(message.from_user.id)
    await message.answer(f"📊 **Твоя статистика**\n\n"
                         f"🧠 Слів у процесі вивчення: {total}\n"
                         f"🔥 Треба повторити зараз: {due}", parse_mode="Markdown")


async def main():
    await database.init_db()
    print("LexiPal запущено і готово до роботи!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())