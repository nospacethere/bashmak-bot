import os
import asyncio
import datetime
import pytz
import random
from collections import deque
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ChatType
from groq import Groq
from aiohttp import web

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Глобальные переменные
bot_id = None

# --- ПАМЯТЬ ---
user_history = {} 

def get_history(chat_id):
    if chat_id not in user_history:
        user_history[chat_id] = deque(maxlen=50)
    return user_history[chat_id]

# --- МОЗГИ (Llama 3.3 - Стабильная) ---
async def ask_groq_async(messages, max_tokens=1000, temperature=0.7):
    loop = asyncio.get_running_loop()
    def _request():
        try:
            return client.chat.completions.create(
                messages=messages, 
                model="llama-3.3-70b-versatile", # Вернули рабочую лошадку
                max_tokens=max_tokens,
                temperature=temperature
            ).choices[0].message.content
        except Exception as e:
            print(f"Groq Error: {e}")
            return "Мозг отвалился. Данил, чини меня."
    
    return await loop.run_in_executor(None, _request)

# --- КОМАНДЫ ---

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("😼 Башмак перезагружен. Llama V3 в строю. Я злой и я всё помню.")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    cid = message.chat.id
    history = get_history(cid)
    if len(history) < 2:
        await message.answer("Пусто. Нечего обсуждать.")
        return

    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in history])
    prompt = (
        f"Ты — Башмак. Вот переписка:\n{text_dump}\n\n"
        "Сделай краткий, злой и смешной пересказ. "
        "Правила:\n"
        "1. НИКАКИХ СКОБОК С ДЕЙСТВИЯМИ типа (смеется). Только текст.\n"
        "2. Высмеивай участников."
    )
    
    msg = await message.answer("⏳ Читаю...")
    res = await ask_groq_async([{"role": "user", "content": prompt}])
    await msg.edit_text(f"📝 **ИТОГО:**\n\n{res}", parse_mode="Markdown")

@dp.message(Command("roast"))
async def cmd_roast(message: types.Message):
    cid = message.chat.id
    history = get_history(cid)
    if not history:
        await message.answer("Некого жарить.")
        return

    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in history])
    prompt = (
        f"Сделай ЖЕСТОКУЮ прожарку участников чата:\n{text_dump}\n\n"
        "Твоя задача — морально уничтожить.\n"
        "1. Не используй сценические действия в скобках (пауза, смех).\n"
        "2. Будь прямым, грубым и токсичным.\n"
        "3. Используй мат, если нужно."
    )

    msg = await message.answer("🔥 Включаю огнемет...")
    res = await ask_groq_async([{"role": "user", "content": prompt}], temperature=1.0) # Максимальный креатив
    await msg.edit_text(f"☠️ **ПРОЖАРКА:**\n\n{res}", parse_mode="Markdown")

# --- ЧАТ ---
@dp.message()
async def chat(message: types.Message):
    global bot_id
    if message.from_user.is_bot or not message.text: return

    if not bot_id:
        me = await bot.get_me()
        bot_id = me.id

    cid = message.chat.id
    text = message.text
    text_lower = text.lower()
    
    # 1. Запись
    history = get_history(cid)
    if not text.startswith('/'):
        history.append({"role": "user", "name": message.from_user.first_name, "content": text})

    # 2. Триггеры
    is_named = "башмак" in text_lower or "bashmak" in text_lower
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_id
    is_private = message.chat.type == ChatType.PRIVATE # В ЛИЧКЕ ОТВЕЧАЕМ ВСЕГДА
    
    should_answer = is_private or is_named or is_reply

    if not should_answer:
        return

    # 3. Ответ
    system_prompt = (
        "Ты — Башмак, злой и умный кот. "
        "Твоя цель — отвечать коротко и язвительно. "
        "СТРОГИЕ ЗАПРЕТЫ:\n"
        "1. НИКАКИХ ДЕЙСТВИЙ В СКОБКАХ типа (смеется), (ухмыляется). Это кринж.\n"
        "2. НИКАКИХ смайликов-скобочек ')))'.\n"
        "3. Не пиши длинно. 1-2 предложения."
    )

    msgs = [{"role": "system", "content": system_prompt}]
    recent = list(history)[-7:]
    for m in recent:
        msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})

    try:
        # Исправленная команда "печатает..."
        await bot.send_chat_action(chat_id=cid, action="typing")
        
        reply = await ask_groq_async(msgs)
        await message.reply(reply)
    except Exception as e:
        print(f"Chat Error: {e}")

# --- ФОНОВЫЕ ЗАДАЧИ ---
async def scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        # Казино 13:37
        if now.hour == 13 and now.minute == 37:
            for cid in list(user_history.keys()):
                try: await bot.send_dice(cid, emoji='🎰')
                except: pass
            await asyncio.sleep(65)
        await asyncio.sleep(40)

async def health(request): return web.Response(text="Bashmak Live")

async def main():
    app = web.Application(); app.router.add_get("/", health)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    asyncio.create_task(scheduler())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
