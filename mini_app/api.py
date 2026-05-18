import sys
import os
import json

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
    update_bot_token
)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
async def startup():
    await init_db()

app.mount("/app", StaticFiles(directory="mini_app", html=True), name="mini_app")
app.mount("/shop", StaticFiles(directory="mini_app", html=True), name="shop")


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
    shop_products:      Optional[str]   = None
    shop_delivery_price: Optional[float] = None
    shop_delivery_days:  Optional[int]   = None
    shop_express_price:  Optional[float] = None
    shop_express_days:   Optional[int]   = None
    shop_free_from:      Optional[float] = None

    class Config:
        # Разрешаем пустые строки
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


@app.post("/api/auth")
async def api_auth(body: AuthRequest):
    client = await get_client_by_code_and_username(body.code, body.username)
    if not client:
        raise HTTPException(status_code=401, detail="Неверный код или аккаунт не совпадает")
    if body.token and ":" in body.token:
        await update_bot_token(client["id"], body.token)
    return {"client_id": client["id"], "bot_name": client["bot_name"], "client_type": client.get("client_type", "cargo")}


@app.post("/api/token/{client_id}")
async def api_update_token(client_id: int, body: TokenUpdate, x_init_data: str = Header(...)):
    if ":" not in body.token:
        raise HTTPException(status_code=400, detail="Неверный формат токена")
    await update_bot_token(client_id, body.token)
    return {"ok": True}


@app.post("/api/apply/{client_id}")
async def api_apply(client_id: int, body: ApplyRequest, x_init_data: str = Header(...)):
    return {"ok": True}


@app.get("/api/settings/{client_id}")
async def api_get_settings(client_id: int, x_init_data: str = Header(...)):
    settings = await get_settings(client_id)
    if not settings:
        raise HTTPException(status_code=404, detail="Client not found")
    try:
        settings["faq"] = json.loads(settings.get("faq_json", "[]"))
    except:
        settings["faq"] = []
    return settings


@app.post("/api/settings/{client_id}")
async def api_update_settings(client_id: int, body: SettingsUpdate, x_init_data: str = Header(...)):
    # Берём все переданные поля включая пустые строки
    updates = {}
    for field, value in body.dict().items():
        if value is not None:
            updates[field] = value

    if not updates:
        return {"ok": True}  # Ничего не обновляем но не ошибка

    try:
        success = await update_settings(client_id, **updates)
        return {"ok": success}
    except Exception as e:
        print(f"Settings update error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/promos/{client_id}")
async def api_get_promos(client_id: int, x_init_data: str = Header(...)):
    return {"promos": await get_promos(client_id)}


@app.post("/api/promos/{client_id}")
async def api_add_promo(client_id: int, body: PromoAdd, x_init_data: str = Header(...)):
    success = await add_promo(client_id, body.code, body.discount)
    return {"ok": success}


@app.delete("/api/promos/{client_id}")
async def api_delete_promo(client_id: int, body: PromoDelete, x_init_data: str = Header(...)):
    success = await delete_promo(client_id, body.code)
    return {"ok": success}


@app.get("/api/tracks/{client_id}")
async def api_get_tracks(client_id: int, x_init_data: str = Header(...)):
    return {"tracks": await get_all_tracks(client_id)}


@app.post("/api/tracks/{client_id}")
async def api_add_track(client_id: int, body: TrackAdd, x_init_data: str = Header(...)):
    success = await add_track(client_id, body.order_id, body.track_num)
    return {"ok": success}


@app.post("/api/faq/{client_id}")
async def api_update_faq(client_id: int, body: List[FaqItem], x_init_data: str = Header(...)):
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
