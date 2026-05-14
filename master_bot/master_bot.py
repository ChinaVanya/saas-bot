"""
ГЛАВНЫЙ БОТ (master_bot.py)
Этот бот — только для тебя (владельца SaaS).
Через него ты регистрируешь клиентов и управляешь ими.
"""

import asyncio
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db import (
    init_db, add_client, get_all_clients,
    deactivate_client, restore_client, delete_client,
    get_client_by_code_and_username
)
from master_config import MASTER_TOKEN, MASTER_IDS, MINI_APP_URL

bot = Bot(token=MASTER_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ───────────────────────────────────────────
#  Состояния
# ───────────────────────────────────────────

class RegisterStates(StatesGroup):
    username    = State()
    bot_token   = State()
    bot_name    = State()
    access_code = State()


# ───────────────────────────────────────────
#  Хелперы
# ───────────────────────────────────────────

def is_master(user_id: int) -> bool:
    return user_id in MASTER_IDS


def master_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить клиента",    callback_data="add_client")
    kb.button(text="📋 Список клиентов",     callback_data="list_clients")
    kb.button(text="🚫 Отключить клиента",   callback_data="deactivate_client")
    kb.button(text="✅ Восстановить клиента", callback_data="restore_client")
    kb.button(text="🗑 Удалить клиента",      callback_data="delete_client")
    kb.adjust(1)
    return kb.as_markup()


# ───────────────────────────────────────────
#  /start — только для владельца
# ───────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    if not is_master(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    await message.answer(
        "👑 <b>Панель управления SaaS</b>\n\n"
        "Здесь ты управляешь клиентами и их ботами.\n"
        "Выбери действие:",
        parse_mode="HTML",
        reply_markup=master_menu_kb()
    )


# ───────────────────────────────────────────
#  Список клиентов
# ───────────────────────────────────────────

@dp.callback_query(F.data == "list_clients")
async def cb_list_clients(callback, state: FSMContext):
    if not is_master(callback.from_user.id):
        return

    clients = get_all_clients()
    if not clients:
        await callback.message.answer("Клиентов пока нет.")
        await callback.answer()
        return

    lines = []
    for cl in clients:
        status = "✅" if cl["is_active"] else "🚫"
        lines.append(
            f"{status} @{cl['username']} — <b>{cl['bot_name']}</b>\n"
            f"   📅 {cl['created_at'][:10]}"
        )

    await callback.message.answer(
        f"📋 <b>Клиенты ({len(clients)}):</b>\n\n" + "\n\n".join(lines),
        parse_mode="HTML"
    )
    await callback.answer()


# ───────────────────────────────────────────
#  Добавление клиента (4 шага)
# ───────────────────────────────────────────

@dp.callback_query(F.data == "add_client")
async def cb_add_client(callback, state: FSMContext):
    if not is_master(callback.from_user.id):
        return
    await state.set_state(RegisterStates.username)
    await callback.message.answer(
        "➕ <b>Регистрация нового клиента</b>\n\n"
        "<b>Шаг 1/4.</b> Введи @username клиента\n"
        "(именно с этого аккаунта он будет входить в панель):",
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
        "📌 Как получить:\n"
        "1. Зайди в @BotFather\n"
        "2. /newbot → придумай имя → получи токен\n"
        "3. Скопируй сюда (вида <code>123456:ABC-DEF...</code>)",
        parse_mode="HTML"
    )


@dp.message(RegisterStates.bot_token)
async def reg_bot_token(message: Message, state: FSMContext):
    token = message.text.strip()
    # Простая проверка формата токена
    if ":" not in token or len(token) < 30:
        await message.answer("❌ Похоже это не токен. Попробуй снова:")
        return
    await state.update_data(bot_token=token)
    await state.set_state(RegisterStates.bot_name)
    await message.answer(
        "<b>Шаг 3/4.</b> Введи название магазина клиента\n"
        "(например: <i>ЧайнаВаня</i> или <i>ShopBot</i>):",
        parse_mode="HTML"
    )


@dp.message(RegisterStates.bot_name)
async def reg_bot_name(message: Message, state: FSMContext):
    await state.update_data(bot_name=message.text.strip())
    await state.set_state(RegisterStates.access_code)
    await message.answer(
        "<b>Шаг 4/4.</b> Придумай код доступа для клиента\n\n"
        "Это пароль, который клиент введёт при первом входе.\n"
        "Например: <code>SHOP2024</code> или <code>VANYA777</code>\n\n"
        "⚠️ Код чувствителен к регистру (будет сохранён в ВЕРХНЕМ):",
        parse_mode="HTML"
    )


@dp.message(RegisterStates.access_code)
async def reg_access_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    data = await state.get_data()

    success = add_client(
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
            f"📲 Клиент должен:\n"
            f"1. Написать <b>этому боту</b> /start\n"
            f"2. Ввести код: <code>{code}</code>\n"
            f"3. Откроется его панель управления",
            parse_mode="HTML",
            reply_markup=master_menu_kb()
        )
    else:
        await message.answer(
            "❌ Ошибка! Возможно этот username или код уже существует.",
            reply_markup=master_menu_kb()
        )


# ───────────────────────────────────────────
#  Деактивация клиента
# ───────────────────────────────────────────

@dp.callback_query(F.data == "deactivate_client")
async def cb_deactivate(callback, state: FSMContext):
    if not is_master(callback.from_user.id):
        return
    await callback.message.answer(
        "🚫 Введи @username клиента которого нужно отключить:"
    )
    await state.set_state("deactivate_waiting")
    await callback.answer()


@dp.message(F.text, lambda m: True)
async def text_input_handler(message: Message, state: FSMContext):
    current = await state.get_state()
    if not is_master(message.from_user.id):
        return

    username = message.text.strip().lstrip("@").lower()

    if current == "deactivate_waiting":
        success = deactivate_client(username)
        await state.clear()
        if success:
            await message.answer(f"✅ Клиент @{username} отключён.", reply_markup=master_menu_kb())
        else:
            await message.answer(f"❌ Клиент @{username} не найден.", reply_markup=master_menu_kb())

    elif current == "restore_waiting":
        success = restore_client(username)
        await state.clear()
        if success:
            await message.answer(f"✅ Клиент @{username} восстановлён!", reply_markup=master_menu_kb())
        else:
            await message.answer(f"❌ Клиент @{username} не найден.", reply_markup=master_menu_kb())

    elif current == "delete_waiting":
        success = delete_client(username)
        await state.clear()
        if success:
            await message.answer(f"🗑 Клиент @{username} удалён вместе со всеми данными.", reply_markup=master_menu_kb())
        else:
            await message.answer(f"❌ Клиент @{username} не найден.", reply_markup=master_menu_kb())



# ───────────────────────────────────────────
#  Восстановление клиента
# ───────────────────────────────────────────

@dp.callback_query(F.data == "restore_client")
async def cb_restore(callback, state: FSMContext):
    if not is_master(callback.from_user.id):
        return
    await callback.message.answer("✅ Введи @username клиента которого нужно восстановить:")
    await state.set_state("restore_waiting")
    await callback.answer()


# ───────────────────────────────────────────
#  Удаление клиента
# ───────────────────────────────────────────

@dp.callback_query(F.data == "delete_client")
async def cb_delete(callback, state: FSMContext):
    if not is_master(callback.from_user.id):
        return
    await callback.message.answer(
        "🗑 Введи @username клиента которого нужно УДАЛИТЬ"
        "⚠️ Все данные (промокоды, треки, настройки) будут удалены безвозвратно!"
    )
    await state.set_state("delete_waiting")
    await callback.answer()


# ───────────────────────────────────────────
#  Запуск
# ───────────────────────────────────────────

async def main():
    init_db()
    print("👑 Главный бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
