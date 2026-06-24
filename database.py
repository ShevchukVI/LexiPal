import aiosqlite
from datetime import datetime

DB_NAME = "data/flashcards.db"


async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS cards
                            (
                                id
                                INTEGER
                                PRIMARY
                                KEY
                                AUTOINCREMENT,
                                front
                                TEXT
                                UNIQUE,
                                back
                                TEXT
                            )''')

        await db.execute('''CREATE TABLE IF NOT EXISTS decks
                            (
                                id
                                INTEGER
                                PRIMARY
                                KEY
                                AUTOINCREMENT,
                                name
                                TEXT
                                UNIQUE,
                                owner_id
                                INTEGER
                                DEFAULT
                                0
                            )''')

        await db.execute('''CREATE TABLE IF NOT EXISTS deck_cards
        (
            deck_id
            INTEGER,
            card_id
            INTEGER,
            PRIMARY
            KEY
                            (
            deck_id,
            card_id
                            ))''')

        await db.execute('''CREATE TABLE IF NOT EXISTS user_decks
        (
            user_id
            INTEGER,
            deck_id
            INTEGER,
            is_active
            INTEGER
            DEFAULT
            1,
            PRIMARY
            KEY
                            (
            user_id,
            deck_id
                            ))''')

        await db.execute('''CREATE TABLE IF NOT EXISTS user_progress
        (
            user_id
            INTEGER,
            card_id
            INTEGER,
            repetitions
            INTEGER
            DEFAULT
            0,
            ease_factor
            REAL
            DEFAULT
            2.5,
            interval
            INTEGER
            DEFAULT
            0,
            next_review
            TEXT,
            PRIMARY
            KEY
                            (
            user_id,
            card_id
                            ))''')

        await db.execute('INSERT OR IGNORE INTO decks (id, name, owner_id) VALUES (1, "📘 Obsidian (Твій словник)", 0)')
        await db.execute('INSERT OR IGNORE INTO decks (id, name, owner_id) VALUES (2, "📙 Базовий словник CSV", 0)')
        await db.commit()


async def ensure_user_decks(user_id: int):
    """Гарантує, що у користувача є особиста база і він підписаний на глобальні."""
    async with aiosqlite.connect(DB_NAME) as db:
        # Створюємо особисту базу, якщо нема
        cursor = await db.execute('SELECT id FROM decks WHERE owner_id = ?', (user_id,))
        deck = await cursor.fetchone()
        if not deck:
            cursor = await db.execute('INSERT INTO decks (name, owner_id) VALUES (?, ?)', ("📗 Особисті слова", user_id))
            deck_id = cursor.lastrowid
            await db.execute('INSERT INTO user_decks (user_id, deck_id, is_active) VALUES (?, ?, 1)',
                             (user_id, deck_id))

        # Авто-підписка на глобальні бази
        await db.execute(
            'INSERT OR IGNORE INTO user_decks (user_id, deck_id, is_active) SELECT ?, id, 1 FROM decks WHERE owner_id = 0',
            (user_id,))
        await db.commit()


async def add_cards_to_deck(deck_id: int, cards_list: list):
    added_count = 0
    async with aiosqlite.connect(DB_NAME) as db:
        for card in cards_list:
            try:
                cursor = await db.execute('INSERT INTO cards (front, back) VALUES (?, ?)',
                                          (card['front'], card['back']))
                card_id = cursor.lastrowid
            except aiosqlite.IntegrityError:
                cursor = await db.execute('SELECT id FROM cards WHERE front = ?', (card['front'],))
                card_id = (await cursor.fetchone())[0]

            try:
                await db.execute('INSERT INTO deck_cards (deck_id, card_id) VALUES (?, ?)', (deck_id, card_id))
                added_count += 1
            except aiosqlite.IntegrityError:
                pass
        await db.commit()
    return added_count


async def add_personal_word(user_id: int, front: str, back: str):
    await ensure_user_decks(user_id)
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('SELECT id FROM decks WHERE owner_id = ?', (user_id,))
        deck_id = (await cursor.fetchone())[0]
    await add_cards_to_deck(deck_id, [{'front': front, 'back': back}])


async def get_user_decks_status(user_id: int):
    await ensure_user_decks(user_id)
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('''
                              SELECT d.id, d.name, ud.is_active
                              FROM decks d
                                       JOIN user_decks ud ON d.id = ud.deck_id
                              WHERE ud.user_id = ?
                                AND (d.owner_id = 0 OR d.owner_id = ?)
                              ''', (user_id, user_id)) as cursor:
            return await cursor.fetchall()


async def toggle_deck_status(user_id: int, deck_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            'UPDATE user_decks SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE user_id = ? AND deck_id = ?',
            (user_id, deck_id))
        await db.commit()


async def get_user_words(user_id: int):
    await ensure_user_decks(user_id)
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('SELECT id FROM decks WHERE owner_id = ?', (user_id,))
        deck_id = (await cursor.fetchone())[0]
        async with db.execute('''
                              SELECT c.front, c.back
                              FROM cards c
                                       JOIN deck_cards dc ON c.id = dc.card_id
                              WHERE dc.deck_id = ?
                              ORDER BY c.id DESC LIMIT 50
                              ''', (deck_id,)) as cursor:
            return await cursor.fetchall()


async def get_due_card(user_id: int):
    await ensure_user_decks(user_id)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        # 1. Слова, які вже час повторювати
        async with db.execute('''
                              SELECT c.id, c.front, c.back, up.repetitions, up.ease_factor, up.interval
                              FROM user_progress up
                                       JOIN cards c ON up.card_id = c.id
                              WHERE up.user_id = ?
                                AND up.next_review <= ?
                                AND c.id IN (SELECT dc.card_id
                                             FROM deck_cards dc
                                                      JOIN user_decks ud ON dc.deck_id = ud.deck_id
                                             WHERE ud.user_id = ?
                                               AND ud.is_active = 1)
                              ORDER BY up.next_review ASC LIMIT 1
                              ''', (user_id, now, user_id)) as cursor:
            card = await cursor.fetchone()
        if card: return card

        # 2. Нові слова
        async with db.execute('''
                              SELECT c.id, c.front, c.back, 0 as repetitions, 2.5 as ease_factor, 0 as interval
                              FROM cards c
                              WHERE c.id NOT IN (SELECT card_id FROM user_progress WHERE user_id = ?)
                                AND c.id IN (
                                  SELECT dc.card_id FROM deck_cards dc
                                  JOIN user_decks ud ON dc.deck_id = ud.deck_id
                                  WHERE ud.user_id = ?
                                AND ud.is_active = 1
                                  )
                                  LIMIT 1
                              ''', (user_id, user_id)) as cursor:
            return await cursor.fetchone()


async def update_card_progress(user_id, card_id, repetitions, ease_factor, interval, next_review):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
                         INSERT INTO user_progress (user_id, card_id, repetitions, ease_factor, interval, next_review)
                         VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(user_id, card_id) DO
                         UPDATE SET
                             repetitions=excluded.repetitions, ease_factor=excluded.ease_factor,
                             interval =excluded.interval, next_review=excluded.next_review
                         ''', (user_id, card_id, repetitions, ease_factor, interval, next_review))
        await db.commit()


async def get_stats(user_id: int):
    await ensure_user_decks(user_id)
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT COUNT(*) FROM user_progress WHERE user_id = ?', (user_id,)) as cursor:
            total_learned = (await cursor.fetchone())[0]
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        async with db.execute('SELECT COUNT(*) FROM user_progress WHERE user_id = ? AND next_review <= ?',
                              (user_id, now)) as cursor:
            due_today = (await cursor.fetchone())[0]
        async with db.execute('''
                              SELECT COUNT(DISTINCT dc.card_id)
                              FROM deck_cards dc
                                       JOIN user_decks ud ON dc.deck_id = ud.deck_id
                              WHERE ud.user_id = ?
                                AND ud.is_active = 1
                              ''', (user_id,)) as cursor:
            total_in_active_decks = (await cursor.fetchone())[0]
    return total_learned, due_today, total_in_active_decks