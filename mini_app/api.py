import sys, os, json, hmac, hashlib
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
    get_client_by_code, update_bot_token, get_client_by_id
)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
async def startup():
    await init_db()

app.mount("/app",  StaticFiles(directory="mini_app", html=True), name="mini_app")
app.mount("/shop", StaticFiles(directory="mini_app", html=True), name="shop")

# --- Сессионные токены ---
SECRET = os.environ.get("MASTER_TOKEN", "secret")

def make_token(client_id: int) -> str:
    sig = hmac.new(SECRET.encode(), str(client_id).encode(), hashlib.sha256).hexdigest()
    return f"{client_id}.{sig}"

def check_token(token: str, client_id: int) -> bool:
    try:
        cid, sig = token.split(".", 1)
        if int(cid) != client_id:
            return False
        expected = hmac.new(SECRET.encode(), str(client_id).encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False

def auth(token: str, client_id: int):
    if not check_token(token, client_id):
        raise HTTPException(403, "Недействительная сессия")

# --- Модели ---
class AuthRequest(BaseModel):
    code: str
    token: str  # токен бота клиента

class SettingsUpdate(BaseModel):
    air_percent: Optional[float] = None
    air_per_kg: Optional[float] = None
    truck_percent: Optional[float] = None
    truck_per_kg: Optional[float] = None
    express_percent: Optional[float] = None
    express_per_kg: Optional[float] = None
    normal_percent: Optional[float] = None
    normal_per_kg: Optional[float] = None
    tariff_enabled: Optional[str] = None
    tariff_mode: Optional[str] = None
    manager_link: Optional[str] = None
    channel_link: Optional[str] = None
    welcome_text: Optional[str] = None
    faq_json: Optional[str] = None
    currency: Optional[str] = None
    tracking_site: Optional[str] = None
    track17_api: Optional[str] = None
    openai_api: Optional[str] = None
    ai_recognition: Optional[int] = None
    msg_welcome: Optional[str] = None
    msg_calc: Optional[str] = None
    msg_order: Optional[str] = None
    msg_support: Optional[str] = None
    msg_welcome_img: Optional[str] = None
    msg_calc_img: Optional[str] = None
    msg_order_img: Optional[str] = None
    msg_support_img: Optional[str] = None
    shop_products: Optional[str] = None
    shop_delivery_price: Optional[float] = None
    shop_delivery_days: Optional[int] = None
    shop_express_price: Optional[float] = None
    shop_express_days: Optional[int] = None
    shop_free_from: Optional[float] = None
    shop_normal_price: Optional[float] = None
    shop_normal_days: Optional[int] = None
    shop_templates: Optional[str] = None
    shop_msg_welcome: Optional[str] = None
    shop_msg_catalog: Optional[str] = None
    shop_msg_delivery: Optional[str] = None
    shop_msg_order: Optional[str] = None
    shop_msg_support: Optional[str] = None
    class Config:
        extra = "allow"

class PromoAdd(BaseModel):
    code: str
    discount: int

class PromoDelete(BaseModel):
    code: str

class TrackAdd(BaseModel):
    order_id: str
    track_num: str

class FaqItem(BaseModel):
    question: str
    answer: str

class TokenUpdate(BaseModel):
    token: str

class ApplyRequest(BaseModel):
    section: str

# --- Эндпоинты ---

@app.post("/api/auth")
async def api_auth(body: AuthRequest):
    """Вход по коду доступа. Возвращает session_token."""
    client = await get_client_by_code(body.code)
    if not client:
        raise HTTPException(401, "Неверный код доступа")
    # Сохраняем токен бота если передан
    if body.token and ":" in body.token:
        await update_bot_token(client["id"], body.token)
    return {
        "client_id":     client["id"],
        "bot_name":      client["bot_name"],
        "client_type":   client.get("client_type", "cargo"),
        "session_token": make_token(client["id"]),
    }

@app.get("/api/settings/{client_id}")
async def api_get_settings(client_id: int, x_session: str = Header(...)):
    auth(x_session, client_id)
    s = await get_settings(client_id)
    if not s:
        raise HTTPException(404, "Клиент не найден")
    try:
        s["faq"] = json.loads(s.get("faq_json", "[]"))
    except Exception:
        s["faq"] = []
    return s

@app.post("/api/settings/{client_id}")
async def api_update_settings(client_id: int, body: SettingsUpdate, x_session: str = Header(...)):
    auth(x_session, client_id)
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if updates:
        await update_settings(client_id, **updates)
    return {"ok": True}

@app.post("/api/token/{client_id}")
async def api_update_token(client_id: int, body: TokenUpdate, x_session: str = Header(...)):
    auth(x_session, client_id)
    if ":" not in body.token:
        raise HTTPException(400, "Неверный формат токена")
    await update_bot_token(client_id, body.token)
    return {"ok": True}

@app.post("/api/apply/{client_id}")
async def api_apply(client_id: int, body: ApplyRequest, x_session: str = Header(...)):
    auth(x_session, client_id)
    return {"ok": True}

@app.get("/api/promos/{client_id}")
async def api_get_promos(client_id: int, x_session: str = Header(...)):
    auth(x_session, client_id)
    return {"promos": await get_promos(client_id)}

@app.post("/api/promos/{client_id}")
async def api_add_promo(client_id: int, body: PromoAdd, x_session: str = Header(...)):
    auth(x_session, client_id)
    return {"ok": await add_promo(client_id, body.code, body.discount)}

@app.delete("/api/promos/{client_id}")
async def api_delete_promo(client_id: int, body: PromoDelete, x_session: str = Header(...)):
    auth(x_session, client_id)
    return {"ok": await delete_promo(client_id, body.code)}

@app.get("/api/tracks/{client_id}")
async def api_get_tracks(client_id: int, x_session: str = Header(...)):
    auth(x_session, client_id)
    return {"tracks": await get_all_tracks(client_id)}

@app.post("/api/tracks/{client_id}")
async def api_add_track(client_id: int, body: TrackAdd, x_session: str = Header(...)):
    auth(x_session, client_id)
    return {"ok": await add_track(client_id, body.order_id, body.track_num)}

@app.post("/api/faq/{client_id}")
async def api_update_faq(client_id: int, body: List[FaqItem], x_session: str = Header(...)):
    auth(x_session, client_id)
    faq_json = json.dumps([{"question": i.question, "answer": i.answer} for i in body], ensure_ascii=False)
    await update_settings(client_id, faq_json=faq_json)
    return {"ok": True}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
