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
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Запобіжник для фонової синхронізації
is_syncing = False


# --- КЛАВІАТУРИ ---

def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎓 Вчити слова")],
            [KeyboardButton(text="🗂 Мої колекції")],
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
        [InlineKeyboardButton(text="🔴 Забув(ла)", callback_data=f"rate_{card_id}_0_{rep}_{ef}_{ivl}"),
         InlineKeyboardButton(text="🟡 Важко", callback_data=f"rate_{card_id}_1_{rep}_{ef}_{ivl}")],
        [InlineKeyboardButton(text="🟢 Добре", callback_data=f"rate_{card_id}_2_{rep}_{ef}_{ivl}"),
         InlineKeyboardButton(text="🔵 Легко", callback_data=f"rate_{card_id}_3_{rep}_{ef}_{ivl}")]
    ])


def get_collections_kb(decks: list):
    kb = []
    for d in decks:
        status_icon = "✅" if d['is_active'] else "❌"
        kb.append([InlineKeyboardButton(text=f"{status_icon} {d['name']}", callback_data=f"toggle_{d['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- ФОНОВА СИНХРОНІЗАЦІЯ ---
async def background_sync():
    """Фонова синхронізація без блокування бота"""
    global is_syncing
    if is_syncing:
        return

    is_syncing = True
    try:
        cards_obsidian = await asyncio.to_thread(parser.parse_cloudflare_obsidian)
        if cards_obsidian:
            await database.add_cards_to_deck(1, cards_obsidian)

        cards_csv = parser.parse_local_csv()
        if cards_csv:
            await database.add_cards_to_deck(2, cards_csv)
    except Exception as e:
        print(f"Помилка фонової синхронізації: {e}")
    finally:
        is_syncing = False


# --- ЛОГІКА ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    # Запускаємо фоново, миттєво відповідаємо
    asyncio.create_task(background_sync())

    await message.answer(
        "Привіт! Я **LexiPal 🇬🇧** — твій помічник для вивчення англійської.\nОбери дію в меню нижче 👇",
        reply_markup=get_main_menu(), parse_mode="Markdown")


@dp.message(Command("update"))
async def cmd_update(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    msg = await message.answer("🔄 Завантажую оновлення з GitHub...")
    try:
        result = subprocess.run(["git", "pull", "origin", "main"], capture_output=True, text=True, check=True)
        await msg.edit_text(f"✅ Код успішно оновлено!\n\n`{result.stdout}`\n\n♻️ Перезапускаю LexiPal...",
                            parse_mode="Markdown")
        os._exit(0)
    except Exception as e:
        await msg.edit_text(f"❌ Помилка оновлення:\n`{e}`", parse_mode="Markdown")


# --- КОЛЕКЦІЇ (НАБОРИ) ---
@dp.message(F.text == "🗂 Мої колекції")
async def cmd_collections(message: Message):
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    decks = await database.get_user_decks_status(message.from_user.id)
    await message.answer(
        "🗂 **Керування твоїми базами слів:**\nНатисни на базу, щоб увімкнути або вимкнути її в навчанні.",
        reply_markup=get_collections_kb(decks), parse_mode="Markdown")


@dp.callback_query(F.data.startswith("toggle_"))
async def toggle_collection(call: CallbackQuery):
    deck_id = int(call.data.split("_")[1])
    await database.toggle_deck_status(call.from_user.id, deck_id)
    decks = await database.get_user_decks_status(call.from_user.id)
    await call.message.edit_reply_markup(reply_markup=get_collections_kb(decks))
    await call.answer("Статус змінено!")


# --- ДОДАВАННЯ СЛІВ ЧЕРЕЗ ЧАТ ---
@dp.message(F.text.lower().startswith("додай:") | F.text.lower().startswith("/add"))
async def cmd_add_word(message: Message):
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    text = message.text[6:] if message.text.lower().startswith("додай:") else message.text[4:]
    text = text.strip()

    if " - " in text:
        parts = text.split(" - ", 1)
    elif "-" in text:
        parts = text.split("-", 1)
    elif "::" in text:
        parts = text.split("::", 1)
    else:
        return await message.answer("❌ Неправильний формат.\nНапиши так: `додай: apple - яблуко`",
                                    parse_mode="Markdown")

    front, back = parts[0].strip(), parts[1].strip()
    if not front or not back: return await message.answer("❌ Забув(ла) написати слово або переклад.")

    await database.add_personal_word(message.from_user.id, front, back)
    await message.answer(f"✅ Додано в особистий словник:\n🇬🇧 **{front}** — 🇺🇦 {back}", parse_mode="Markdown")


@dp.message(Command("my_words"))
async def cmd_my_words(message: Message):
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    words = await database.get_user_words(message.from_user.id)
    if not words: return await message.answer("📭 Твій словник поки порожній. \nНапиши: `додай: слово - переклад`")
    text = "📚 **Останні твої слова:**\n\n" + "".join([f"▪️ {w[0]} — {w[1]}\n" for w in words])
    await message.answer(text, parse_mode="Markdown")


# --- СИНХРОНІЗАЦІЯ ---
@dp.message(F.text == "🔄 Синхронізація")
@dp.message(Command("sync"))
async def cmd_sync_all(message: Message):
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    msg = await message.answer("🔄 Шукаю нові слова в Obsidian та локальній базі...")

    cards_obsidian = await asyncio.to_thread(parser.parse_cloudflare_obsidian)
    added_obsidian = await database.add_cards_to_deck(1, cards_obsidian) if cards_obsidian else 0

    cards_csv = parser.parse_local_csv()
    added_csv = await database.add_cards_to_deck(2, cards_csv) if cards_csv else 0

    await msg.edit_text(f"✅ Синхронізацію завершено!\n\n"
                        f"📘 Нових слів з Obsidian: {added_obsidian}\n"
                        f"📙 Нових слів з CSV: {added_csv}")


# --- НАВЧАННЯ ---
async def send_next_card(user_id: int, message_or_call):
    card = await database.get_due_card(user_id)
    if not card:
        text = "🎉 На сьогодні все!\nТи повторив(ла) всі слова з активних баз. Повертайся завтра!"
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
    card = await database.get_due_card(call.from_user.id)
    if not card: return await call.message.edit_text("ℹ️ Картка більше не актуальна.")
    text = f"🇬🇧 **{card['front']}**\n\n🇺🇦 {card['back']}"
    kb = get_rating_kb(card_id, card['repetitions'], card['ease_factor'], card['interval'])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


@dp.callback_query(F.data.startswith("rate_"))
async def rate_card(call: CallbackQuery):
    await call.answer()
    _, card_id, quality, rep, ef, ivl = call.data.split("_")
    new_rep, new_ef, new_ivl, next_rev = sm2.calculate_next_review(int(quality), int(rep), float(ef), int(ivl))
    await database.update_card_progress(call.from_user.id, int(card_id), new_rep, new_ef, new_ivl, next_rev)
    await send_next_card(call.from_user.id, call)


# --- СТАТИСТИКА ---
@dp.message(F.text == "📊 Статистика")
@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    # Запускаємо фоново, НЕ БЛОКУЄМО інтерфейс
    asyncio.create_task(background_sync())

    total, due, active_total = await database.get_stats(message.from_user.id)
    await message.answer(f"📊 **Твоя статистика**\n\n"
                         f"🗂 Слів у твоїх активних базах: {active_total}\n"
                         f"🧠 З них в процесі вивчення: {total}\n"
                         f"🔥 Треба повторити зараз: {due}", parse_mode="Markdown")


async def main():
    await database.init_db()
    print("LexiPal запущено і готово до роботи!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())