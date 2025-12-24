import asyncio
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from groq import Groq
from aiohttp import web

# Ключи
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
ai_client = Groq(api_key=GROQ_API_KEY)
messages_history = []

# --- ЗАГЛУШКА ДЛЯ KOYEB ---
async def handle(request):
    return web.Response(text="Bashmak is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    # Koyeb дает порт в переменной окружения PORT
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
# --------------------------

async def get_ai_answer(system_prompt, user_text):
    try:
        completion = ai_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}]
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"AI Error: {e}")
        return None

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    summary = await get_ai_answer("Ты — кот Башмак. Расскажи сплетни кратко.", "\n".join(messages_history) if messages_history else "Тишина.")
    await message.answer(f"🐾 **Башмак вкинул:**\n\n{summary}")

@dp.message(F.text)
async def handle_text(message: types.Message):
    messages_history.append(f"{message.from_user.first_name}: {message.text}")
    if len(messages_history) > 300: messages_history.pop(0)
    if "башмак" in message.text.lower() or (message.reply_to_message and message.reply_to_message.from_user.id == bot.id):
        ans = await get_ai_answer("Ты — кот Башмак. Отвечай кратко.", message.text)
        if ans: await message.reply(ans)

async def main():
    print("Башмак на новом месте!")
    # Запускаем веб-сервер для Koyeb
    asyncio.create_task(start_web_server())
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())