"""
База данных на PostgreSQL.
"""

import os
import json
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
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

    c.execute("""
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
            FOREIGN KEY (client_id) REFERENCES clients(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS promocodes (
            id          SERIAL PRIMARY KEY,
            client_id   INTEGER NOT NULL,
            code        TEXT NOT NULL,
            discount    INTEGER NOT NULL,
            UNIQUE(client_id, code),
            FOREIGN KEY (client_id) REFERENCES clients(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            id          SERIAL PRIMARY KEY,
            client_id   INTEGER NOT NULL,
            order_id    TEXT NOT NULL,
            track_num   TEXT NOT NULL,
            UNIQUE(client_id, order_id),
            FOREIGN KEY (client_id) REFERENCES clients(id)
        )
    """)

    conn.commit()
    conn.close()
    print("✅ PostgreSQL база инициализирована")


def add_client(username: str, access_code: str, bot_token: str, bot_name: str) -> bool:
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT INTO clients (username, access_code, bot_token, bot_name) VALUES (%s,%s,%s,%s) RETURNING id",
            (username.lower().lstrip("@"), access_code.upper(), bot_token, bot_name)
        )
        client_id = c.fetchone()[0]
        c.execute("INSERT INTO bot_settings (client_id) VALUES (%s)", (client_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"add_client error: {e}")
        return False


def get_client_by_code_and_username(code: str, username: str):
    conn = get_conn()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute(
        "SELECT * FROM clients WHERE access_code=%s AND username=%s AND is_active=1",
        (code.upper(), username.lower().lstrip("@"))
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_clients():
    conn = get_conn()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT id, username, bot_name, is_active, created_at FROM clients ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def deactivate_client(username: str) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE clients SET is_active=0 WHERE username=%s", (username.lower(),))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def restore_client(username: str) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE clients SET is_active=1 WHERE username=%s", (username.lower(),))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def delete_client(username: str) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM clients WHERE username=%s", (username.lower(),))
    row = c.fetchone()
    if not row:
        conn.close()
        return False
    cid = row[0]
    c.execute("DELETE FROM promocodes WHERE client_id=%s", (cid,))
    c.execute("DELETE FROM tracks WHERE client_id=%s", (cid,))
    c.execute("DELETE FROM bot_settings WHERE client_id=%s", (cid,))
    c.execute("DELETE FROM clients WHERE id=%s", (cid,))
    conn.commit()
    conn.close()
    return True


def get_settings(client_id: int) -> dict:
    conn = get_conn()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM bot_settings WHERE client_id=%s", (client_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else {}


def update_settings(client_id: int, **kwargs) -> bool:
    if not kwargs:
        return False
    fields = ", ".join(f"{k}=%s" for k in kwargs)
    values = list(kwargs.values()) + [client_id]
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"UPDATE bot_settings SET {fields} WHERE client_id=%s", values)
    conn.commit()
    conn.close()
    return True


def add_promo(client_id: int, code: str, discount: int) -> bool:
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT INTO promocodes (client_id, code, discount) VALUES (%s,%s,%s) ON CONFLICT (client_id, code) DO UPDATE SET discount=EXCLUDED.discount",
            (client_id, code.upper(), discount)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"add_promo error: {e}")
        return False


def delete_promo(client_id: int, code: str) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM promocodes WHERE client_id=%s AND code=%s", (client_id, code.upper()))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def get_promos(client_id: int) -> list:
    conn = get_conn()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT code, discount FROM promocodes WHERE client_id=%s", (client_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def check_promo(client_id: int, code: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT discount FROM promocodes WHERE client_id=%s AND code=%s", (client_id, code.upper()))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def add_track(client_id: int, order_id: str, track_num: str) -> bool:
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT INTO tracks (client_id, order_id, track_num) VALUES (%s,%s,%s) ON CONFLICT (client_id, order_id) DO UPDATE SET track_num=EXCLUDED.track_num",
            (client_id, order_id, track_num)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"add_track error: {e}")
        return False


def get_track(client_id: int, order_id: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT track_num FROM tracks WHERE client_id=%s AND order_id=%s", (client_id, order_id))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def get_all_tracks(client_id: int) -> list:
    conn = get_conn()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT order_id, track_num FROM tracks WHERE client_id=%s", (client_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
