import asyncio
import sys
import os
import json
import base64

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

from database.db import init_db, get_all_clients, get_settings, check_promo, get_track

import aiohttp

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GPT_LIMIT = 5
gpt_usage = {}

TRACKING_URLS = {
    'track24':  'https://track24.ru/?code=',
    '17track':  'https://www.17track.net/ru/track?nums=',
    'pochta':   'https://www.pochta.ru/tracking#',
    'cainiao':  'https://global.cainiao.com/detail.htm?mailNoList=',
}


async def get_cny_rate() -> float:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json(content_type=None)
                return round(data["Valute"]["CNY"]["Value"] / data["Valute"]["CNY"]["Nominal"], 2)
    except:
        return 13.0


async def calculate(price_cny, weight, settings) -> str:
    rate = await get_cny_rate()
    price_rub = price_cny * rate

    lines = [
        f"📊 <b>Расчёт стоимости доставки</b>\n\n"
        f"💰 Цена товара: {price_cny} ¥ = {price_rub:.0f} ₽\n"
        f"⚖️ Вес: {weight} кг\n"
        f"💱 Курс юаня: {rate} ₽\n"
    ]

    # Читаем какие тарифы включены
    try:
        enabled = json.loads(settings.get("tariff_enabled", "{}"))
    except:
        enabled = {}

    if enabled.get("normal", True):
        np_ = settings.get("normal_percent", 0.08)
        nk_ = settings.get("normal_per_kg", 200)
        svc = price_rub * np_ + weight * nk_
        lines.append(f"\n📦 <b>Обычный (35-50 дней)</b>\nУслуги: {svc:.0f} ₽ | Итого: <b>{price_rub+svc:.0f} ₽</b>")

    if enabled.get("truck", True):
        tp_ = settings.get("truck_percent", 0.11)
        tk_ = settings.get("truck_per_kg", 350)
        svc = price_rub * tp_ + weight * tk_
        lines.append(f"\n🚛 <b>Авто (25-40 дней)</b>\nУслуги: {svc:.0f} ₽ | Итого: <b>{price_rub+svc:.0f} ₽</b>")

    if enabled.get("air", True):
        ap_ = settings.get("air_percent", 0.17)
        ak_ = settings.get("air_per_kg", 700)
        svc = price_rub * ap_ + weight * ak_
        lines.append(f"\n✈️ <b>Авиа (7-14 дней)</b>\nУслуги: {svc:.0f} ₽ | Итого: <b>{price_rub+svc:.0f} ₽</b>")

    if enabled.get("express", True):
        ep_ = settings.get("express_percent", 0.25)
        ek_ = settings.get("express_per_kg", 1200)
        svc = price_rub * ep_ + weight * ek_
        lines.append(f"\n⚡ <b>Экспресс (5-7 дней)</b>\nУслуги: {svc:.0f} ₽ | Итого: <b>{price_rub+svc:.0f} ₽</b>")

    return "".join(lines)


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


def make_shop_dispatcher(client_id: int):
    dp = Dispatcher(storage=MemoryStorage())

    @dp.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext):
        await state.clear()
        settings = await get_settings(client_id)
        text    = settings.get("welcome_text", "Добро пожаловать! 👋")
        await message.answer(text, reply_markup=main_menu_kb())

    # ── КАЛЬКУЛЯТОР — входное меню ──
    @dp.message(F.text == "💸 Калькулятор стоимости")
    async def calc_main(message: Message, state: FSMContext):
        await state.clear()
        await message.answer("Выберите действие:", reply_markup=calc_menu_kb())

    @dp.message(F.text == "🏠 Главное меню")
    async def go_home(message: Message, state: FSMContext):
        await state.clear()
        await message.answer("Главное меню:", reply_markup=main_menu_kb())

    @dp.message(F.text == "💸 Рассчитать стоимость")
    async def calc_start(message: Message, state: FSMContext):
        await state.set_state(CalcStates.waiting_price)
        await message.answer(
            "Введите цену товара в ¥ или пришлите скриншот:",
            reply_markup=back_kb()
        )

    @dp.message(CalcStates.waiting_price, F.photo)
    async def calc_photo(message: Message, state: FSMContext):
        if not OPENAI_API_KEY:
            await message.answer("Распознавание фото недоступно. Введите цену числом:")
            return
        user_id = message.from_user.id
        if gpt_usage.get(user_id, 0) >= GPT_LIMIT:
            await message.answer(f"❌ Лимит {GPT_LIMIT} распознаваний/день исчерпан. Введите цену вручную:")
            return
        msg = await message.answer("🔍 Анализируем фото...")
        photo = message.photo[-1]
        file_info = await message.bot.get_file(photo.file_id)
        photo_bytes = await message.bot.download_file(file_info.file_path)
        b64 = base64.b64encode(photo_bytes.getvalue()).decode()
        try:
            from openai import OpenAI
            oa = OpenAI(api_key=OPENAI_API_KEY)
            response = oa.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "Find price in Yuan and weight in kg. Return ONLY: price;weight;name. Example: 25;0.2;AirPods. If not found: ERROR"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}],
                max_tokens=50
            )
            result = response.choices[0].message.content.strip()
            if "ERROR" in result or ";" not in result:
                await msg.edit_text("❌ Не удалось найти цену. Введите вручную:")
                return
            price, weight, name = result.split(";")
            price, weight = float(price), float(weight)
            gpt_usage[user_id] = gpt_usage.get(user_id, 0) + 1
            settings = await get_settings(client_id)
            result_text = await calculate(price, weight, settings)
            await state.clear()
            await msg.edit_text(
                f"✅ <b>{name}</b>\n\n{result_text}",
                parse_mode="HTML",
                reply_markup=calc_menu_kb()
            )
        except Exception as e:
            await msg.edit_text("❌ Ошибка. Введите цену вручную:")

    @dp.message(CalcStates.waiting_price, F.text)
    async def calc_price(message: Message, state: FSMContext):
        if message.text == "◀️ Назад":
            await state.clear()
            await message.answer("Выберите действие:", reply_markup=calc_menu_kb())
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

    # ── ПРОМОКОД ──
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
            await message.answer(
                f"✅ Промокод активирован! Скидка: <b>{discount}%</b>",
                parse_mode="HTML",
                reply_markup=calc_menu_kb()
            )
        else:
            await message.answer("❌ Промокод не найден.", reply_markup=calc_menu_kb())

    # ── ОТСЛЕЖИВАНИЕ ──
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
        if track:
            settings = await get_settings(client_id)
            site = settings.get("tracking_site", "track24")
            base_url = TRACKING_URLS.get(site, TRACKING_URLS["track24"])
            track_url = base_url + track
            await message.answer(
                f"📦 <b>Заказ {order_id}</b>\n"
                f"Трек-номер: <code>{track}</code>\n\n"
                f"<a href=\"{track_url}\">🔗 Отследить посылку</a>",
                parse_mode="HTML",
                reply_markup=main_menu_kb()
            )
        else:
            await message.answer("❌ Заказ не найден. Обратитесь к менеджеру.", reply_markup=main_menu_kb())

    # ── ЗАКАЗ ──
    @dp.message(F.text == "🤩 Оформить заказ")
    async def order_msg(message: Message):
        settings = await get_settings(client_id)
        manager = settings.get("manager_link", "@manager")
        await message.answer(f"Оформить заказ: {manager} 👈\n\nОтправь скриншот товара или ссылку.")

    # ── ПОДДЕРЖКА ──
    @dp.message(F.text == "❓ Остались вопросы")
    async def support_msg(message: Message):
        settings = await get_settings(client_id)
        manager = settings.get("manager_link", "@manager")
        await message.answer(f"Напиши менеджеру: {manager}")

    # ── FAQ ──
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
            await callback.message.answer(
                f"❓ <b>{item['question']}</b>\n\n{item['answer']}",
                parse_mode="HTML"
            )
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
        from database.db import get_conn
        conn = await get_conn()
        row = await conn.fetchrow("SELECT bot_token FROM clients WHERE id=$1", client["id"])
        await conn.close()
        if not row or row["bot_token"].startswith("pending_"):
            continue
        bot = Bot(token=row["bot_token"])
        dp = make_shop_dispatcher(client["id"])
        tasks.append(dp.start_polling(bot))
        print(f"🛍 Запущен бот: {client['bot_name']}")

    if not tasks:
        print("⚠️ Нет ботов с токенами.")
        return

    print(f"✅ Запущено {len(tasks)} ботов")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
