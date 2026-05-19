import asyncio
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage

from master_config import MINI_APP_URL
from database.db import init_db

# Токен @pandatest15_bot — бота с Mini App
CLIENT_BOT_TOKEN = os.environ["CLIENT_BOT_TOKEN"]

def panel_kb() -> InlineKeyboardMarkup:
    url = MINI_APP_URL if MINI_APP_URL.startswith("https://") else "https://" + MINI_APP_URL
    # Всегда открываем /app — там клиент вводит код и попадает в нужный интерфейс
    if not url.endswith("/app"):
        url = url.rstrip("/") + "/app"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⚙️ Открыть панель управления", web_app=WebAppInfo(url=url))
    ]])


dp = Dispatcher(storage=MemoryStorage())

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("👋 Добро пожаловать!\n\nНажмите кнопку ниже чтобы войти в панель управления:", reply_markup=ReplyKeyboardRemove())
    await message.answer("⚙️ Войти в панель:", reply_markup=panel_kb())

@dp.message(F.text)
async def any_message(message: Message):
    await message.answer("Используйте кнопку ниже:", reply_markup=panel_kb())


async def main():
    await init_db()
    bot = Bot(token=CLIENT_BOT_TOKEN)
    print(f"🤖 Запущен бот с Mini App")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
