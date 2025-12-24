import os
import asyncio
import datetime
import pytz
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from groq import Groq
from aiohttp import web

# Конфиг
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MY_CHAT_ID = "ТВОЙ_АЙДИ_ЧАТА" # Сюда бот будет слать итоги дня

client = Groq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Память: {user_id: [messages]}
user_history = {}

def ask_groq(messages, model="llama-3.3-70b-versatile"):
    response = client.chat.completions.create(messages=messages, model=model)
    return response.choices[0].message.content

@dp.message(Command("start"))
async def start(message: types.Message):
    user_history[message.from_user.id] = []
    await message.answer("Мяу, блять! Башмак в здании. Теперь я всё помню и нихрена не прощаю. Чо надо?")

@dp.message()
async def chat(message: types.Message):
    uid = message.from_user.id
    if uid not in user_history: user_history[uid] = []
    
    user_history[uid].append({"role": "user", "content": message.text})

    # Если переписка > 20 сообщений — делаем саммари старой части
    if len(user_history[uid]) > 20:
        old_part = str(user_history[uid][:10])
        summary = ask_groq([{"role": "user", "content": f"Сделай максимально короткую выжимку (до 300 симв) этой херни: {old_part}"}])
        user_history[uid] = [{"role": "system", "content": f"Контекст из прошлого: {summary}"}] + user_history[uid][10:]

    # Промпт: тут настраивается токсичность и маты
    system_prompt = (
        "Ты — Башмак, самый охуевший и токсичный кот в телеграме. "
        "Тебе разрешено и предписано использовать мат, жестко шутить и подкалывать пользователя. "
        "Ты не терпила, ты хозяин. Но при этом ты чертовски умен."
    )

    full_messages = [{"role": "system", "content": system_prompt}] + user_history[uid]
    
    try:
        reply = ask_groq(full_messages)
        user_history[uid].append({"role": "assistant", "content": reply})
        await message.answer(reply)
    except Exception as e:
        await message.answer(f"Сука, ошибка: {e}")

# Рассылка итогов дня в 22:00 по МСК
async def daily_summary_scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        # Если сейчас 22:00
        if now.hour == 22 and now.minute == 0:
            for uid, history in user_history.items():
                if history:
                    report = ask_groq([{"role": "user", "content": f"Подведи итог дня для этого юзера на основе переписки: {history}. Будь краток и язвителен."}])
                    await bot.send_message(uid, f"📢 Итоги твоего просранного дня:\n{report}")
            await asyncio.sleep(60) # Чтобы не спамить в течение этой минуты
        await asyncio.sleep(30)

# Health check для Koyeb
async def health(request): return web.Response(text="Башмак жив!")

async def main():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    
    asyncio.create_task(daily_summary_scheduler()) # Запуск планировщика
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
