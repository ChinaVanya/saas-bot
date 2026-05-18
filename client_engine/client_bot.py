import asyncio
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage

from client_config import CLIENT_TOKENS, MINI_APP_URL
from database.db import get_client_by_code_and_username, get_conn


def panel_kb(client_type='cargo') -> InlineKeyboardMarkup:
    if client_type == 'shop':
        url = MINI_APP_URL.replace('/app', '/shop')
    else:
        url = MINI_APP_URL
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="⚙️ Открыть панель управления",
            web_app=WebAppInfo(url=url)
        )
    ]])


def make_dispatcher():
    dp = Dispatcher(storage=MemoryStorage())

    @dp.message(CommandStart())
    async def cmd_start(message: Message):
        await message.answer(
            "👋 Добро пожаловать!\n\nНажмите кнопку ниже чтобы войти в панель управления:",
            reply_markup=ReplyKeyboardRemove()
        )
        await message.answer(
            "⚙️ Войти в панель:",
            reply_markup=panel_kb('cargo')
        )

    @dp.message(F.text)
    async def any_message(message: Message):
        await message.answer(
            "Используйте кнопку ниже:",
            reply_markup=panel_kb('cargo')
        )

    return dp


async def main():
    tasks = []
    dp = make_dispatcher()
    for token in CLIENT_TOKENS:
        bot_instance = Bot(token=token)
        tasks.append(dp.start_polling(bot_instance))
    print(f"🤖 Запущено {len(CLIENT_TOKENS)} клиентских ботов")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
