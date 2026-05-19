import asyncio
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage

from client_config import MINI_APP_URL
from database.db import init_db, get_all_active_bots


def panel_kb(client_type: str = 'cargo') -> InlineKeyboardMarkup:
    # Для магазина открываем /shop, для карго — /app
    if client_type == 'shop':
        url = MINI_APP_URL.replace('/app', '/shop')
    else:
        url = MINI_APP_URL
    # Убеждаемся что URL начинается с https://
    if not url.startswith("https://"):
        url = "https://" + url
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="⚙️ Открыть панель управления",
            web_app=WebAppInfo(url=url)
        )
    ]])


def make_dispatcher(client_type: str):
    dp = Dispatcher(storage=MemoryStorage())

    @dp.message(CommandStart())
    async def cmd_start(message: Message):
        await message.answer(
            "👋 Добро пожаловать!\n\nНажмите кнопку ниже чтобы войти в панель управления:",
            reply_markup=ReplyKeyboardRemove()
        )
        await message.answer(
            "⚙️ Войти в панель:",
            reply_markup=panel_kb(client_type)
        )

    @dp.message(F.text)
    async def any_message(message: Message):
        await message.answer(
            "Используйте кнопку ниже:",
            reply_markup=panel_kb(client_type)
        )

    return dp


async def main():
    await init_db()

    # Загружаем всех активных клиентов из БД (не из конфига!)
    clients = await get_all_active_bots()

    if not clients:
        print("⚠️ Нет активных клиентов с токенами в базе данных.")
        return

    tasks = []
    for client in clients:
        token = client["bot_token"]
        name = client["bot_name"]
        ctype = client.get("client_type", "cargo")
        try:
            bot_instance = Bot(token=token)
            dp = make_dispatcher(ctype)
            tasks.append(dp.start_polling(bot_instance))
            print(f"🤖 Запущен клиентский бот: {name} (тип: {ctype})")
        except Exception as e:
            print(f"❌ Ошибка запуска бота {name}: {e}")

    if not tasks:
        print("⚠️ Ни один клиентский бот не запустился.")
        return

    print(f"✅ Запущено {len(tasks)} клиентских ботов")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
