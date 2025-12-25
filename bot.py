import os
import asyncio
import datetime
import pytz
import random
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from groq import Groq
from aiohttp import web

# Настройки доступа
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
    await message.answer("Мяу! Башмак в здании. Данил меня создал, чтобы я за вами присматривал. Не бесите меня.")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    chat_id = message.chat.id
    if chat_id in user_history and user_history[chat_id]:
        history_str = str(user_history[chat_id])
        # Саммари теперь короткое, дерзкое и по пунктам
        prompt = (
            f"Ты — Башмак. Сделай КРАТКИЙ (до 600 симв) и УГАРНЫЙ пересказ этого пиздежа: {history_str}. "
            "Никакого официоза! Напиши 3-5 коротких пунктов: кто тупил, кто нес чушь. "
            "Используй мат, стеби всех. Будь лаконичен, как пуля!"
        )
        res = ask_groq([{"role": "user", "content": prompt}], max_tokens=600)
        await message.answer(f"**⚡️ ЧО ВЫ ТУТ ПОНАПИСАЛИ (коротко):**\n\n{res}", parse_mode="Markdown")
    else:
        await message.answer("Тут пусто. Начните уже нести херню, чтобы мне было что пересказать.")

@dp.message()
async def chat(message: types.Message):
    chat_id = message.chat.id
    text_lower = message.text.lower() if message.text else ""
    bot_info = await bot.get_me()
    
    # Проверка на имя или реплай
    is_calling_me = any(name in text_lower for name in ["башмак", "ьашмак", bot_info.username.lower()])
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    
    # Записываем всё в историю с именем автора для будущего саммари
    if chat_id not in user_history: user_history[chat_id] = []
    user_history[chat_id].append({"role": "user", "content": f"{message.from_user.first_name}: {message.text}"})

    # Сжатие истории (держим последние 15 сообщений + контекст)
    if len(user_history[chat_id]) > 25:
        old_data = str(user_history[chat_id][:15])
        short_mem = ask_groq([{"role": "user", "content": f"Сверни этот базар в одну короткую фразу: {old_data}"}])
        user_history[chat_id] = [{"role": "system", "content": f"Контекст: {short_mem}"}] + user_history[chat_id][15:]

    # Если в группе не позвали — молчим, но запоминаем
    if message.chat.type in ["group", "supergroup"] and not (is_calling_me or is_reply):
        return

    # Логика настроения 50/50 и личности
    rand = random.random()
    base_info = "Тебя создал Данил. Пиши ТОЛЬКО на русском, иероглифы — табу. "
    
    if rand < 0.1: # Древнерусский прикол
        mood = base_info + "Ты кот-боярин. Говори на старославянском (аз есмь, вельми). Отвечай строго 1-2 предложения."
    elif rand < 0.55: # Добрый
        mood = base_info + "Ты милый ласковый кот. Мурчи, будь добр. Отвечай строго 1-2 предложения."
    else: # Токсик
        mood = base_info + "Ты токсичный Башмак. Используй мат, сарказм и издевки. Отвечай строго 1-2 фразы."
    
    try:
        reply = ask_groq([{"role": "system", "content": mood}] + user_history[chat_id], max_tokens=400)
        user_history[chat_id].append({"role": "assistant", "content": reply})
        await message.answer(reply)
    except Exception as e:
        print(f"Ошибка: {e}")

# Авто-итоги в 22:00
async def daily_summary_scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        if now.hour == 22 and now.minute == 0:
            for chat_id, history in user_history.items():
                if history:
                    try:
                        res = ask_groq([{"role": "user", "content": f"Сделай КРАТКИЙ и язвительный итог дня для этой банды: {history}"}], max_tokens=600)
                        await bot.send_message(chat_id, f"📢 **ИТОГИ ДНЯ ОТ БАШМАКА:**\n\n{res}", parse_mode="Markdown")
                    except: pass
            await asyncio.sleep(60)
        await asyncio.sleep(30)

# Веб-сервер для Koyeb (Health Check)
async def health(request): return web.Response(text="Bashmak is alive")

async def main():
    app = web.Application(); app.router.add_get("/", health)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    
    asyncio.create_task(daily_summary_scheduler())
    print("Башмак обновлен и готов к труду!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
