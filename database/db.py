"""
База данных на asyncpg (PostgreSQL).
Не требует системных библиотек.
"""

import os
import asyncio
import asyncpg
import json

DATABASE_URL = os.environ.get("DATABASE_URL", "")


async def get_conn():
    return await asyncpg.connect(DATABASE_URL)


async def init_db():
    conn = await get_conn()

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id          SERIAL PRIMARY KEY,
            username    TEXT UNIQUE NOT NULL,
            access_code TEXT UNIQUE NOT NULL,
            bot_token   TEXT UNIQUE NOT NULL,
            bot_name    TEXT,
            created_at  TIMESTAMP DEFAULT NOW(),
            is_active   INTEGER DEFAULT 1
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            client_id     INTEGER PRIMARY KEY,
            air_percent   REAL DEFAULT 0.17,
            air_per_kg    REAL DEFAULT 700,
            truck_percent REAL DEFAULT 0.11,
            truck_per_kg  REAL DEFAULT 350,
            manager_link  TEXT DEFAULT '@manager',
            channel_link  TEXT DEFAULT '@channel',
            welcome_text  TEXT DEFAULT 'Добро пожаловать! 👋',
            faq_json      TEXT DEFAULT '[]'
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS promocodes (
            id        SERIAL PRIMARY KEY,
            client_id INTEGER NOT NULL,
            code      TEXT NOT NULL,
            discount  INTEGER NOT NULL,
            UNIQUE(client_id, code)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            id        SERIAL PRIMARY KEY,
            client_id INTEGER NOT NULL,
            order_id  TEXT NOT NULL,
            track_num TEXT NOT NULL,
            UNIQUE(client_id, order_id)
        )
    """)

    await conn.close()
    print("✅ PostgreSQL база инициализирована")


# ── Клиенты ──

async def add_client(username, access_code, bot_token, bot_name) -> bool:
    try:
        conn = await get_conn()
        row = await conn.fetchrow(
            "INSERT INTO clients (username, access_code, bot_token, bot_name) VALUES ($1,$2,$3,$4) RETURNING id",
            username.lower().lstrip("@"), access_code.upper(), bot_token, bot_name
        )
        await conn.execute("INSERT INTO bot_settings (client_id) VALUES ($1)", row["id"])
        await conn.close()
        return True
    except Exception as e:
        print(f"add_client error: {e}")
        return False


async def get_client_by_code_and_username(code, username):
    conn = await get_conn()
    row = await conn.fetchrow(
        "SELECT * FROM clients WHERE access_code=$1 AND username=$2 AND is_active=1",
        code.upper(), username.lower().lstrip("@")
    )
    await conn.close()
    return dict(row) if row else None


async def get_all_clients():
    conn = await get_conn()
    rows = await conn.fetch("SELECT id, username, bot_name, is_active, created_at FROM clients ORDER BY id DESC")
    await conn.close()
    return [dict(r) for r in rows]


async def deactivate_client(username) -> bool:
    conn = await get_conn()
    result = await conn.execute("UPDATE clients SET is_active=0 WHERE username=$1", username.lower())
    await conn.close()
    return result != "UPDATE 0"


async def restore_client(username) -> bool:
    conn = await get_conn()
    result = await conn.execute("UPDATE clients SET is_active=1 WHERE username=$1", username.lower())
    await conn.close()
    return result != "UPDATE 0"


async def delete_client(username) -> bool:
    conn = await get_conn()
    row = await conn.fetchrow("SELECT id FROM clients WHERE username=$1", username.lower())
    if not row:
        await conn.close()
        return False
    cid = row["id"]
    await conn.execute("DELETE FROM promocodes WHERE client_id=$1", cid)
    await conn.execute("DELETE FROM tracks WHERE client_id=$1", cid)
    await conn.execute("DELETE FROM bot_settings WHERE client_id=$1", cid)
    await conn.execute("DELETE FROM clients WHERE id=$1", cid)
    await conn.close()
    return True


# ── Настройки ──

async def get_settings(client_id) -> dict:
    conn = await get_conn()
    row = await conn.fetchrow("SELECT * FROM bot_settings WHERE client_id=$1", client_id)
    await conn.close()
    return dict(row) if row else {}


async def update_settings(client_id, **kwargs) -> bool:
    if not kwargs:
        return False
    fields = ", ".join(f"{k}=${i+2}" for i, k in enumerate(kwargs))
    values = [client_id] + list(kwargs.values())
    conn = await get_conn()
    await conn.execute(f"UPDATE bot_settings SET {fields} WHERE client_id=$1", *values)
    await conn.close()
    return True


# ── Промокоды ──

async def add_promo(client_id, code, discount) -> bool:
    try:
        conn = await get_conn()
        await conn.execute(
            "INSERT INTO promocodes (client_id, code, discount) VALUES ($1,$2,$3) ON CONFLICT (client_id, code) DO UPDATE SET discount=EXCLUDED.discount",
            client_id, code.upper(), discount
        )
        await conn.close()
        return True
    except Exception as e:
        print(f"add_promo error: {e}")
        return False


async def delete_promo(client_id, code) -> bool:
    conn = await get_conn()
    result = await conn.execute("DELETE FROM promocodes WHERE client_id=$1 AND code=$2", client_id, code.upper())
    await conn.close()
    return result != "DELETE 0"


async def get_promos(client_id) -> list:
    conn = await get_conn()
    rows = await conn.fetch("SELECT code, discount FROM promocodes WHERE client_id=$1", client_id)
    await conn.close()
    return [dict(r) for r in rows]


async def check_promo(client_id, code):
    conn = await get_conn()
    row = await conn.fetchrow("SELECT discount FROM promocodes WHERE client_id=$1 AND code=$2", client_id, code.upper())
    await conn.close()
    return row["discount"] if row else None


# ── Треки ──

async def add_track(client_id, order_id, track_num) -> bool:
    try:
        conn = await get_conn()
        await conn.execute(
            "INSERT INTO tracks (client_id, order_id, track_num) VALUES ($1,$2,$3) ON CONFLICT (client_id, order_id) DO UPDATE SET track_num=EXCLUDED.track_num",
            client_id, order_id, track_num
        )
        await conn.close()
        return True
    except Exception as e:
        print(f"add_track error: {e}")
        return False


async def get_track(client_id, order_id):
    conn = await get_conn()
    row = await conn.fetchrow("SELECT track_num FROM tracks WHERE client_id=$1 AND order_id=$2", client_id, order_id)
    await conn.close()
    return row["track_num"] if row else None


async def get_all_tracks(client_id) -> list:
    conn = await get_conn()
    rows = await conn.fetch("SELECT order_id, track_num FROM tracks WHERE client_id=$1", client_id)
    await conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    asyncio.run(init_db())


async def update_bot_token(client_id: int, token: str) -> bool:
    conn = await get_conn()
    await conn.execute("UPDATE clients SET bot_token=$1 WHERE id=$2", token, client_id)
    await conn.close()
    return True


async def get_client_by_id(client_id: int):
    conn = await get_conn()
    row = await conn.fetchrow("SELECT * FROM clients WHERE id=$1", client_id)
    await conn.close()
    return dict(row) if row else None
