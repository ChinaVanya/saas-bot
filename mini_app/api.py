"""
API-сервер для Mini App (mini_app_api.py)
Принимает запросы от веб-панели клиента и обновляет БД.
Запускается на том же сервере что и боты.
"""

import sys
import os
import json
import hmac
import hashlib
from urllib.parse import unquote

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List

from database.db import (
    get_settings, update_settings,
    get_promos, add_promo, delete_promo,
    get_all_tracks, add_track,
    get_client_by_code_and_username
)
from client_config import CLIENT_TOKENS, MINI_APP_URL

app = FastAPI(title="SaaS Bot API")

# CORS — разрешаем запросы из Telegram Mini App
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Отдаём статику Mini App
app.mount("/app", StaticFiles(directory="mini_app", html=True), name="mini_app")


# ───────────────────────────────────────────
#  Проверка Telegram initData (безопасность)
# ───────────────────────────────────────────

def verify_telegram_data(init_data: str, bot_token: str) -> dict:
    """
    Проверяет подпись initData от Telegram.
    Возвращает данные пользователя или кидает исключение.
    """
    try:
        parsed = {}
        for part in unquote(init_data).split("&"):
            k, v = part.split("=", 1)
            parsed[k] = v

        received_hash = parsed.pop("hash", "")
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )

        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(received_hash, expected_hash):
            raise HTTPException(status_code=403, detail="Invalid signature")

        user_data = json.loads(parsed.get("user", "{}"))
        return user_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad initData: {e}")


# ───────────────────────────────────────────
#  Модели запросов
# ───────────────────────────────────────────

class SettingsUpdate(BaseModel):
    air_percent:    Optional[float] = None
    air_per_kg:     Optional[float] = None
    truck_percent:  Optional[float] = None
    truck_per_kg:   Optional[float] = None
    manager_link:   Optional[str]   = None
    channel_link:   Optional[str]   = None
    welcome_text:   Optional[str]   = None
    faq_json:       Optional[str]   = None  # JSON-строка

class PromoAdd(BaseModel):
    code:     str
    discount: int

class PromoDelete(BaseModel):
    code: str

class TrackAdd(BaseModel):
    order_id:  str
    track_num: str

class FaqItem(BaseModel):
    question: str
    answer:   str


# ───────────────────────────────────────────
#  Эндпоинты
# ───────────────────────────────────────────

@app.get("/api/settings/{client_id}")
async def api_get_settings(client_id: int, x_init_data: str = Header(...)):
    """Получить все настройки."""
    # В продакшене здесь нужно верифицировать initData через токен клиента
    settings = get_settings(client_id)
    if not settings:
        raise HTTPException(status_code=404, detail="Client not found")

    # Парсим FAQ из JSON-строки
    try:
        settings["faq"] = json.loads(settings.get("faq_json", "[]"))
    except:
        settings["faq"] = []

    return settings


@app.post("/api/settings/{client_id}")
async def api_update_settings(
    client_id: int,
    body: SettingsUpdate,
    x_init_data: str = Header(...)
):
    """Обновить настройки (только переданные поля)."""
    updates = body.dict(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")

    success = update_settings(client_id, **updates)
    return {"ok": success}


# ── Промокоды ──

@app.get("/api/promos/{client_id}")
async def api_get_promos(client_id: int, x_init_data: str = Header(...)):
    return {"promos": get_promos(client_id)}


@app.post("/api/promos/{client_id}")
async def api_add_promo(client_id: int, body: PromoAdd, x_init_data: str = Header(...)):
    if body.discount < 1 or body.discount > 99:
        raise HTTPException(status_code=400, detail="Discount must be 1-99%")
    success = add_promo(client_id, body.code, body.discount)
    return {"ok": success}


@app.delete("/api/promos/{client_id}")
async def api_delete_promo(client_id: int, body: PromoDelete, x_init_data: str = Header(...)):
    success = delete_promo(client_id, body.code)
    return {"ok": success}


# ── Трек-номера ──

@app.get("/api/tracks/{client_id}")
async def api_get_tracks(client_id: int, x_init_data: str = Header(...)):
    return {"tracks": get_all_tracks(client_id)}


@app.post("/api/tracks/{client_id}")
async def api_add_track(client_id: int, body: TrackAdd, x_init_data: str = Header(...)):
    success = add_track(client_id, body.order_id, body.track_num)
    return {"ok": success}


# ── FAQ ──

@app.post("/api/faq/{client_id}")
async def api_update_faq(client_id: int, body: List[FaqItem], x_init_data: str = Header(...)):
    """Полностью заменяет FAQ список."""
    faq_data = [{"question": item.question, "answer": item.answer} for item in body]
    faq_json = json.dumps(faq_data, ensure_ascii=False)
    success = update_settings(client_id, faq_json=faq_json)
    return {"ok": success}


# ── Health check ──

@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
