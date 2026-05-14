import asyncio
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db import (
    init_db, add_client, get_all_clients,
    deactivate_client, restore_client, delete_client
)
from master_config import MASTER_TOKEN, MASTER_IDS, MINI_APP_URL

bot = Bot(token=MASTER_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


class RegisterStates(StatesGroup):
    username    = State()
    bot_token   = State()
    bot_name    = State()
    access_code = State()


def is_master(user_id):
    return user_id in MASTER_IDS


def master_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить клиента",     callback_data="add_client")
    kb.button(text="📋 Список клиентов",      callback_data="list_clients")
    kb.button(text="🚫 Отключить клиента",    callback_data="deactivate_client")
    kb.button(text="✅ Восстановить клиента", callback_data="restore_client")
    kb.button(text="🗑 Удалить клиента",      callback_data="delete_client")
    kb.adjust(1)
    return kb.as_markup()


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    if not is_master(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer(
        "👑 <b>Панель управления SaaS</b>\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=master_menu_kb()
    )


@dp.callback_query(F.data == "list_clients")
async def cb_list_clients(callback, state: FSMContext):
    if not is_master(callback.from_user.id):
        return
    clients = await get_all_clients()
    if not clients:
        await callback.message.answer("Клиентов пока нет.")
        await callback.answer()
        return
    lines = []
    for cl in clients:
        status = "✅" if cl["is_active"] else "🚫"
        date = str(cl["created_at"])[:10]
        lines.append(f"{status} @{cl['username']} — <b>{cl['bot_name']}</b>\n   📅 {date}")
    await callback.message.answer(
        f"📋 <b>Клиенты ({len(clients)}):</b>\n\n" + "\n\n".join(lines),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "add_client")
async def cb_add_client(callback, state: FSMContext):
    if not is_master(callback.from_user.id):
        return
    await state.set_state(RegisterStates.username)
    await callback.message.answer(
        "➕ <b>Регистрация клиента</b>\n\n<b>Шаг 1/4.</b> Введи @username клиента:",
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(RegisterStates.username)
async def reg_username(message: Message, state: FSMContext):
    username = message.text.strip().lstrip("@").lower()
    if not username.replace("_", "").isalnum():
        await message.answer("❌ Некорректный username. Введи ещё раз:")
        return
    await state.update_data(username=username)
    await state.set_state(RegisterStates.bot_token)
    await message.answer(
        "<b>Шаг 2/4.</b> Введи токен бота клиента\n\n"
        "Получи у @BotFather → /newbot",
        parse_mode="HTML"
    )


@dp.message(RegisterStates.bot_token)
async def reg_bot_token(message: Message, state: FSMContext):
    token = message.text.strip()
    if ":" not in token or len(token) < 30:
        await message.answer("❌ Похоже это не токен. Попробуй снова:")
        return
    await state.update_data(bot_token=token)
    await state.set_state(RegisterStates.bot_name)
    await message.answer("<b>Шаг 3/4.</b> Введи название магазина:", parse_mode="HTML")


@dp.message(RegisterStates.bot_name)
async def reg_bot_name(message: Message, state: FSMContext):
    await state.update_data(bot_name=message.text.strip())
    await state.set_state(RegisterStates.access_code)
    await message.answer(
        "<b>Шаг 4/4.</b> Придумай код доступа\n"
        "Например: <code>SHOP2024</code>",
        parse_mode="HTML"
    )


@dp.message(RegisterStates.access_code)
async def reg_access_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    data = await state.get_data()
    success = await add_client(
        username=data["username"],
        access_code=code,
        bot_token=data["bot_token"],
        bot_name=data["bot_name"]
    )
    await state.clear()
    if success:
        await message.answer(
            f"✅ <b>Клиент зарегистрирован!</b>\n\n"
            f"👤 Username: @{data['username']}\n"
            f"🤖 Бот: {data['bot_name']}\n"
            f"🔑 Код доступа: <code>{code}</code>\n\n"
            f"📲 Клиент пишет боту /start и вводит код.",
            parse_mode="HTML",
            reply_markup=master_menu_kb()
        )
    else:
        await message.answer("❌ Ошибка! Username или код уже существует.", reply_markup=master_menu_kb())


@dp.callback_query(F.data == "deactivate_client")
async def cb_deactivate(callback, state: FSMContext):
    if not is_master(callback.from_user.id):
        return
    await callback.message.answer("🚫 Введи username клиента для отключения:")
    await state.set_state("deactivate_waiting")
    await callback.answer()


@dp.callback_query(F.data == "restore_client")
async def cb_restore(callback, state: FSMContext):
    if not is_master(callback.from_user.id):
        return
    await callback.message.answer("✅ Введи username клиента для восстановления:")
    await state.set_state("restore_waiting")
    await callback.answer()


@dp.callback_query(F.data == "delete_client")
async def cb_delete(callback, state: FSMContext):
    if not is_master(callback.from_user.id):
        return
    await callback.message.answer(
        "🗑 Введи username клиента для УДАЛЕНИЯ\n\n"
        "⚠️ Все данные удалятся безвозвратно!"
    )
    await state.set_state("delete_waiting")
    await callback.answer()


@dp.message(F.text)
async def text_input_handler(message: Message, state: FSMContext):
    current = await state.get_state()
    if not is_master(message.from_user.id):
        return
    if current not in ("deactivate_waiting", "restore_waiting", "delete_waiting"):
        return

    username = message.text.strip().lstrip("@").lower()

    if current == "deactivate_waiting":
        success = await deactivate_client(username)
        await state.clear()
        if success:
            await message.answer(f"✅ @{username} отключён.", reply_markup=master_menu_kb())
        else:
            await message.answer(f"❌ @{username} не найден.", reply_markup=master_menu_kb())

    elif current == "restore_waiting":
        success = await restore_client(username)
        await state.clear()
        if success:
            await message.answer(f"✅ @{username} восстановлен!", reply_markup=master_menu_kb())
        else:
            await message.answer(f"❌ @{username} не найден.", reply_markup=master_menu_kb())

    elif current == "delete_waiting":
        success = await delete_client(username)
        await state.clear()
        if success:
            await message.answer(f"🗑 @{username} удалён.", reply_markup=master_menu_kb())
        else:
            await message.answer(f"❌ @{username} не найден.", reply_markup=master_menu_kb())


async def main():
    await init_db()
    print("👑 Главный бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
