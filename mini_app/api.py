import sys
import os
import json
import hmac
import hashlib
from urllib.parse import unquote

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List

from database.db import (
    init_db, get_settings, update_settings,
    get_promos, add_promo, delete_promo,
    get_all_tracks, add_track,
    get_client_by_code_and_username,
    update_bot_token, get_client_by_id
)

app = FastAPI()

# CORS: в продакшне разрешаем только свой домен Railway
ALLOWED_ORIGIN = os.environ.get("MINI_APP_URL", "*").replace("/app", "").replace("/shop", "")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN, "https://web.telegram.org"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await init_db()


app.mount("/app",  StaticFiles(directory="mini_app", html=True), name="mini_app")
app.mount("/shop", StaticFiles(directory="mini_app", html=True), name="shop")


# ---------------------------------------------------------------------------
# Верификация подписи Telegram Mini App
# ---------------------------------------------------------------------------
MASTER_TOKEN = os.environ.get("MASTER_TOKEN", "")

def _verify_telegram_init_data(init_data: str) -> bool:
    """
    Проверяет подпись initData от Telegram.
    Документация: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not init_data or not MASTER_TOKEN:
        return False

    # Разбираем строку вида "key=value&key=value&hash=..."
    try:
        parsed = {}
        for part in unquote(init_data).split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                parsed[k] = v
    except Exception:
        return False

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return False

    # Строка для проверки: отсортированные пары key=value через \n
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

    # HMAC-SHA256 с ключом = HMAC-SHA256("WebAppData", bot_token)
    secret_key = hmac.new(b"WebAppData", MASTER_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    return hmac.compare_digest(expected, received_hash)


def require_auth(x_init_data: str):
    """Вызывается в эндпоинтах требующих авторизации Telegram."""
    if not _verify_telegram_init_data(x_init_data):
        raise HTTPException(status_code=403, detail="Невалидная подпись Telegram")


# ---------------------------------------------------------------------------
# Модели запросов
# ---------------------------------------------------------------------------
class SettingsUpdate(BaseModel):
    air_percent:     Optional[float] = None
    air_per_kg:      Optional[float] = None
    truck_percent:   Optional[float] = None
    truck_per_kg:    Optional[float] = None
    express_percent: Optional[float] = None
    express_per_kg:  Optional[float] = None
    normal_percent:  Optional[float] = None
    normal_per_kg:   Optional[float] = None
    tariff_enabled:  Optional[str]   = None
    tariff_mode:     Optional[str]   = None
    manager_link:    Optional[str]   = None
    channel_link:    Optional[str]   = None
    welcome_text:    Optional[str]   = None
    faq_json:        Optional[str]   = None
    currency:        Optional[str]   = None
    tracking_site:   Optional[str]   = None
    track17_api:     Optional[str]   = None
    openai_api:      Optional[str]   = None
    ai_recognition:  Optional[int]   = None
    msg_welcome:     Optional[str]   = None
    msg_calc:        Optional[str]   = None
    msg_order:       Optional[str]   = None
    msg_support:     Optional[str]   = None
    msg_welcome_img: Optional[str]   = None
    msg_calc_img:    Optional[str]   = None
    msg_order_img:   Optional[str]   = None
    msg_support_img: Optional[str]   = None
    shop_products:       Optional[str]   = None
    shop_delivery_price: Optional[float] = None
    shop_delivery_days:  Optional[int]   = None
    shop_express_price:  Optional[float] = None
    shop_express_days:   Optional[int]   = None
    shop_free_from:      Optional[float] = None
    shop_normal_price:   Optional[float] = None
    shop_normal_days:    Optional[int]   = None
    shop_templates:      Optional[str]   = None
    shop_msg_welcome:    Optional[str]   = None
    shop_msg_catalog:    Optional[str]   = None
    shop_msg_delivery:   Optional[str]   = None
    shop_msg_order:      Optional[str]   = None
    shop_msg_support:    Optional[str]   = None

    class Config:
        extra = "allow"


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

class AuthRequest(BaseModel):
    code:     str
    username: str
    token:    str

class TokenUpdate(BaseModel):
    token: str

class ApplyRequest(BaseModel):
    section: str


# ---------------------------------------------------------------------------
# Эндпоинты
# ---------------------------------------------------------------------------

@app.post("/api/auth")
async def api_auth(body: AuthRequest):
    """
    Авторизация клиента по коду доступа и username.
    Не требует подписи Telegram — это первый шаг входа.
    """
    client = await get_client_by_code_and_username(body.code, body.username)
    if not client:
        raise HTTPException(status_code=401, detail="Неверный код или аккаунт не совпадает")
    if body.token and ":" in body.token:
        await update_bot_token(client["id"], body.token)
    return {
        "client_id":   client["id"],
        "bot_name":    client["bot_name"],
        "client_type": client.get("client_type", "cargo")
    }


@app.post("/api/token/{client_id}")
async def api_update_token(client_id: int, body: TokenUpdate, x_init_data: str = Header(...)):
    require_auth(x_init_data)
    if ":" not in body.token:
        raise HTTPException(status_code=400, detail="Неверный формат токена")
    await update_bot_token(client_id, body.token)
    return {"ok": True}


@app.post("/api/apply/{client_id}")
async def api_apply(client_id: int, body: ApplyRequest, x_init_data: str = Header(...)):
    require_auth(x_init_data)
    return {"ok": True}


@app.get("/api/settings/{client_id}")
async def api_get_settings(client_id: int, x_init_data: str = Header(...)):
    require_auth(x_init_data)
    settings = await get_settings(client_id)
    if not settings:
        raise HTTPException(status_code=404, detail="Client not found")
    try:
        settings["faq"] = json.loads(settings.get("faq_json", "[]"))
    except Exception:
        settings["faq"] = []
    return settings


@app.post("/api/settings/{client_id}")
async def api_update_settings(client_id: int, body: SettingsUpdate, x_init_data: str = Header(...)):
    require_auth(x_init_data)
    updates = {field: value for field, value in body.dict().items() if value is not None}
    if not updates:
        return {"ok": True}
    try:
        success = await update_settings(client_id, **updates)
        return {"ok": success}
    except Exception as e:
        print(f"Settings update error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/promos/{client_id}")
async def api_get_promos(client_id: int, x_init_data: str = Header(...)):
    require_auth(x_init_data)
    return {"promos": await get_promos(client_id)}


@app.post("/api/promos/{client_id}")
async def api_add_promo(client_id: int, body: PromoAdd, x_init_data: str = Header(...)):
    require_auth(x_init_data)
    success = await add_promo(client_id, body.code, body.discount)
    return {"ok": success}


@app.delete("/api/promos/{client_id}")
async def api_delete_promo(client_id: int, body: PromoDelete, x_init_data: str = Header(...)):
    require_auth(x_init_data)
    success = await delete_promo(client_id, body.code)
    return {"ok": success}


@app.get("/api/tracks/{client_id}")
async def api_get_tracks(client_id: int, x_init_data: str = Header(...)):
    require_auth(x_init_data)
    return {"tracks": await get_all_tracks(client_id)}


@app.post("/api/tracks/{client_id}")
async def api_add_track(client_id: int, body: TrackAdd, x_init_data: str = Header(...)):
    require_auth(x_init_data)
    success = await add_track(client_id, body.order_id, body.track_num)
    return {"ok": success}


@app.post("/api/faq/{client_id}")
async def api_update_faq(client_id: int, body: List[FaqItem], x_init_data: str = Header(...)):
    require_auth(x_init_data)
    faq_data = [{"question": i.question, "answer": i.answer} for i in body]
    faq_json = json.dumps(faq_data, ensure_ascii=False)
    success = await update_settings(client_id, faq_json=faq_json)
    return {"ok": success}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
