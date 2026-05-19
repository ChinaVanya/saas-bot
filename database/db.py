import os
import asyncio
import asyncpg
import json

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL не задан! Добавь в переменные Railway.")
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id          SERIAL PRIMARY KEY,
                username    TEXT UNIQUE NOT NULL,
                access_code TEXT UNIQUE NOT NULL,
                bot_token   TEXT UNIQUE NOT NULL,
                bot_name    TEXT,
                created_at  TIMESTAMP DEFAULT NOW(),
                is_active   INTEGER DEFAULT 1,
                client_type TEXT DEFAULT 'cargo'
            )
        """)
        try:
            await conn.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS client_type TEXT DEFAULT 'cargo'")
        except Exception:
            pass

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                client_id       INTEGER PRIMARY KEY,
                air_percent     REAL DEFAULT 0.17,
                air_per_kg      REAL DEFAULT 700,
                truck_percent   REAL DEFAULT 0.11,
                truck_per_kg    REAL DEFAULT 350,
                manager_link    TEXT DEFAULT '@manager',
                channel_link    TEXT DEFAULT '@channel',
                welcome_text    TEXT DEFAULT 'Добро пожаловать! 👋',
                faq_json        TEXT DEFAULT '[]',
                express_percent REAL DEFAULT 0.25,
                express_per_kg  REAL DEFAULT 1200,
                tariff_enabled  TEXT DEFAULT '{"air":true,"truck":true,"express":true,"normal":true}',
                tracking_site   TEXT DEFAULT 'track24',
                currency        TEXT DEFAULT 'RUB',
                track17_api     TEXT DEFAULT '',
                openai_api      TEXT DEFAULT '',
                ai_recognition  INTEGER DEFAULT 0,
                msg_welcome     TEXT DEFAULT '',
                msg_calc        TEXT DEFAULT '',
                msg_order       TEXT DEFAULT '',
                msg_support     TEXT DEFAULT '',
                msg_welcome_img TEXT DEFAULT '',
                msg_calc_img    TEXT DEFAULT '',
                msg_order_img   TEXT DEFAULT '',
                msg_support_img TEXT DEFAULT '',
                normal_percent  REAL DEFAULT 0.08,
                normal_per_kg   REAL DEFAULT 200,
                tariff_mode     TEXT DEFAULT 'mode1'
            )
        """)

        new_columns = [
            ("normal_percent",      "REAL DEFAULT 0.08"),
            ("normal_per_kg",       "REAL DEFAULT 200"),
            ("tariff_mode",         "TEXT DEFAULT 'mode1'"),
            ("currency",            "TEXT DEFAULT 'RUB'"),
            ("tracking_site",       "TEXT DEFAULT 'track24'"),
            ("track17_api",         "TEXT DEFAULT ''"),
            ("openai_api",          "TEXT DEFAULT ''"),
            ("ai_recognition",      "INTEGER DEFAULT 0"),
            ("msg_welcome",         "TEXT DEFAULT ''"),
            ("msg_calc",            "TEXT DEFAULT ''"),
            ("msg_order",           "TEXT DEFAULT ''"),
            ("msg_support",         "TEXT DEFAULT ''"),
            ("msg_welcome_img",     "TEXT DEFAULT ''"),
            ("msg_calc_img",        "TEXT DEFAULT ''"),
            ("msg_order_img",       "TEXT DEFAULT ''"),
            ("msg_support_img",     "TEXT DEFAULT ''"),
            ("express_percent",     "REAL DEFAULT 0.25"),
            ("express_per_kg",      "REAL DEFAULT 1200"),
            ("tariff_enabled",      "TEXT DEFAULT '{}'"),
            ("shop_products",       "TEXT DEFAULT '[]'"),
            ("shop_delivery_price", "REAL DEFAULT 350"),
            ("shop_delivery_days",  "INTEGER DEFAULT 7"),
            ("shop_express_price",  "REAL DEFAULT 700"),
            ("shop_express_days",   "INTEGER DEFAULT 2"),
            ("shop_free_from",      "REAL DEFAULT 0"),
            ("shop_normal_price",   "REAL DEFAULT 350"),
            ("shop_normal_days",    "INTEGER DEFAULT 14"),
            ("shop_templates",      "TEXT DEFAULT '[]'"),
            ("shop_msg_welcome",    "TEXT DEFAULT ''"),
            ("shop_msg_catalog",    "TEXT DEFAULT ''"),
            ("shop_msg_delivery",   "TEXT DEFAULT ''"),
            ("shop_msg_order",      "TEXT DEFAULT ''"),
            ("shop_msg_support",    "TEXT DEFAULT ''"),
        ]
        for col, definition in new_columns:
            try:
                await conn.execute(f"ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS {col} {definition}")
            except Exception:
                pass

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

    print("✅ PostgreSQL база инициализирована")


async def add_client(username, access_code, bot_token, bot_name, client_type='cargo'):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO clients (username, access_code, bot_token, bot_name, client_type) "
                "VALUES ($1,$2,$3,$4,$5) RETURNING id",
                username.lower().lstrip("@"), access_code.upper(), bot_token, bot_name, client_type
            )
            await conn.execute("INSERT INTO bot_settings (client_id) VALUES ($1)", row["id"])
        return True
    except Exception as e:
        print(f"add_client error: {e}")
        return False


async def get_client_by_code(code: str):
    """Ищет клиента только по коду доступа."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM clients WHERE access_code=$1 AND is_active=1",
            code.upper()
        )
    return dict(row) if row else None


async def get_all_clients():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, username, bot_name, is_active, created_at, client_type FROM clients ORDER BY id DESC"
        )
    return [dict(r) for r in rows]


async def get_all_active_bots():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, bot_name, bot_token, client_type FROM clients "
            "WHERE is_active=1 AND bot_token NOT LIKE 'pending_%'"
        )
    return [dict(r) for r in rows]


async def deactivate_client(username):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("UPDATE clients SET is_active=0 WHERE username=$1", username.lower())
    return result != "UPDATE 0"


async def restore_client(username):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("UPDATE clients SET is_active=1 WHERE username=$1", username.lower())
    return result != "UPDATE 0"


async def delete_client(username):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM clients WHERE username=$1", username.lower())
        if not row:
            return False
        cid = row["id"]
        await conn.execute("DELETE FROM promocodes WHERE client_id=$1", cid)
        await conn.execute("DELETE FROM tracks WHERE client_id=$1", cid)
        await conn.execute("DELETE FROM bot_settings WHERE client_id=$1", cid)
        await conn.execute("DELETE FROM clients WHERE id=$1", cid)
    return True


async def update_bot_token(client_id: int, token: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE clients SET bot_token=$1 WHERE id=$2", token, client_id)
    return True


async def get_client_by_id(client_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM clients WHERE id=$1", client_id)
    return dict(row) if row else None


async def get_settings(client_id):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM bot_settings WHERE client_id=$1", client_id)
    return dict(row) if row else {}


async def update_settings(client_id, **kwargs):
    if not kwargs:
        return False
    valid = {k: v for k, v in kwargs.items() if v is not None}
    if not valid:
        return False
    fields = ", ".join(f"{k}=${i+2}" for i, k in enumerate(valid))
    values = [client_id] + list(valid.values())
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(f"UPDATE bot_settings SET {fields} WHERE client_id=$1", *values)
        except Exception as e:
            print(f"update_settings error: {e}")
            return False
    return True


async def add_promo(client_id, code, discount):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO promocodes (client_id, code, discount) VALUES ($1,$2,$3) "
                "ON CONFLICT (client_id, code) DO UPDATE SET discount=EXCLUDED.discount",
                client_id, code.upper(), discount
            )
        return True
    except Exception as e:
        print(f"add_promo error: {e}")
        return False


async def delete_promo(client_id, code):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM promocodes WHERE client_id=$1 AND code=$2", client_id, code.upper()
        )
    return result != "DELETE 0"


async def get_promos(client_id):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT code, discount FROM promocodes WHERE client_id=$1", client_id)
    return [dict(r) for r in rows]


async def check_promo(client_id, code):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT discount FROM promocodes WHERE client_id=$1 AND code=$2",
            client_id, code.upper()
        )
    return row["discount"] if row else None


async def add_track(client_id, order_id, track_num):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO tracks (client_id, order_id, track_num) VALUES ($1,$2,$3) "
                "ON CONFLICT (client_id, order_id) DO UPDATE SET track_num=EXCLUDED.track_num",
                client_id, order_id, track_num
            )
        return True
    except Exception as e:
        print(f"add_track error: {e}")
        return False


async def get_track(client_id, order_id):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT track_num FROM tracks WHERE client_id=$1 AND order_id=$2", client_id, order_id
        )
    return row["track_num"] if row else None


async def get_all_tracks(client_id):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT order_id, track_num FROM tracks WHERE client_id=$1", client_id
        )
    return [dict(r) for r in rows]


if __name__ == "__main__":
    asyncio.run(init_db())
