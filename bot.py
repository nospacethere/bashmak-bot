import os
import asyncio
import datetime
import pytz
import random
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from groq import Groq
from aiohttp import web

TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

user_history = {}

def ask_groq(messages):
    # Добавляем ограничение на количество токенов в ответе, чтобы не писал мемуары
    response = client.chat.completions.create(
        messages=messages, 
        model="llama-3.3-70b-versatile",
        max_tokens=300 # Ограничиваем длину ответа нейронки
    )
    return response.choices[0].message.content

@dp.message(Command("start"))
async def start(message: types.Message):
    user_history[message.from_user.id] = []
    await message.answer("Мяу! Башмак в здании. Краткость — сестра таланта, так что не жди от меня поэм.")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    uid = message.from_user.id
    if uid in user_history and user_history[uid]:
        history_str = str(user_history[uid])
        # Запрос на итоги
        res = ask_groq([{"role": "user", "content": f"Сделай максимально короткий и дерзкий итог дня (до 200 симв): {history_str}"}])
        await message.answer(f"**Твой день в двух словах:**\n{res}", parse_mode="Markdown")
    else:
        await message.answer("Мы еще не базарили. Пиши давай.")

@dp.message()
async def chat(message: types.Message):
    uid = message.from_user.id
    text_lower = message.text.lower() if message.text else ""
    bot_info = await bot.get_me()
    
    # Проверка на упоминание: башмак, ьашмак, тег или реплай
    is_calling_me = any(name in text_lower for name in ["башмак", "ьашмак", "кот", bot_info.username.lower()])
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    
    if message.chat.type in ["group", "supergroup"] and not (is_calling_me or is_reply):
        return

    if uid not in user_history: user_history[uid] = []
    user_history[uid].append({"role": "user", "content": message.text})

    # Очистка старой памяти через саммари (> 20 сообщений)
    if len(user_history[uid]) > 20:
        old_data = str(user_history[uid][:10])
        short_mem = ask_groq([{"role": "user", "content": f"Сверни это в одну короткую фразу: {old_data}"}])
        user_history[uid] = [{"role": "system", "content": f"Контекст: {short_mem}"}] + user_history[uid][10:]

    # Настроение: 30% добрый / 70% токсик. ТРЕБОВАНИЕ: отвечать КОРОТКО.
    if random.random() < 0.3:
        mood = "Ты милый ласковый кот. Отвечай кратко, мурчи."
    else:
        mood = "Ты дерзкий токсичный кот Башмак. Используй мат, сарказм, но отвечай КРАТКО (1-2 предложения). Не пиши длинные тексты."
    
    try:
        reply = ask_groq([{"role": "system", "content": mood}] + user_history[uid])
        user_history[uid].append({"role": "assistant", "content": reply})
        await message.answer(reply)
    except Exception as e:
        print(f"Ошибка: {e}")

# Веб-сервер для Koyeb
async def health(request): return web.Response(text="Bashmak is alive")

async def main():
    app = web.Application(); app.router.add_get("/", health)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    
    print("Башмак запущен. Коротко и по делу.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
