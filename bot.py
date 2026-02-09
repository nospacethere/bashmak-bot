import os, asyncio, base64, random
from collections import deque
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.types import BotCommand
from groq import Groq
from aiohttp import web

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ПАМЯТЬ (уменьшил до 15 сообщений, чтобы не было "воды")
user_history = {} 
def get_history(chat_id):
    if chat_id not in user_history: user_history[chat_id] = deque(maxlen=15)
    return user_history[chat_id]

async def ask_groq_async(messages, model="llama-3.3-70b-versatile", temp=0.7):
    loop = asyncio.get_running_loop()
    def _request():
        try:
            return client.chat.completions.create(
                messages=messages, model=model, max_tokens=150, temperature=temp
            ).choices[0].message.content
        except: return "У меня кошачий ступор. Попробуй позже."
    return await loop.run_in_executor(None, _request)

# --- ФОТО (ВИДИТ И КОММЕНТИРУЕТ) ---
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    try:
        await bot.send_chat_action(chat_id=message.chat.id, action="upload_photo")
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(file_info.file_path)
        encoded = base64.b64encode(photo_bytes.read()).decode('utf-8')

        # Смягчил промпт, чтобы не триггерить цензуру, но оставил стёб
        prompt = "Ты — Башмак. 1. Скажи, что на фото. 2. Прокомментируй это с сарказмом. Максимум 2 фразы. Никаких скобочек."

        res = await ask_groq_async([
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}
            ]}
        ], model="llama-3.2-11b-vision-preview")
        await message.reply(res)
    except: await message.reply("Глаза запотели, не вижу.")

# --- КОМАНДЫ ---
@dp.message(Command("roast"))
async def cmd_roast(message: types.Message):
    history = get_history(message.chat.id)
    if not history: return await message.answer("Чат пустой.")
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in history])
    # Переписал промпт, чтобы он был "ироничным шоу", так нейронка меньше капризничает
    prompt = f"Ты — стендап-комик Башмак. Высмей этот диалог очень коротко и едко:\n{text_dump}\nБЕЗ скобок и БЕЗ длинных речей."
    res = await ask_groq_async([{"role": "user", "content": prompt}], temp=0.9)
    await message.answer(f"☠️ **РАЗНОС:**\n{res}")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    history = get_history(message.chat.id)
    if not history: return await message.answer("Нечего подытоживать.")
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in history])
    prompt = f"Коротко и дерзко перескажи, о чем тут ныли:\n{text_dump}\nМаксимум 2 предложения."
    res = await ask_groq_async([{"role": "user", "content": prompt}])
    await message.answer(f"📝 **ИТОГО:**\n{res}")

@dp.message(Command("start"))
async def start(message: types.Message):
    await bot.set_my_commands([
        BotCommand(command="start", description="Оживить"),
        BotCommand(command="roast", description="Разнос чата"),
        BotCommand(command="summary", description="Итоги бреда"),
    ])
    await message.answer("😼 Башмак в деле. Меню команд обновил. Кидай фото или пиши.")

# --- ЧАТ ---
@dp.message()
async def chat(message: types.Message):
    if message.from_user.is_bot or not message.text: return
    history = get_history(message.chat.id)
    if not message.text.startswith('/'):
        history.append({"role": "user", "name": message.from_user.first_name, "content": message.text})

    is_named = "башмак" in message.text.lower()
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == (await bot.get_me()).id
    if not (message.chat.type == ChatType.PRIVATE or is_named or is_reply): return

    prompt = "Ты Башмак, злой кот. Отвечай ОЧЕНЬ коротко (1 фраза). СТРОГИЙ ЗАПРЕТ на скобки типа )) и действия в скобках."
    msgs = [{"role": "system", "content": prompt}]
    for m in list(history)[-5:]: msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})

    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    reply = await ask_groq_async(msgs)
    await message.reply(reply)

# --- СЕРВЕР ---
async def main():
    app = web.Application(); app.router.add_get("/", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    await dp.start_polling(bot)

if __name__ == "__main__": asyncio.run(main())
