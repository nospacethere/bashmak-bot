import os
import asyncio
import base64
import random
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

# --- ПАМЯТЬ ---
user_history = {} 

def get_history(chat_id):
    if chat_id not in user_history:
        user_history[chat_id] = deque(maxlen=20) # Уменьшил историю для четкости
    return user_history[chat_id]

async def ask_groq_async(messages, model="llama-3.3-70b-versatile", temp=0.7):
    loop = asyncio.get_running_loop()
    def _request():
        try:
            return client.chat.completions.create(
                messages=messages, model=model, max_tokens=150, temperature=temp
            ).choices[0].message.content
        except: return "Мозг кота временно недоступен."
    return await loop.run_in_executor(None, _request)

# --- ФОТО (ВИДИТ И КОММЕНТИРУЕТ) ---
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    is_evil = random.choice([True, False])
    mood = "Ты — токсичный критик, разнеси то, что видишь." if is_evil else "Ты — саркастичный кот, похвали это, но с подколом."
    
    try:
        await bot.send_chat_action(chat_id=message.chat.id, action="upload_photo")
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(file_info.file_path)
        encoded = base64.b64encode(photo_bytes.read()).decode('utf-8')

        prompt = (
            "1. Коротко скажи, что именно на фото.\n"
            f"2. {mood}\n"
            "СТРОГО: Без скобок ))), без текста в духе (смеется). Максимум 2 предложения."
        )

        res = await ask_groq_async([
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}
            ]}
        ], model="llama-3.2-11b-vision-preview")
        await message.reply(res)
    except: await message.reply("Глаза заплыли, не вижу ничего.")

# --- КОМАНДЫ ---
@dp.message(Command("roast"))
async def cmd_roast(message: types.Message):
    history = get_history(message.chat.id)
    if not history: return await message.answer("Чат пустой, жарить некого.")
    
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in history])
    prompt = f"Разнеси этих людей за их тупость: {text_dump}. Пиши максимально коротко и зло. Без воды и скобок."
    
    res = await ask_groq_async([{"role": "user", "content": prompt}], temp=0.9)
    await message.answer(f"☠️ **РАЗНОС:**\n{res}")

@dp.message(Command("start"))
async def start(message: types.Message):
    await bot.set_my_commands([
        BotCommand(command="start", description="Оживить"),
        BotCommand(command="roast", description="Прожарка (коротко)"),
    ])
    await message.answer("😼 Башмак здесь. Кидай фото или пиши. Буду краток, как выстрел.")

# --- ЧАТ ---
@dp.message()
async def chat(message: types.Message):
    if message.from_user.is_bot or not message.text: return
    cid = message.chat.id
    history = get_history(cid)
    if not message.text.startswith('/'):
        history.append({"role": "user", "name": message.from_user.first_name, "content": message.text})

    bot_info = await bot.get_me()
    is_named = "башмак" in message.text.lower()
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    
    if not (message.chat.type == ChatType.PRIVATE or is_named or is_reply): return

    prompt = "Ты Башмак. Будь прямым, злым и ОЧЕНЬ коротким (1 фраза). Никаких скобок и пояснений действий."
    msgs = [{"role": "system", "content": prompt}]
    for m in list(history)[-5:]: msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})

    await bot.send_chat_action(chat_id=cid, action="typing")
    reply = await ask_groq_async(msgs)
    await message.reply(reply)

# --- WEB ---
async def main():
    app = web.Application(); app.router.add_get("/", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    await dp.start_polling(bot)

if __name__ == "__main__": asyncio.run(main())
