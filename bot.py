import os
import logging

TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = os.environ.get("ADMIN_ID")

if not TOKEN:
    raise ValueError("BOT_TOKEN не найден!")

if not ADMIN_ID:
    raise ValueError("ADMIN_ID не найден!")

ADMIN_ID = int(ADMIN_ID)

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from datetime import datetime
import asyncio
# ==================== НАСТРОЙКА ====================

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

messages_db = {}

# ==================== FSM ====================

class ReplyState(StatesGroup):
    waiting_for_reply = State()

# ==================== ПОЛЬЗОВАТЕЛЬ ====================

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"Напишите сообщение — я передам его администратору.",
        parse_mode="HTML"
    )

# ВАЖНО: работает только без состояния
@dp.message(StateFilter(None))
async def receive_message(message: Message):
    user = message.from_user

    message_data = {
        'user_id': user.id,
        'chat_id': message.chat.id,
        'user_name': user.first_name or "Неизвестный",
        'username': user.username or "нет username",
        'timestamp': datetime.now().isoformat(),
        'type': 'text',
        'content': message.text or "[Медиа]",
        'file_id': None,
        'file_type': None,
        'caption': None
    }

    # Тип контента
    if message.photo:
        message_data.update({
            'type': 'photo',
            'file_id': message.photo[-1].file_id,
            'file_type': 'photo',
            'caption': message.caption
        })
    elif message.video:
        message_data.update({
            'type': 'video',
            'file_id': message.video.file_id,
            'file_type': 'video',
            'caption': message.caption
        })
    elif message.voice:
        message_data.update({
            'type': 'voice',
            'file_id': message.voice.file_id,
            'file_type': 'voice'
        })
    elif message.document:
        message_data.update({
            'type': 'document',
            'file_id': message.document.file_id,
            'file_type': 'document'
        })

    msg_id = len(messages_db)
    messages_db[msg_id] = message_data

    logging.info(f"NEW MSG: {msg_id} from {user.id}")

    await send_to_admin(msg_id, message_data)

    await message.answer("✅ Сообщение отправлено!")

# ==================== ОТПРАВКА АДМИНУ ====================

async def send_to_admin(msg_id: int, data: dict):
    text = (
        f"📨 <b>Новое сообщение</b>\n\n"
        f"👤 {data['user_name']} (@{data['username']})\n"
        f"🆔 <code>{data['user_id']}</code>\n\n"
        f"{data['content']}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_{msg_id}")]
    ])

    try:
        if data['file_type'] == 'photo':
            msg = await bot.send_photo(ADMIN_ID, data['file_id'], caption=text, reply_markup=keyboard, parse_mode="HTML")
        elif data['file_type'] == 'video':
            msg = await bot.send_video(ADMIN_ID, data['file_id'], caption=text, reply_markup=keyboard, parse_mode="HTML")
        elif data['file_type'] == 'voice':
            msg = await bot.send_voice(ADMIN_ID, data['file_id'], caption=text, reply_markup=keyboard)
        elif data['file_type'] == 'document':
            msg = await bot.send_document(ADMIN_ID, data['file_id'], caption=text, reply_markup=keyboard)
        else:
            msg = await bot.send_message(ADMIN_ID, text, reply_markup=keyboard, parse_mode="HTML")

        messages_db[msg_id]['admin_message_id'] = msg.message_id

    except Exception as e:
        logging.error(f"ADMIN SEND ERROR: {e}")

# ==================== АДМИН ====================

@dp.callback_query(F.data.startswith("reply_"), F.from_user.id == ADMIN_ID)
async def reply_handler(callback: CallbackQuery, state: FSMContext):
    msg_id = int(callback.data.split("_")[1])

    if msg_id not in messages_db:
        await callback.answer("❌ Не найдено", show_alert=True)
        return

    chat_id = messages_db[msg_id]['chat_id']

    await state.update_data(msg_id=msg_id, chat_id=chat_id)
    await state.set_state(ReplyState.waiting_for_reply)

    await callback.message.answer(
        "✍️ Напишите ответ\n\n/cancel — отмена"
    )

    await callback.answer()

# Отмена
@dp.message(ReplyState.waiting_for_reply, Command("cancel"), F.from_user.id == ADMIN_ID)
async def cancel_reply(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено")

# Отправка ответа
@dp.message(ReplyState.waiting_for_reply, F.from_user.id == ADMIN_ID)
async def send_reply(message: Message, state: FSMContext):
    data = await state.get_data()

    if not data:
        await message.answer("❌ Состояние потеряно")
        await state.clear()
        return

    chat_id = data['chat_id']

    logging.info(f"REPLY TO: {chat_id}")

    try:
        if message.text:
            await bot.send_message(chat_id, f"📬 Ответ:\n\n{message.text}")
        elif message.photo:
            await bot.send_photo(chat_id, message.photo[-1].file_id, caption=message.caption)
        elif message.video:
            await bot.send_video(chat_id, message.video.file_id, caption=message.caption)
        elif message.document:
            await bot.send_document(chat_id, message.document.file_id, caption=message.caption)
        elif message.voice:
            await bot.send_voice(chat_id, message.voice.file_id)

        await message.answer("✅ Отправлено")

    except Exception as e:
        logging.error(f"USER SEND ERROR: {e}")
        await message.answer(f"❌ Ошибка: {e}")

    await state.clear()

# ==================== ЗАПУСК ====================

async def main():
    logging.info("🤖 Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())