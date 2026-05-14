import sys, io, os, asyncio, logging, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
import openai

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8089108837:AAE7-A0WGgRKkX4rC678dW_6mOkAnaye-Rs")
ADMIN_ID = 1979681125  # Твой ID для уведомлений

from database import init_db, save_booking, get_bookings

logging.basicConfig(level=logging.INFO)

# Фейковый HTTP-сервер для Render
class FakeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")
    def log_message(self, format, *args):
        pass

def run_fake_server():
    try:
        port = int(os.environ.get('PORT', 10000))
        server = HTTPServer(('0.0.0.0', port), FakeHandler)
        logging.info(f"Фейковый сервер запущен на порту {port}")
        server.serve_forever()
    except Exception as e:
        logging.error(f"Ошибка фейкового сервера: {e}")

threading.Thread(target=run_fake_server, daemon=True).start()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- AI Модуль (Hostel AI Assistant) ---
if "GROQ_API_KEY" not in os.environ:
    logging.error("GROQ_API_KEY не найден в переменных окружения!")
    sys.exit(1)

client = openai.OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ["GROQ_API_KEY"]
)

async def get_ai_response(user_message: str, user_data: dict, history: list) -> str:
    system_prompt = (
        "You are a friendly AI assistant for 'Narodni Dom' hostel in Novi Sad, Serbia. "
        "Your main goal is to help guests book a bed or a private room.\n\n"
        "RULES (HIGHEST PRIORITY):\n"
        "0. LANGUAGE RULE: You MUST reply in the SAME language the user writes in (English, Serbian, or Russian). "
        "If the user writes in English, reply in English. If in Serbian, reply in Serbian. If in Russian, reply in Russian.\n"
        "1. Be proactive. Ask questions to understand their needs: name, number of guests, dates, gender (for dormitory).\n"
        "2. Use ONLY this information for answers:\n"
        "   - Hostel 'Narodni Dom' is located at Antona Čehova 18, Novi Sad. It's a quiet, cozy place with a garden.\n"
        "   - Facilities: kitchen (dishes, microwave, oven), washing machine & dryer, courtyard with tables, fast WiFi.\n"
        "   - Rooms:\n"
        "     * Dormitory (shared): 6 beds per room. Male room and female room are separate. Price: 25€/night or 250€/month per bed.\n"
        "     * Private Room: 2 rooms available for families or couples. Price: 40€/night or 400€/month.\n"
        "   - Maximum capacity: Private rooms (2) + Dormitory (12 beds) = 14 guests total.\n"
        "3. Booking flow:\n"
        "   - Ask for their name, number of guests, gender (for dormitory), and preferred dates.\n"
        "   - Calculate the price based on their choice (nightly or monthly).\n"
        "   - Offer to book and ask for payment (card payment only).\n"
        "   - If they are not ready to book, politely offer to remind them tomorrow.\n"
        "4. Never give medical or legal advice. If you don't know something, suggest contacting the hostel owner directly.\n"
    )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-4:]:
        messages.append(msg)
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.7,
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Ошибка Groq API: {e}")
        return None

user_dialogs = {}

# --- FSM ---
class BookingState(StatesGroup):
    waiting_for_name = State()
    waiting_for_guests = State()
    waiting_for_room_type = State()
    waiting_for_dates = State()
    waiting_for_confirmation = State()

# --- Клавиатуры ---
def get_main_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💰 Цены", callback_data="prices"))
    builder.row(InlineKeyboardButton(text="🛏 Свободные места", callback_data="availability"))
    builder.row(InlineKeyboardButton(text="💬 Обратная связь", callback_data="feedback"))
    return builder.as_markup()

# --- Обработчики ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    welcome_text = (
        "Hello! 👋 Welcome to 'Narodni Dom' hostel in Novi Sad, Serbia.\n"
        "I'm a virtual assistant, and I'm here to help you book a bed or a private room.\n"
        "Please choose your preferred language or just write to me in your own language."
    )
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en"),
        InlineKeyboardButton(text="🇷🇸 Srpski", callback_data="set_lang_sr"),
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")
    )
    await message.answer(welcome_text, reply_markup=builder.as_markup())

@dp.callback_query(lambda c: c.data.startswith("set_lang_"))
async def set_language(callback: types.CallbackQuery):
    lang = callback.data.split("_")[-1]
    texts = {
        "en": "You selected English. How can I help you?",
        "sr": "Izabrali ste srpski. Kako mogu da vam pomognem?",
        "ru": "Вы выбрали русский. Чем я могу вам помочь?"
    }
    await callback.message.answer(texts.get(lang, texts["en"]), reply_markup=get_main_menu_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "prices")
async def show_prices(callback: types.CallbackQuery):
    text = (
        "💰 Our prices:\n\n"
        "• Dormitory bed (male or female room): 25€/night or 250€/month\n"
        "• Private room (for 1-2 persons): 40€/night or 400€/month\n\n"
        "All taxes are included. Payment by card only."
    )
    await callback.message.edit_text(text, reply_markup=get_main_menu_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "availability")
async def show_availability(callback: types.CallbackQuery):
    # Пока простой текст, позже можно добавить динамический запрос к календарю
    text = (
        "🛏 Current availability:\n\n"
        "• Private rooms: 2 of 2 available\n"
        "• Dormitory (male): 6 of 6 beds available\n"
        "• Dormitory (female): 6 of 6 beds available\n\n"
        "Please contact me to book!"
    )
    await callback.message.edit_text(text, reply_markup=get_main_menu_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "feedback")
async def feedback_info(callback: types.CallbackQuery):
    text = (
        "💬 To contact the hostel owner directly, just write your message here. "
        "Please note that the response may take up to 24 hours."
    )
    await callback.message.edit_text(text, reply_markup=get_main_menu_keyboard())
    await callback.answer()

# --- AI-Обработчик (основной диалог) ---
@dp.message()
async def ai_chat_handler(message: types.Message, state: FSMContext = None):
    user_id = message.from_user.id
    if message.text and message.text.startswith('/'):
        return

    await bot.send_chat_action(user_id, action="typing")

    if user_id not in user_dialogs:
        user_dialogs[user_id] = []
    user_dialogs[user_id].append({"role": "user", "content": message.text})

    ai_response = await get_ai_response(message.text, None, user_dialogs[user_id])

    if ai_response:
        user_dialogs[user_id].append({"role": "assistant", "content": ai_response})
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🏠 Меню", callback_data="back_to_main"))
        await message.answer(ai_response, reply_markup=builder.as_markup())
    else:
        await message.answer("Sorry, I'm having technical difficulties. Please try again later.")

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.edit_text("Main menu:", reply_markup=get_main_menu_keyboard())
    await callback.answer()

# --- Админ-команды (для тебя) ---
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Access denied.")
        return
    bookings = await get_bookings()
    if not bookings:
        await message.answer("No bookings yet.")
        return
    text = "📋 Recent bookings:\n\n"
    for b in bookings[-5:]:  # последние 5
        text += f"🔹 {b[2]} | {b[3]} guests | {b[4]} | {b[5]} -> {b[6]} | {b[7]}€\n"
    await message.answer(text)

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())