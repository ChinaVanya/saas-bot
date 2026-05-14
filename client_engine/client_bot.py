import asyncio
import sys
import os
import json

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, WebAppInfo
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

from database.db import (
    get_client_by_code_and_username, get_settings,
    check_promo, get_track, add_track, get_promos
)
from client_config import CLIENT_TOKENS, MINI_APP_URL

import aiohttp


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
    truck_svc = price_rub * settings["truck_percent"] + weight * settings["truck_per_kg"]
    air_svc   = price_rub * settings["air_percent"]   + weight * settings["air_per_kg"]
    return (
        f"📊 <b>Расчёт стоимости</b>\n\n"
        f"💰 Цена: {price_cny} ¥ = {price_rub:.0f} ₽\n"
        f"⚖️ Вес: {weight} кг\n"
        f"💱 Курс: {rate} ₽\n\n"
        f"🚛 <b>Авто (25-40 дней)</b>\n"
        f"Услуги: {truck_svc:.0f} ₽ | Итого: <b>{price_rub+truck_svc:.0f} ₽</b>\n\n"
        f"✈️ <b>Авиа (7-14 дней)</b>\n"
        f"Услуги: {air_svc:.0f} ₽ | Итого: <b>{price_rub+air_svc:.0f} ₽</b>"
    )


class AuthStates(StatesGroup):
    waiting_code = State()

class CalcStates(StatesGroup):
    waiting_price  = State()
    waiting_weight = State()

class TrackStates(StatesGroup):
    waiting_order = State()

class PromoStates(StatesGroup):
    waiting_promo = State()


def client_menu_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="💸 Калькулятор")
    kb.button(text="🔎 Отследить посылку")
    kb.button(text="🤩 Оформить заказ")
    kb.button(text="📚 FAQ")
    kb.button(text="❓ Вопросы")
    kb.button(text="⚙️ Настройки бота")
    kb.adjust(2, 2, 2)
    return kb.as_markup(resize_keyboard=True)


def back_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="◀️ Назад")
    return kb.as_markup(resize_keyboard=True)


def miniapp_kb(client_id):
    kb = InlineKeyboardBuilder()
    kb.button(text="⚙️ Открыть панель управления", web_app=WebAppInfo(url=f"{MINI_APP_URL}?client_id={client_id}"))
    return kb.as_markup()


def make_dispatcher():
    dp = Dispatcher(storage=MemoryStorage())

    @dp.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext):
        await state.clear()
        await state.set_state(AuthStates.waiting_code)
        await message.answer("🔑 Введите код доступа:")

    @dp.message(AuthStates.waiting_code)
    async def check_code(message: Message, state: FSMContext):
        username = message.from_user.username
        if not username:
            await message.answer("❌ У вас нет @username в Telegram. Установите его в настройках.")
            return
        client = await get_client_by_code_and_username(message.text.strip(), username)
        if not client:
            await message.answer("❌ Неверный код или этот код не привязан к вашему аккаунту.\nОбратитесь к продавцу.")
            return
        await state.update_data(client_id=client["id"])
        await state.set_state(None)
        settings = await get_settings(client["id"])
        await message.answer(
            f"✅ <b>Доступ открыт!</b>\n\n{settings.get('welcome_text', 'Добро пожаловать!')}",
            parse_mode="HTML",
            reply_markup=client_menu_kb()
        )
        await message.answer("⚙️ Панель управления ботом:", reply_markup=miniapp_kb(client["id"]))

    @dp.message(F.text == "⚙️ Настройки бота")
    async def open_settings(message: Message, state: FSMContext):
        data = await state.get_data()
        client_id = data.get("client_id")
        if not client_id:
            await message.answer("Сначала введите код (/start)")
            return
        await message.answer("⚙️ Панель управления:", reply_markup=miniapp_kb(client_id))

    @dp.message(F.text == "💸 Калькулятор")
    async def calc_start(message: Message, state: FSMContext):
        data = await state.get_data()
        if not data.get("client_id"):
            await message.answer("Сначала введите код (/start)")
            return
        await state.set_state(CalcStates.waiting_price)
        await message.answer("Введите цену товара в ¥:", reply_markup=back_kb())

    @dp.message(CalcStates.waiting_price, F.text)
    async def calc_price(message: Message, state: FSMContext):
        if message.text == "◀️ Назад":
            await state.set_state(None)
            await message.answer("Главное меню:", reply_markup=client_menu_kb())
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
            settings = await get_settings(data["client_id"])
            result = await calculate(data["price"], weight, settings)
            await state.set_state(None)
            await message.answer(result, parse_mode="HTML", reply_markup=client_menu_kb())
        except ValueError:
            await message.answer("Введите число, например: 1.5")

    @dp.message(F.text == "🔎 Отследить посылку")
    async def track_start(message: Message, state: FSMContext):
        data = await state.get_data()
        if not data.get("client_id"):
            return
        await state.set_state(TrackStates.waiting_order)
        await message.answer("Введите номер заказа:", reply_markup=back_kb())

    @dp.message(TrackStates.waiting_order)
    async def track_check(message: Message, state: FSMContext):
        if message.text == "◀️ Назад":
            await state.set_state(None)
            await message.answer("Главное меню:", reply_markup=client_menu_kb())
            return
        data = await state.get_data()
        track = await get_track(data["client_id"], message.text.strip())
        await state.set_state(None)
        if track:
            await message.answer(f"📦 Трек-номер: <code>{track}</code>", parse_mode="HTML", reply_markup=client_menu_kb())
        else:
            await message.answer("❌ Заказ не найден. Обратитесь к менеджеру.", reply_markup=client_menu_kb())

    @dp.message(F.text == "🤩 Оформить заказ")
    async def order_msg(message: Message, state: FSMContext):
        data = await state.get_data()
        if not data.get("client_id"):
            return
        settings = await get_settings(data["client_id"])
        await message.answer(f"Оформить заказ: {settings.get('manager_link', '@manager')} 👈")

    @dp.message(F.text == "❓ Вопросы")
    async def support_msg(message: Message, state: FSMContext):
        data = await state.get_data()
        if not data.get("client_id"):
            return
        settings = await get_settings(data["client_id"])
        await message.answer(f"Напишите менеджеру: {settings.get('manager_link', '@manager')}")

    @dp.message(F.text == "📚 FAQ")
    async def faq_msg(message: Message, state: FSMContext):
        data = await state.get_data()
        if not data.get("client_id"):
            return
        settings = await get_settings(data["client_id"])
        try:
            faq = json.loads(settings.get("faq_json", "[]"))
        except:
            faq = []
        if not faq:
            await message.answer("FAQ пока не заполнен.", reply_markup=client_menu_kb())
            return
        kb = InlineKeyboardBuilder()
        for i, item in enumerate(faq):
            kb.button(text=item["question"], callback_data=f"faq_{i}")
        kb.adjust(1)
        await message.answer("📚 Выберите вопрос:", reply_markup=kb.as_markup())

    @dp.callback_query(F.data.startswith("faq_"))
    async def faq_answer(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        if not data.get("client_id"):
            return
        settings = await get_settings(data["client_id"])
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
    tasks = []
    dp = make_dispatcher()
    for token in CLIENT_TOKENS:
        bot_instance = Bot(token=token)
        tasks.append(dp.start_polling(bot_instance))
    print(f"🤖 Запущено {len(tasks)} клиентских ботов")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
