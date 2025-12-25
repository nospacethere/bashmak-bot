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

def ask_groq(messages, max_tokens=500):
    response = client.chat.completions.create(
        messages=messages, 
        model="llama-3.3-70b-versatile",
        max_tokens=max_tokens
    )
    return response.choices[0].message.content

@dp.message(Command("start"))
async def start(message: types.Message):
    user_history[message.from_user.id] = []
    await message.answer("Мяу! Башмак в здании. Я всё помню, так что не надейся, что твои косяки забудутся.")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    uid = message.from_user.id
    if uid in user_history and user_history[uid]:
        history_str = str(user_history[uid])
        # Для саммари просим МАКСИМАЛЬНО подробно и без ограничений по длине
        res = ask_groq([{"role": "user", "content": f"Сделай очень подробный, детальный и язвительный разбор всей нашей переписки за сегодня. Вспомни всё важное. Не жалей слов: {history_str}"}], max_tokens=1500)
        await message.answer(f"**⚡️ ПОДРОБНЫЙ ОТЧЕТ ПО ТВОИМ ПРЕДЪЯВАМ:**\n\n{res}", parse_mode="Markdown")
    else:
        await message.answer("Мы еще не базарили. Сначала напиши что-нибудь.")

@dp.message()
async def chat(message: types.Message):
    uid = message.from_user.id
    text_lower = message.text.lower() if message.text else ""
    bot_info = await bot.get_me()
    
    # Реакция на имя (башмак, ьашмак, тег) или реплай
    is_calling_me = any(name in text_lower for name in ["башмак", "ьашмак", bot_info.username.lower()])
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    
    if message.chat.type in ["group", "supergroup"] and not (is_calling_me or is_reply):
        return

    if uid not in user_history: user_history[uid] = []
    user_history[uid].append({"role": "user", "content": message.text})

    # Авто-саммари для очистки памяти (> 25 сообщений)
    if len(user_history[uid]) > 25:
        old_data = str(user_history[uid][:15])
        short_mem = ask_groq([{"role": "user", "content": f"Сверни это в одну длинную фразу контекста: {old_data}"}])
        user_history[uid] = [{"role": "system", "content": f"Контекст прошлых терок: {short_mem}"}] + user_history[uid][15:]

    # Настроение и инструкция по длине ответа (2-6 предложений)
    if random.random() < 0.3:
        mood = "Ты милый ласковый кот. Отвечай развернуто, от 2 до 6 предложений. Мурчи и будь добр."
    else:
        mood = "Ты токсичный кот Башмак. Используй мат и сарказм. Отвечай развернуто (2-6 предложений). Не будь кратким, поиздевайся над юзером."
    
    try:
        reply = ask_groq([{"role": "system", "content": mood}] + user_history[uid], max_tokens=600)
        user_history[uid].append({"role": "assistant", "content": reply})
        await message.answer(reply)
    except Exception as e:
        print(f"Ошибка: {e}")

# Саммари в 22:00 по МСК (автоматически)
async def daily_summary_scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        if now.hour == 22 and now.minute == 0:
            for uid, history in user_history.items():
                if history:
                    try:
                        res = ask_groq([{"role": "user", "content": f"Подведи очень детальный итог дня для этого существа: {history}. Не стесняйся в выражениях."}], max_tokens=1500)
                        await bot.send_message(uid, f"📢 **ИТОГИ ДНЯ ОТ БАШМАКА:**\n\n{res}", parse_mode="Markdown")
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
