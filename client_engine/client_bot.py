import asyncio
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from database.db import get_client_by_code_and_username, get_settings
from client_config import CLIENT_TOKENS, MINI_APP_URL


class AuthStates(StatesGroup):
    waiting_code = State()


def panel_kb(client_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="⚙️ Открыть панель управления",
            web_app=WebAppInfo(url=f"{MINI_APP_URL}?client_id={client_id}")
        )
    ]])


def make_dispatcher():
    dp = Dispatcher(storage=MemoryStorage())

    @dp.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext):
        await state.clear()
        # Убираем все reply-кнопки
        await message.answer("🔑 Введите код доступа:", reply_markup=ReplyKeyboardRemove())

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
        welcome = settings.get("welcome_text", "Добро пожаловать!")

        await message.answer(
            f"✅ <b>Доступ открыт!</b>\n\n{welcome}\n\nНажмите кнопку ниже для управления ботом:",
            parse_mode="HTML",
            reply_markup=panel_kb(client["id"])
        )

    @dp.message(F.text)
    async def any_message(message: Message, state: FSMContext):
        data = await state.get_data()
        client_id = data.get("client_id")

        if not client_id:
            await state.set_state(AuthStates.waiting_code)
            await message.answer("🔑 Введите код доступа:")
            return

        # Если уже авторизован — просто показываем панель
        await message.answer(
            "Используйте кнопку ниже для управления ботом:",
            reply_markup=panel_kb(client_id)
        )

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
