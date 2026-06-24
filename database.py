import aiosqlite
from datetime import datetime

DB_NAME = "data/flashcards.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS cards (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            front TEXT UNIQUE,
                            back TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS user_progress (
                            user_id INTEGER,
                            card_id INTEGER,
                            repetitions INTEGER DEFAULT 0,
                            ease_factor REAL DEFAULT 2.5,
                            interval INTEGER DEFAULT 0,
                            next_review TEXT,
                            PRIMARY KEY (user_id, card_id))''')
        await db.commit()

async def add_cards_to_db(cards_list):
    added_count = 0
    async with aiosqlite.connect(DB_NAME) as db:
        for card in cards_list:
            try:
                await db.execute('INSERT INTO cards (front, back) VALUES (?, ?)',
                                 (card['front'], card['back']))
                added_count += 1
            except aiosqlite.IntegrityError:
                pass # Вже є в базі
        await db.commit()
    return added_count

async def get_due_card(user_id: int):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        # 1. Шукаємо слова на повторення
        async with db.execute('''
            SELECT c.id, c.front, c.back, up.repetitions, up.ease_factor, up.interval 
            FROM cards c
            JOIN user_progress up ON c.id = up.card_id
            WHERE up.user_id = ? AND up.next_review <= ?
            ORDER BY up.next_review ASC LIMIT 1
        ''', (user_id, now)) as cursor:
            card = await cursor.fetchone()
        if card: return card

        # 2. Якщо старих немає, даємо нове слово
        async with db.execute('''
            SELECT c.id, c.front, c.back, 0 as repetitions, 2.5 as ease_factor, 0 as interval 
            FROM cards c
            WHERE c.id NOT IN (SELECT card_id FROM user_progress WHERE user_id = ?)
            LIMIT 1
        ''', (user_id,)) as cursor:
            return await cursor.fetchone()

async def update_card_progress(user_id, card_id, repetitions, ease_factor, interval, next_review):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            INSERT INTO user_progress (user_id, card_id, repetitions, ease_factor, interval, next_review)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, card_id) DO UPDATE SET
                repetitions=excluded.repetitions,
                ease_factor=excluded.ease_factor,
                interval=excluded.interval,
                next_review=excluded.next_review
        ''', (user_id, card_id, repetitions, ease_factor, interval, next_review))
        await db.commit()

async def get_stats(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT COUNT(*) FROM user_progress WHERE user_id = ?', (user_id,)) as cursor:
            total_learned = (await cursor.fetchone())[0]
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        async with db.execute('SELECT COUNT(*) FROM user_progress WHERE user_id = ? AND next_review <= ?', (user_id, now)) as cursor:
            due_today = (await cursor.fetchone())[0]
    return total_learned, due_today


async def add_single_card_and_link(user_id: int, front: str, back: str):
    """Додає одне слово і відразу прив'язує його до прогресу конкретного користувача"""
    async with aiosqlite.connect(DB_NAME) as db:
        # 1. Пробуємо додати слово в загальну базу карток
        try:
            cursor = await db.execute('INSERT INTO cards (front, back) VALUES (?, ?)', (front, back))
            card_id = cursor.lastrowid
        except aiosqlite.IntegrityError:
            # Якщо слово вже є в базі, просто дістаємо його ID
            cursor = await db.execute('SELECT id FROM cards WHERE front = ?', (front,))
            card_id = (await cursor.fetchone())[0]

        # 2. Робимо запис в user_progress з нульовим прогресом (щоб слово випало на вивчення)
        try:
            await db.execute('''
                             INSERT INTO user_progress (user_id, card_id, repetitions, ease_factor, interval, next_review)
                             VALUES (?, ?, 0, 2.5, 0, ?)
                             ''', (user_id, card_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        except aiosqlite.IntegrityError:
            pass  # Якщо вона вже вчить це слово, нічого не робимо

        await db.commit()
    return True


async def get_user_words(user_id: int):
    """Повертає список слів, які користувач додав/вивчає"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('''
                              SELECT c.front, c.back
                              FROM cards c
                                       JOIN user_progress up ON c.id = up.card_id
                              WHERE up.user_id = ?
                              ORDER BY up.next_review DESC LIMIT 50
                              ''', (user_id,)) as cursor:
            return await cursor.fetchall()