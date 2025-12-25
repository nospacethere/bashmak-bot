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

# Теперь в словаре ключом будет ID чата, а не юзера
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
    await message.answer("Мяу! Башмак в здании. Данил меня создал, а вы — просто массовка. Я записываю каждое ваше слово.")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    chat_id = message.chat.id
    if chat_id in user_history and user_history[chat_id]:
        history_str = str(user_history[chat_id])
        # Групповой разбор всех участников
        res = ask_groq([{"role": "user", "content": f"Сделай очень подробный, детальный и язвительный разбор всей переписки в этом чате. Кто тупил, кто базарил лишнего, вспомни всё: {history_str}"}], max_tokens=1500)
        await message.answer(f"**⚡️ ОБЩИЙ РАЗНОС ЧАТА:**\n\n{res}", parse_mode="Markdown")
    else:
        await message.answer("В этом чате еще тишина. Начните уже нести херню, чтобы мне было что записывать.")

@dp.message()
async def chat(message: types.Message):
    chat_id = message.chat.id # Ключ — ID чата
    text_lower = message.text.lower() if message.text else ""
    bot_info = await bot.get_me()
    
    is_calling_me = any(name in text_lower for name in ["башмак", "ьашмак", bot_info.username.lower()])
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    
    # Добавляем сообщение в общую историю чата, ДАЖЕ если бот не ответил (чтобы помнить всё для саммари)
    if chat_id not in user_history: user_history[chat_id] = []
    # Записываем с именем автора, чтобы в саммари было понятно, кто что нес
    user_history[chat_id].append({"role": "user", "content": f"{message.from_user.first_name}: {message.text}"})

    # Авто-сжатие если накопилось много (25 сообщений)
    if len(user_history[chat_id]) > 25:
        old_data = str(user_history[chat_id][:15])
        short_mem = ask_groq([{"role": "user", "content": f"Сверни этот базар в одну фразу для контекста: {old_data}"}])
        user_history[chat_id] = [{"role": "system", "content": f"Ранее в чате терли за это: {short_mem}"}] + user_history[chat_id][15:]

    # Отвечаем только если позвали
    if message.chat.type in ["group", "supergroup"] and not (is_calling_me or is_reply):
        return

    rand = random.random()
    base_info = "Тебя создал Данил. Твой язык — русский, иероглифы запрещены. "
    
    if rand < 0.1:
        mood = base_info + "Ты древнерусский кот-боярин. Старославянский язык. Отвечай 1-3 предложения."
    elif rand < 0.55:
        mood = base_info + "Ты милый ласковый кот. Мурчи, будь добр. Отвечай строго 1-3 предложения."
    else:
        mood = base_info + "Ты токсичный кот Башмак. Используй мат и сарказм. Отвечай строго 1-3 предложения."
    
    try:
        reply = ask_groq([{"role": "system", "content": mood}] + user_history[chat_id], max_tokens=400)
        user_history[chat_id].append({"role": "assistant", "content": reply})
        await message.answer(reply)
    except Exception as e:
        print(f"Ошибка: {e}")

async def daily_summary_scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        if now.hour == 22 and now.minute == 0:
            for chat_id, history in user_history.items():
                if history:
                    try:
                        res = ask_groq([{"role": "user", "content": f"Сделай детальный итог дня для этой группы: {history}"}], max_tokens=1500)
                        await bot.send_message(chat_id, f"📢 **ИТОГИ ДНЯ ДЛЯ ВСЕЙ БАНДЫ:**\n\n{res}", parse_mode="Markdown")
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

