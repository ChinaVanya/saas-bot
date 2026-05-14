"""
База данных всей SaaS-системы.
Один файл SQLite, три таблицы.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "saas.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # доступ по имени колонки
    return conn


def init_db():
    """Создаёт таблицы при первом запуске."""
    conn = get_conn()
    c = conn.cursor()

    # --- Клиенты (каждый купивший бота) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT UNIQUE NOT NULL,   -- @username покупателя (без @)
            access_code TEXT UNIQUE NOT NULL,   -- секретный код доступа
            bot_token   TEXT UNIQUE NOT NULL,   -- токен их бота от @BotFather
            bot_name    TEXT,                   -- отображаемое имя бота
            created_at  TEXT DEFAULT (datetime('now')),
            is_active   INTEGER DEFAULT 1       -- 1=активен, 0=заблокирован
        )
    """)

    # --- Настройки каждого клиентского бота ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            client_id       INTEGER PRIMARY KEY,
            -- Тарифы доставки
            air_percent     REAL DEFAULT 0.17,
            air_per_kg      REAL DEFAULT 700,
            truck_percent   REAL DEFAULT 0.11,
            truck_per_kg    REAL DEFAULT 350,
            -- Контакты
            manager_link    TEXT DEFAULT '@manager',
            channel_link    TEXT DEFAULT '@channel',
            -- Приветствие
            welcome_text    TEXT DEFAULT 'Добро пожаловать! 👋',
            -- FAQ (хранится как JSON-строка)
            faq_json        TEXT DEFAULT '[]',
            FOREIGN KEY (client_id) REFERENCES clients(id)
        )
    """)

    # --- Промокоды каждого клиента ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS promocodes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id   INTEGER NOT NULL,
            code        TEXT NOT NULL,
            discount    INTEGER NOT NULL,   -- скидка в %
            UNIQUE(client_id, code),
            FOREIGN KEY (client_id) REFERENCES clients(id)
        )
    """)

    # --- Трек-номера каждого клиента ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id   INTEGER NOT NULL,
            order_id    TEXT NOT NULL,
            track_num   TEXT NOT NULL,
            UNIQUE(client_id, order_id),
            FOREIGN KEY (client_id) REFERENCES clients(id)
        )
    """)

    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")


# ───────────────────────────────────────────
#  Клиенты
# ───────────────────────────────────────────

def add_client(username: str, access_code: str, bot_token: str, bot_name: str) -> bool:
    """Добавляет нового клиента. Возвращает True если успешно."""
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT INTO clients (username, access_code, bot_token, bot_name) VALUES (?,?,?,?)",
            (username.lower().lstrip("@"), access_code.upper(), bot_token, bot_name)
        )
        client_id = c.lastrowid
        # Сразу создаём настройки по умолчанию
        c.execute("INSERT INTO bot_settings (client_id) VALUES (?)", (client_id,))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False  # дубликат username или кода


def get_client_by_code_and_username(code: str, username: str):
    """Проверяет код доступа + username. Возвращает клиента или None."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM clients WHERE access_code=? AND username=? AND is_active=1",
        (code.upper(), username.lower().lstrip("@"))
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_clients():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, username, bot_name, is_active, created_at FROM clients")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def deactivate_client(username: str) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE clients SET is_active=0 WHERE username=?", (username.lower(),))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def restore_client(username: str) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE clients SET is_active=1 WHERE username=?", (username.lower(),))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def delete_client(username: str) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM clients WHERE username=?", (username.lower(),))
    row = c.fetchone()
    if not row:
        conn.close()
        return False
    cid = row["id"]
    c.execute("DELETE FROM promocodes WHERE client_id=?", (cid,))
    c.execute("DELETE FROM tracks WHERE client_id=?", (cid,))
    c.execute("DELETE FROM bot_settings WHERE client_id=?", (cid,))
    c.execute("DELETE FROM clients WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    return True


# ───────────────────────────────────────────
#  Настройки бота клиента
# ───────────────────────────────────────────

def get_settings(client_id: int) -> dict:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM bot_settings WHERE client_id=?", (client_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else {}


def update_settings(client_id: int, **kwargs) -> bool:
    """Обновляет любые поля настроек. Пример: update_settings(1, air_per_kg=800)"""
    if not kwargs:
        return False
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [client_id]
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"UPDATE bot_settings SET {fields} WHERE client_id=?", values)
    conn.commit()
    conn.close()
    return True


# ───────────────────────────────────────────
#  Промокоды
# ───────────────────────────────────────────

def add_promo(client_id: int, code: str, discount: int) -> bool:
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO promocodes (client_id, code, discount) VALUES (?,?,?)",
            (client_id, code.upper(), discount)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def delete_promo(client_id: int, code: str) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM promocodes WHERE client_id=? AND code=?", (client_id, code.upper()))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def get_promos(client_id: int) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT code, discount FROM promocodes WHERE client_id=?", (client_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def check_promo(client_id: int, code: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT discount FROM promocodes WHERE client_id=? AND code=?", (client_id, code.upper()))
    row = c.fetchone()
    conn.close()
    return row["discount"] if row else None


# ───────────────────────────────────────────
#  Трек-номера
# ───────────────────────────────────────────

def add_track(client_id: int, order_id: str, track_num: str) -> bool:
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO tracks (client_id, order_id, track_num) VALUES (?,?,?)",
            (client_id, order_id, track_num)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def get_track(client_id: int, order_id: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT track_num FROM tracks WHERE client_id=? AND order_id=?", (client_id, order_id))
    row = c.fetchone()
    conn.close()
    return row["track_num"] if row else None


def get_all_tracks(client_id: int) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT order_id, track_num FROM tracks WHERE client_id=?", (client_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
