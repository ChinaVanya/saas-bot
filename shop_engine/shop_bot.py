import asyncio
import sys
import os
import json
import base64

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, BufferedInputFile
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

from database.db import init_db, get_all_clients, get_settings, check_promo, get_track, get_conn

import aiohttp

TRACKING_URLS = {
    'track24':     'https://track24.ru/?code=',
    'track24api':  'https://track24.ru/?code=',
}

# Статусы 17track на русском
TRACK17_STATUSES = {
    0:   "Не найден",
    10:  "В ожидании",
    20:  "Информация получена",
    30:  "В пути",
    35:  "Прибыл в страну назначения",
    40:  "На доставке",
    41:  "Попытка доставки",
    42:  "Забрать в отделении",
    50:  "Доставлен",
    60:  "Возврат",
    65:  "Возврат завершён",
    70:  "Утерян",
    80:  "Таможня",
}


async def get_cny_rate() -> float:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json(content_type=None)
                return round(data["Valute"]["CNY"]["Value"] / data["Valute"]["CNY"]["Nominal"], 2)
    except:
        return 13.0


async def get_track17_status(track_num: str, api_key: str) -> dict:
    """Запрашивает статус посылки через 17track API."""
    try:
        async with aiohttp.ClientSession() as session:
            # Регистрируем трек
            await session.post(
                "https://api.17track.net/track/v2.2/register",
                headers={"17token": api_key, "Content-Type": "application/json"},
                json=[{"number": track_num}]
            )
            # Получаем статус
            async with session.post(
                "https://api.17track.net/track/v2.2/gettrackinfo",
                headers={"17token": api_key, "Content-Type": "application/json"},
                json=[{"number": track_num}]
            ) as resp:
                data = await resp.json()
                if data.get("code") != 0:
                    return None
                track_data = data.get("data", {}).get("accepted", [])
                if not track_data:
                    return None
                info = track_data[0].get("track", {})
                status_code = info.get("e", 0)
                status_text = TRACK17_STATUSES.get(status_code, "Неизвестно")
                last_event = ""
                events = info.get("z0", []) or info.get("z1", [])
                if events:
                    last = events[0]
                    last_event = last.get("z", "")
                return {
                    "status": status_text,
                    "last_event": last_event,
                    "status_code": status_code
                }
    except Exception as e:
        print(f"17track error: {e}")
        return None


async def calculate(price_cny, weight, settings) -> str:
    rate = await get_cny_rate()
    price_rub = price_cny * rate

    currency = settings.get("currency", "RUB")
    sym = {"RUB": "₽", "USD": "$", "KZT": "₸"}.get(currency, "₽")

    # Конвертируем если нужно
    if currency == "USD":
        usd_rate = await get_usd_rate()
        price_display = price_rub / usd_rate
    elif currency == "KZT":
        kzt_rate = await get_kzt_rate()
        price_display = price_rub * kzt_rate
    else:
        price_display = price_rub

    try:
        enabled = json.loads(settings.get("tariff_enabled", "{}"))
    except:
        enabled = {}

    lines = [
        f"📊 <b>Расчёт стоимости доставки</b>\n\n"
        f"💰 Цена товара: {price_cny} ¥ = {price_display:.0f} {sym}\n"
        f"⚖️ Вес: {weight} кг\n"
        f"💱 Курс юаня: {rate} ₽\n"
    ]

    def calc_tariff(percent, per_kg):
        svc = price_rub * percent + weight * per_kg
        total = price_rub + svc
        if currency == "USD":
            svc = svc / usd_rate if 'usd_rate' in dir() else svc / 90
            total = total / usd_rate if 'usd_rate' in dir() else total / 90
        elif currency == "KZT":
            svc = svc * kzt_rate if 'kzt_rate' in dir() else svc * 5.5
            total = total * kzt_rate if 'kzt_rate' in dir() else total * 5.5
        return svc, total

    if enabled.get("normal", True):
        np_ = settings.get("normal_percent", 0.08)
        nk_ = settings.get("normal_per_kg", 200)
        svc = price_rub * np_ + weight * nk_
        total = price_rub + svc
        lines.append(f"\n📦 <b>Обычный (35-50 дней)</b>\nУслуги: {svc:.0f} ₽ | Итого: <b>{total:.0f} {sym}</b>")

    if enabled.get("truck", True):
        tp_ = settings.get("truck_percent", 0.11)
        tk_ = settings.get("truck_per_kg", 350)
        svc = price_rub * tp_ + weight * tk_
        total = price_rub + svc
        lines.append(f"\n🚛 <b>Авто (25-40 дней)</b>\nУслуги: {svc:.0f} ₽ | Итого: <b>{total:.0f} {sym}</b>")

    if enabled.get("air", True):
        ap_ = settings.get("air_percent", 0.17)
        ak_ = settings.get("air_per_kg", 700)
        svc = price_rub * ap_ + weight * ak_
        total = price_rub + svc
        lines.append(f"\n✈️ <b>Авиа (7-14 дней)</b>\nУслуги: {svc:.0f} ₽ | Итого: <b>{total:.0f} {sym}</b>")

    if enabled.get("express", True):
        ep_ = settings.get("express_percent", 0.25)
        ek_ = settings.get("express_per_kg", 1200)
        svc = price_rub * ep_ + weight * ek_
        total = price_rub + svc
        lines.append(f"\n⚡ <b>Экспресс (5-7 дней)</b>\nУслуги: {svc:.0f} ₽ | Итого: <b>{total:.0f} {sym}</b>")

    return "".join(lines)


async def get_usd_rate():
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=aiohttp.ClientTimeout(total=5)) as r:
                d = await r.json(content_type=None)
                return d["Valute"]["USD"]["Value"]
    except:
        return 90.0


async def get_kzt_rate():
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=aiohttp.ClientTimeout(total=5)) as r:
                d = await r.json(content_type=None)
                return 1 / (d["Valute"]["KZT"]["Value"] / d["Valute"]["KZT"]["Nominal"])
    except:
        return 5.5


class CalcStates(StatesGroup):
    waiting_price  = State()
    waiting_weight = State()

class TrackStates(StatesGroup):
    waiting_order = State()

class PromoStates(StatesGroup):
    waiting_promo = State()


def main_menu_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="💸 Калькулятор стоимости")
    kb.button(text="🔎 Отследить посылку")
    kb.button(text="🤩 Оформить заказ")
    kb.button(text="📚 Ответы на вопросы")
    kb.button(text="❓ Остались вопросы")
    kb.adjust(2, 2, 1)
    return kb.as_markup(resize_keyboard=True)


def calc_menu_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="💸 Рассчитать стоимость")
    kb.button(text="🎟 У меня есть промокод")
    kb.button(text="🏠 Главное меню")
    kb.adjust(2, 1)
    return kb.as_markup(resize_keyboard=True)


def back_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="◀️ Назад")
    return kb.as_markup(resize_keyboard=True)


async def send_msg_with_img(message: Message, text: str, img_b64: str, reply_markup=None):
    """Отправляет сообщение с изображением если оно есть."""
    if img_b64 and img_b64.startswith("data:image"):
        try:
            header, data = img_b64.split(",", 1)
            img_bytes = base64.b64decode(data)
            photo = BufferedInputFile(img_bytes, filename="image.jpg")
            await message.answer_photo(photo, caption=text, parse_mode="HTML", reply_markup=reply_markup)
            return
        except:
            pass
    await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


def make_shop_dispatcher(client_id: int):
    dp = Dispatcher(storage=MemoryStorage())

    @dp.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext):
        await state.clear()
        settings = await get_settings(client_id)
        text = settings.get("msg_welcome") or settings.get("welcome_text") or "Добро пожаловать! 👋"
        img = settings.get("msg_welcome_img", "")
        await send_msg_with_img(message, text, img, main_menu_kb())

    @dp.message(F.text == "💸 Калькулятор стоимости")
    async def calc_main(message: Message, state: FSMContext):
        await state.clear()
        settings = await get_settings(client_id)
        text = settings.get("msg_calc") or "Выберите действие:"
        img = settings.get("msg_calc_img", "")
        await send_msg_with_img(message, text, img, calc_menu_kb())

    @dp.message(F.text == "🏠 Главное меню")
    async def go_home(message: Message, state: FSMContext):
        await state.clear()
        await message.answer("Главное меню:", reply_markup=main_menu_kb())

    @dp.message(F.text == "💸 Рассчитать стоимость")
    async def calc_start(message: Message, state: FSMContext):
        settings = await get_settings(client_id)
        ai_on = settings.get("ai_recognition", 0) == 1
        ai_key = settings.get("openai_api", "")
        if ai_on and ai_key:
            await state.set_state(CalcStates.waiting_price)
            await message.answer("Введите цену товара в ¥ или пришлите <b>скриншот</b> из магазина:", parse_mode="HTML", reply_markup=back_kb())
        else:
            await state.set_state(CalcStates.waiting_price)
            await message.answer("Введите цену товара в ¥:", reply_markup=back_kb())

    @dp.message(CalcStates.waiting_price, F.photo)
    async def calc_photo(message: Message, state: FSMContext):
        settings = await get_settings(client_id)
        ai_on = settings.get("ai_recognition", 0) == 1
        ai_key = settings.get("openai_api", "")

        if not ai_on or not ai_key:
            await message.answer("Распознавание скриншотов отключено. Введите цену числом:")
            return

        msg = await message.answer("🔍 Анализируем скриншот...")
        photo = message.photo[-1]
        file_info = await message.bot.get_file(photo.file_id)
        photo_bytes = await message.bot.download_file(file_info.file_path)
        b64 = base64.b64encode(photo_bytes.getvalue()).decode()

        try:
            from openai import OpenAI
            oa = OpenAI(api_key=ai_key)
            response = oa.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "Find product price in Yuan (¥) and estimate weight in kg. Return ONLY: price;weight;name. Example: 299;1.2;Кроссовки. If not found: ERROR"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}],
                max_tokens=60
            )
            result = response.choices[0].message.content.strip()
            if "ERROR" in result or ";" not in result:
                await msg.edit_text("❌ Не удалось найти цену. Введите вручную:")
                return
            price, weight, name = result.split(";", 2)
            price, weight = float(price.strip()), float(weight.strip())
            calc_result = await calculate(price, weight, settings)
            await state.clear()
            await msg.edit_text(f"✅ <b>Распознано:</b> {name.strip()}\n\n{calc_result}", parse_mode="HTML", reply_markup=calc_menu_kb())
        except Exception as e:
            await msg.edit_text(f"❌ Ошибка распознавания. Введите цену вручную:")

    @dp.message(CalcStates.waiting_price, F.text)
    async def calc_price(message: Message, state: FSMContext):
        if message.text == "◀️ Назад":
            await state.clear()
            settings = await get_settings(client_id)
            text = settings.get("msg_calc") or "Выберите действие:"
            await message.answer(text, reply_markup=calc_menu_kb())
            return
        try:
            price = float(message.text.replace(',', '.'))
            await state.update_data(price=price)
            await state.set_state(CalcStates.waiting_weight)
            await message.answer("Введите вес товара в кг (например: 1.5):")
        except ValueError:
            await message.answer("Введите число, например: 299")

    @dp.message(CalcStates.waiting_weight, F.text)
    async def calc_weight(message: Message, state: FSMContext):
        if message.text == "◀️ Назад":
            await state.set_state(CalcStates.waiting_price)
            await message.answer("Введите цену товара в ¥:")
            return
        try:
            weight = float(message.text.replace(',', '.'))
            data = await state.get_data()
            settings = await get_settings(client_id)
            result = await calculate(data["price"], weight, settings)
            await state.clear()
            await message.answer(result, parse_mode="HTML", reply_markup=calc_menu_kb())
        except ValueError:
            await message.answer("Введите число, например: 1.5")

    @dp.message(F.text == "🎟 У меня есть промокод")
    async def promo_start(message: Message, state: FSMContext):
        await state.set_state(PromoStates.waiting_promo)
        await message.answer("Введите промокод:", reply_markup=back_kb())

    @dp.message(PromoStates.waiting_promo)
    async def promo_check(message: Message, state: FSMContext):
        if message.text == "◀️ Назад":
            await state.clear()
            await message.answer("Выберите действие:", reply_markup=calc_menu_kb())
            return
        discount = await check_promo(client_id, message.text.strip())
        await state.clear()
        if discount:
            await message.answer(f"✅ Промокод активирован! Скидка: <b>{discount}%</b>", parse_mode="HTML", reply_markup=calc_menu_kb())
        else:
            await message.answer("❌ Промокод не найден.", reply_markup=calc_menu_kb())

    @dp.message(F.text == "🔎 Отследить посылку")
    async def track_start(message: Message, state: FSMContext):
        await state.set_state(TrackStates.waiting_order)
        await message.answer("Введите номер заказа:", reply_markup=back_kb())

    @dp.message(TrackStates.waiting_order)
    async def track_check(message: Message, state: FSMContext):
        if message.text == "◀️ Назад":
            await state.clear()
            await message.answer("Главное меню:", reply_markup=main_menu_kb())
            return

        order_id = message.text.strip()
        track = await get_track(client_id, order_id)
        await state.clear()

        if not track:
            await message.answer("❌ Заказ не найден. Обратитесь к менеджеру.", reply_markup=main_menu_kb())
            return

        settings = await get_settings(client_id)
        site = settings.get("tracking_site", "track24")
        api17 = settings.get("track17_api", "")
        base_url = TRACKING_URLS.get(site, TRACKING_URLS["track24"])
        track_url = base_url + track

        # Если есть 17track API — показываем статус автоматически
        if site == "track24api" and api17:
            msg = await message.answer("🔍 Запрашиваем статус посылки...")
            status_data = await get_track24_status(track, api17)
            if status_data:
                status_emoji = "📦"
                text = (
                    f"📦 <b>Заказ {order_id}</b>\n"
                    f"Трек-номер: <code>{track}</code>\n\n"
                    f"{status_emoji} <b>Статус:</b> {status_data['status']}\n"
                )
                if status_data["last_event"]:
                    text += f"📍 <b>Последнее событие:</b>\n{status_data['last_event']}\n"
                if status_data.get("eta"):
                    text += f"\n📅 <b>Ожидаемая доставка:</b> {status_data['eta']}\n"
                text += f"\n<a href=\"{track_url}\">🔗 Подробнее на Track24</a>"
                await msg.edit_text(text, parse_mode="HTML", reply_markup=main_menu_kb())
            else:
                await msg.edit_text(
                    f"📦 <b>Заказ {order_id}</b>\n"
                    f"Трек-номер: <code>{track}</code>\n\n"
                    f"<a href=\"{track_url}\">🔗 Отследить посылку</a>",
                    parse_mode="HTML", reply_markup=main_menu_kb()
                )
        else:
            await message.answer(
                f"📦 <b>Заказ {order_id}</b>\n"
                f"Трек-номер: <code>{track}</code>\n\n"
                f"<a href=\"{track_url}\">🔗 Отследить посылку</a>",
                parse_mode="HTML", reply_markup=main_menu_kb()
            )

    @dp.message(F.text == "🤩 Оформить заказ")
    async def order_msg(message: Message):
        settings = await get_settings(client_id)
        manager = settings.get("manager_link", "@manager")
        text = settings.get("msg_order") or f"Оформить заказ: {manager} 👈\n\nОтправь скриншот товара или ссылку."
        img = settings.get("msg_order_img", "")
        await send_msg_with_img(message, text, img)

    @dp.message(F.text == "❓ Остались вопросы")
    async def support_msg(message: Message):
        settings = await get_settings(client_id)
        manager = settings.get("manager_link", "@manager")
        text = settings.get("msg_support") or f"Напиши менеджеру: {manager}"
        img = settings.get("msg_support_img", "")
        await send_msg_with_img(message, text, img)

    @dp.message(F.text == "📚 Ответы на вопросы")
    async def faq_msg(message: Message):
        settings = await get_settings(client_id)
        try:
            faq = json.loads(settings.get("faq_json", "[]"))
        except:
            faq = []
        if not faq:
            await message.answer("FAQ пока не заполнен.", reply_markup=main_menu_kb())
            return
        kb = InlineKeyboardBuilder()
        for i, item in enumerate(faq):
            kb.button(text=item["question"], callback_data=f"faq_{i}")
        kb.adjust(1)
        await message.answer("📚 Выберите вопрос:", reply_markup=kb.as_markup())

    @dp.callback_query(F.data.startswith("faq_"))
    async def faq_answer(callback: CallbackQuery):
        settings = await get_settings(client_id)
        try:
            faq = json.loads(settings.get("faq_json", "[]"))
            idx = int(callback.data.split("_")[1])
            item = faq[idx]
            await callback.message.answer(f"❓ <b>{item['question']}</b>\n\n{item['answer']}", parse_mode="HTML")
        except:
            await callback.message.answer("Ошибка загрузки FAQ.")
        await callback.answer()

    return dp


async def main():
    await init_db()
    clients = await get_all_clients()
    active = [c for c in clients if c["is_active"]]

    if not active:
        print("⚠️ Нет активных клиентов.")
        return

    tasks = []
    for client in active:
        conn = await get_conn()
        row = await conn.fetchrow("SELECT bot_token FROM clients WHERE id=$1", client["id"])
        await conn.close()
        if not row or not row["bot_token"] or row["bot_token"].startswith("pending_"):
            print(f"⚠️ Пропуск {client['bot_name']} — нет токена")
            continue
        try:
            bot = Bot(token=row["bot_token"])
            dp = make_shop_dispatcher(client["id"])
            tasks.append(dp.start_polling(bot))
            print(f"🛍 Запущен бот: {client['bot_name']}")
        except Exception as e:
            print(f"❌ Ошибка запуска {client['bot_name']}: {e}")

    if not tasks:
        print("⚠️ Нет ботов с валидными токенами.")
        return

    print(f"✅ Запущено {len(tasks)} ботов")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
