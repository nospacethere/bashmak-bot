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

# Память: {user_id: [messages]}
user_history = {}

def ask_groq(messages, model="llama-3.3-70b-versatile"):
    response = client.chat.completions.create(messages=messages, model=model)
    return response.choices[0].message.content

@dp.message(Command("start"))
async def start(message: types.Message):
    user_history[message.from_user.id] = []
    await message.answer("Мяу, блять! Башмак в сети. Буду за тобой присматривать... или обоссу тапки, как пойдет.")

@dp.message()
async def chat(message: types.Message):
    uid = message.from_user.id
    chat_type = message.chat.type
    bot_info = await bot.get_me()

    # Фильтр для групп: отвечаем только на имя или реплай
    if chat_type in ["group", "supergroup"]:
        is_mentioned = message.text and (f"@{bot_info.username}" in message.text or "Башмак" in message.text)
        is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
        if not (is_mentioned or is_reply):
            return

    if uid not in user_history: user_history[uid] = []
    user_history[uid].append({"role": "user", "content": message.text})

    # Саммари при переполнении памяти (20 сообщений)
    if len(user_history[uid]) > 20:
        old_part = str(user_history[uid][:10])
        summary = ask_groq([{"role": "user", "content": f"Сделай краткое саммари (до 300 симв) этой истории: {old_part}"}])
        user_history[uid] = [{"role": "system", "content": f"Контекст: {summary}"}] + user_history[uid][10:]

    # Механика настроения: 30% шанс на доброту
    is_good_mood = random.random() < 0.3
    if is_good_mood:
        system_prompt = "Ты — Башмак, но у тебя сейчас редкое хорошее настроение. Ты милый, ласковый кот, который любит своего хозяина, мурчит и дает добрые советы. Но всё равно оставайся котом."
    else:
        system_prompt = "Ты — Башмак, токсичный, злой и дерзкий кот. Используй мат, сарказм и всячески подкалывай пользователя. Ты хозяин этого чата."

    try:
        reply = ask_groq([{"role": "system", "content": system_prompt}] + user_history[uid])
        user_history[uid].append({"role": "assistant", "content": reply})
        await message.answer(reply)
    except Exception as e:
        print(f"Ошибка: {e}")

# Итоги дня в 22:00 по МСК
async def daily_summary_scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        if now.hour == 22 and now.minute == 0:
            for uid, history in user_history.items():
                if history:
                    try:
                        report = ask_groq([{"role": "user", "content": f"Подведи итог дня на основе истории: {history}. Будь краток и язвителен."}])
                        await bot.send_message(uid, f"📢 Итоги дня от Башмака:\n{report}")
                    except: pass
            await asyncio.sleep(60)
        await asyncio.sleep(30)

# Health check для Koyeb
async def health(request): return web.Response(text="Башмак жив!")

async def main():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    
    asyncio.create_task(daily_summary_scheduler())
    print("Башмак запущен с биполяркой!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
