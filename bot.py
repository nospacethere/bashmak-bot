import os
import asyncio
import datetime
import pytz
import random
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from groq import Groq
from aiohttp import web

# Настройки
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Общая память по ID чата
user_history = {}

def ask_groq(messages, max_tokens=500):
    response = client.chat.completions.create(
        messages=messages, 
        model="llama-3.3-70b-versatile",
        max_tokens=max_tokens
    )
    return response.choices[0].message.content

@dp.message(Command("start"))
async def start(message: types.Message):
    user_history[message.chat.id] = []
    await message.answer("Мяу! Башмак в здании. Данил меня создал, а вы — кожаные мешки. Я всё записываю.")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    cid = message.chat.id
    # Проверяем историю именно по ID чата
    if cid in user_history and len(user_history[cid]) > 0:
        history_str = ""
        for msg in user_history[cid]:
            if msg['role'] == 'user':
                history_str += f"{msg['content']}\n"
        
        # Короткий и угарный промпт
        prompt = (
            f"Ты — Башмак, кот Данила. Сделай КРАТКИЙ (до 500 симв) и УГАРНЫЙ пересказ этого пиздежа: {history_str}. "
            "Пиши ТОЛЬКО на русском. Напиши 3-4 коротких пункта стеба. Никаких лекций и иероглифов!"
        )
        try:
            res = ask_groq([{"role": "user", "content": prompt}], max_tokens=600)
            await message.answer(f"**⚡️ ЧО ВЫ ТУТ ПОНАПИСАЛИ:**\n\n{res}", parse_mode="Markdown")
        except:
            await message.answer("Бля, чет не получается вспомнить. Пишите еще.")
    else:
        await message.answer("Тут пусто. Нечего пересказывать, тупицы.")

@dp.message()
async def chat(message: types.Message):
    cid = message.chat.id
    text_lower = message.text.lower() if message.text else ""
    bot_info = await bot.get_me()
    
    # 1. Сначала ВСЕГДА записываем сообщение в историю чата для саммари
    if cid not in user_history: 
        user_history[cid] = []
    
    # Не записываем сами команды в историю
    if not text_lower.startswith('/'):
        user_history[cid].append({"role": "user", "content": f"{message.from_user.first_name}: {message.text}"})

    # Ограничение памяти
    if len(user_history[cid]) > 30:
        user_history[cid] = user_history[cid][-20:]

    # 2. Проверяем, нужно ли отвечать
    is_calling_me = any(name in text_lower for name in ["башмак", "ьашмак", bot_info.username.lower()])
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    
    if message.chat.type in ["group", "supergroup"] and not (is_calling_me or is_reply):
        return

    # 3. Формируем ответ
    rand = random.random()
    base_info = "Тебя создал Данил. Твой язык — РУССКИЙ. Иероглифы ЗАПРЕЩЕНЫ. "
    
    if rand < 0.1: # Боярин
        mood = base_info + "Ты древнерусский кот-боярин. Старославянский стиль. Ответ строго 1-2 предл."
    elif rand < 0.55: # Добрый
        mood = base_info + "Ты милый ласковый кот. Мурчи. Ответ строго 1-2 предложения."
    else: # Токсик
        mood = base_info + "Ты токсичный Башмак. Мат и сарказм. Ответ строго 1-2 фразы."
    
    try:
        reply = ask_groq([{"role": "system", "content": mood}] + user_history[cid][-10:], max_tokens=300)
        await message.answer(reply)
    except Exception as e:
        print(f"Ошибка: {e}")

async def daily_summary_scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        if now.hour == 22 and now.minute == 0:
            for cid, history in user_history.items():
                if history:
                    try:
                        res = ask_groq([{"role": "user", "content": f"Краткий и язвительный итог дня для чата: {history}"}], max_tokens=600)
                        await bot.send_message(cid, f"📢 **ИТОГИ ДНЯ:**\n\n{res}", parse_mode="Markdown")
                    except: pass
            await asyncio.sleep(60)
        await asyncio.sleep(30)

async def health(request): return web.Response(text="Bashmak is alive")

async def main():
    app = web.Application(); app.router.add_get("/", health)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    asyncio.create_task(daily_summary_scheduler())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
