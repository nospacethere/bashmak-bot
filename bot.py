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

# Глобальные данные бота (заполнятся при старте)
bot_id = None
bot_username = ""

# --- ПАМЯТЬ ---
user_history = {} 

def get_history(chat_id):
    if chat_id not in user_history:
        user_history[chat_id] = deque(maxlen=50)
    return user_history[chat_id]

# --- МОЗГИ (DeepSeek R1) ---
async def ask_groq_async(messages, max_tokens=1000, temperature=0.6):
    loop = asyncio.get_running_loop()
    def _request():
        try:
            return client.chat.completions.create(
                messages=messages, 
                model="deepseek-r1-distill-llama-70b",
                max_tokens=max_tokens,
                temperature=temperature
            ).choices[0].message.content
        except Exception as e:
            print(f"Groq Error: {e}")
            return "Бля, у меня мозги заклинило. Попробуй позже."
    
    res = await loop.run_in_executor(None, _request)
    # Убираем теги раздумий <think>, если DeepSeek их выдает
    if "</think>" in res:
        res = res.split("</think>")[-1].strip()
    return res

# --- КОМАНДЫ ---

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("😼 Башмак в здании. DeepSeek заряжен, скобки запрещены, жопы под угрозой.")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    cid = message.chat.id
    history = get_history(cid)
    if len(history) < 2:
        await message.answer("Тут пусто, как в твоей голове.")
        return

    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in history])
    prompt = (
        f"Ты — Башмак, циничный кот. Вот переписка:\n{text_dump}\n\n"
        "Сделай жесткий и правдивый итог. Высмеивай тупость. "
        "НИКАКИХ СКОБОК ')))' И НИКАКИХ ПОЯСНЕНИЙ В СКОБКАХ."
    )
    
    msg = await message.answer("⏳ Анализирую этот мусор...")
    res = await ask_groq_async([{"role": "user", "content": prompt}])
    await msg.edit_text(f"📝 **ИТОГО:**\n\n{res}", parse_mode="Markdown")

@dp.message(Command("roast"))
async def cmd_roast(message: types.Message):
    cid = message.chat.id
    history = get_history(cid)
    if not history:
        await message.answer("Некого жарить, все вымерли.")
        return

    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in history])
    prompt = (
        f"Ты — Башмак. Сделай ЗЛУЮ и ЯЗВИТЕЛЬНУЮ прожарку участников этого чата:\n{text_dump}\n\n"
        "Правила:\n"
        "1. Будь максимально грубым и прямым (как просил Данил).\n"
        "2. НИКАКИХ СКОБОЧЕК ')))', никаких '(смеется)', '(пауза)'.\n"
        "3. Не подлизывайся к Данилу, даже если он босс — жарь всех честно.\n"
        "4. Используй мат для акцента. Пиши только текст."
    )

    msg = await message.answer("🔥 Разогреваю гриль...")
    res = await ask_groq_async([{"role": "user", "content": prompt}], temperature=0.9)
    await msg.edit_text(f"☠️ **РАЗНОС:**\n\n{res}", parse_mode="Markdown")

# --- ОБРАБОТКА ЧАТА ---
@dp.message()
async def chat(message: types.Message):
    global bot_id, bot_username
    if message.from_user.is_bot or not message.text: return

    # Подгружаем данные бота, если их нет
    if not bot_id:
        me = await bot.get_me()
        bot_id = me.id
        bot_username = me.username.lower()

    cid = message.chat.id
    text = message.text
    text_lower = text.lower()
    
    # 1. Сначала записываем в историю (чтобы summary и roast работали)
    history = get_history(cid)
    if not text.startswith('/'):
        history.append({"role": "user", "name": message.from_user.first_name, "content": text})

    # 2. Проверяем, надо ли отвечать текстом
    is_named = "башмак" in text_lower or "bashmak" in text_lower
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_id
    is_private = message.chat.type == ChatType.PRIVATE
    
    # В личке отвечаем на всё, в группах — если позвали или ответили боту
    should_answer = is_private or is_named or is_reply

    if not should_answer:
        return

    # 3. Генерируем ответ
    system_prompt = (
        "Ты — Башмак, кот Данила. Ты циничный, прямой и справедливый. "
        "Данил просил тебя быть прямым, даже если это звучит обидно. "
        "ЗАПРЕТЫ:\n"
        "1. НИКОГДА НЕ ИСПОЛЬЗУЙ СКОБКИ ТИПА ')))' ИЛИ '((('.\n"
        "2. НИКАКИХ ПОЯСНЕНИЙ ТИПА '(смеется)' ИЛИ '(взял микрофон)'. Только прямая речь.\n"
        "3. Пиши коротко (1-3 предложения), если не просят иначе.\n"
        "4. Используй эмодзи 🗿, 💀, 🤡, если надо."
    )

    msgs = [{"role": "system", "content": system_prompt}]
    # Берем последние 10 сообщений для контекста
    recent = list(history)[-10:]
    for m in recent:
        msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})

    try:
        async with message.chat_action("typing"):
            reply = await ask_groq_async(msgs)
            await message.reply(reply)
    except Exception as e:
        print(f"Chat Error: {e}")

# --- СЛУЖЕБНОЕ ---
async def scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        if now.hour == 13 and now.minute == 37:
            for cid in list(user_history.keys()):
                try: await bot.send_dice(cid, emoji='🎰')
                except: pass
            await asyncio.sleep(65)
        await asyncio.sleep(40)

async def health(request): return web.Response(text="Bashmak is hungry")

async def main():
    app = web.Application(); app.router.add_get("/", health)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    asyncio.create_task(scheduler())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
