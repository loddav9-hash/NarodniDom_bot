import aiosqlite
import logging

DB_PATH = "narodni_dom.db"

async def init_db():
    """Создаёт таблицы для хостела."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT,
                guests INTEGER,
                room_type TEXT,
                check_in TEXT,
                check_out TEXT,
                total_price REAL,
                language TEXT DEFAULT 'en',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
    logging.info("База данных NarodniDom инициализирована")

async def save_booking(user_id: int, name: str, guests: int, room_type: str, check_in: str, check_out: str, total_price: float, language: str = 'en'):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO bookings (user_id, name, guests, room_type, check_in, check_out, total_price, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, name, guests, room_type, check_in, check_out, total_price, language)
        )
        await db.commit()

async def get_bookings():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM bookings ORDER BY created_at DESC") as cursor:
            rows = await cursor.fetchall()
            return rows