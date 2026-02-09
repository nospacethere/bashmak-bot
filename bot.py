import os
import asyncio
import datetime
import pytz
import random
from collections import deque
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from groq import Groq
from aiohttp import web

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Инициализация
client = Groq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()
my_username = ""  # Сюда запомним имя бота

# --- ПАМЯТЬ ---
user_history = {} 

def get_history(chat_id):
    if chat_id not in user_history:
        user_history[chat_id] = deque(maxlen=50) # Помним 50 последних сообщений
    return user_history[chat_id]

# --- МОЗГИ (DeepSeek + Llama) ---
async def ask_groq_async(messages, max_tokens=800, temperature=0.8, model="deepseek-r1-distill-llama-70b"):
    loop = asyncio.get_running_loop()
    def _request():
        try:
            # Пытаемся юзать DeepSeek (он умнее и злее)
            return client.chat.completions.create(
                messages=messages, 
                model=model,
                max_tokens=max_tokens,
                temperature=temperature
            ).choices[0].message.content
        except Exception as e:
            # Если DeepSeek перегружен, переключаемся на Llama 3.3
            print(f"DeepSeek error, switching to Llama: {e}")
            return client.chat.completions.create(
                messages=messages, 
                model="llama-3.3-70b-versatile",
                max_tokens=max_tokens,
                temperature=temperature
            ).choices[0].message.content
    
    return await loop.run_in_executor(None, _request)

# --- КОМАНДЫ ---

@dp.message(Command("start"))
async def start(message: types.Message):
    global my_username
    me = await bot.get_me()
    my_username = me.username.lower()
    await message.answer("👁 Башмак видит всё. DeepSeek активирован. Готовьте жопы.")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    cid = message.chat.id
    history = get_history(cid)
    
    if len(history) < 3:
        await message.answer("Нечего читать. Напишите хоть что-то.")
        return

    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in history])
    
    prompt = (
        f"Ты — Башмак. Вот переписка:\n{text_dump}\n\n"
        "Сделай ЖЕСТКИЙ и СМЕШНОЙ пересказ. "
        "1. Вскрой суть: о чем реально базарили (деньги, нытье, игры).\n"
        "2. Стеби тупые моменты.\n"
        "3. ЗАПРЕТ НА СКОБКИ ')))'. Используй слова или эмодзи.\n"
        "4. Формат: 'Короче, расклад такой:' и пункты."
    )
    
    msg = await message.answer("⏳ Анализирую этот бред...")
    try:
        res = await ask_groq_async([{"role": "user", "content": prompt}])
        # DeepSeek иногда выдает мысли в тегах <think>, убираем их если есть
        clean_res = res.split("</think>")[-1].strip()
        await msg.edit_text(f"📝 **СВОДКА:**\n\n{clean_res}", parse_mode="Markdown")
    except:
        await msg.edit_text("Мозг перегрелся. Слишком много тупости.")

@dp.message(Command("roast"))
async def cmd_roast(message: types.Message):
    """ЗЛАЯ ПРОЖАРКА"""
    cid = message.chat.id
    history = get_history(cid)
    
    if not history:
        await message.answer("Кого жарить? Пусто.")
        return

    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in history])
    prompt = (
        f"Ты — стендап-комик с чернейшим юмором. Вот чат:\n{text_dump}\n\n"
        "Твоя задача — УНИЧТОЖИТЬ участников морально. Выбери жертву (кто больше всех писал или тупил) и сделай прожарку.\n"
        "1. Будь грубым, переходи на личности (в шутку, но обидно).\n"
        "2. Высмеивай грамотность, логику и темы.\n"
        "3. НИКАКИХ ')))'. Смех через 'АХАХА' или '🤡'.\n"
        "4. Используй мат, если в тему."
    )

    try:
        await message.answer("🔥 Разогреваю гриль...")
        res = await ask_groq_async([{"role": "user", "content": prompt}])
        clean_res = res.split("</think>")[-1].strip()
        await message.answer(f"☠️ **ПРОЖАРКА:**\n\n{clean_res}", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"Осечка: {e}")

# --- ЧАТ ---
@dp.message()
async def chat(message: types.Message):
    global my_username
    if message.from_user.is_bot or not message.text: return

    # Инициализация имени бота, если вдруг не прогрузилось
    if not my_username:
        me = await bot.get_me()
        my_username = me.username.lower()

    cid = message.chat.id
    text = message.text
    text_lower = text.lower()
    
    # 1. Запоминаем
    history = get_history(cid)
    if not text.startswith('/'):
        history.append({"role": "user", "name": message.from_user.first_name, "content": text})

    # 2. ПРОВЕРКА ТРИГГЕРА (Упрощенная и надежная)
    # Реагируем, если:
    # - В тексте есть "башмак"
    # - Это ответ (Reply) на сообщение бота
    # - Это личка (Private)
    is_named = "башмак" in text_lower or "bashmak" in text_lower
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot.id
    is_private = message.chat.type == "private"
    
    should_answer = is_named or is_reply or is_private

    # Рандомный врыв (3% шанс), но только если сообщение длиннее 2 слов
    if not should_answer and random.random() < 0.03 and len(text.split()) > 2:
        should_answer = True

    if not should_answer:
        return

    # 3. ГЕНЕРАЦИЯ ОТВЕТА
    
    # Контекст (последние 7 сообщений для скорости)
    msgs = [{"role": "system", "content": (
        "Ты — Башмак, кот Данила. Твой характер: циничный, умный, немного злой. "
        "Твоя цель — отвечать смешно и по фактам. "
        "ПРАВИЛА:\n"
        "1. НИКОГДА не ставь скобки типа ')))' или '((('. Это для лохов. Используй эмодзи 🗿, 💀, 🤡.\n"
        "2. Если тебя оскорбляют — оскорбляй в ответ жестче.\n"
        "3. Не пиши длинные лекции. 1-2 предложения, максимум 3.\n"
        "4. Ты любишь азартные игры и ненавидишь тупость."
    )}]
    
    # Докидываем историю
    recent = list(history)[-7:]
    for m in recent:
        msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})

    # Финальный пинок нейронке
    msgs.append({"role": "user", "content": f"Ответь на последнее сообщение ({message.from_user.first_name}: {text}). Будь дерзким."})

    try:
        async with message.chat_action("typing"):
            # Для обычных ответов юзаем Llama 3.3 (она быстрее отвечает в чате), 
            # но если хочешь супер-ум — можно и DeepSeek, но будет задержка 2-3 сек.
            # Оставил DeepSeek, раз просил "крутую".
            res = await ask_groq_async(msgs, max_tokens=250, model="deepseek-r1-distill-llama-70b")
            
            # Чистим "мысли" модели (DeepSeek любит писать <think>...</think>)
            clean_res = res.split("</think>")[-1].strip()
            
            await message.reply(clean_res)
    except Exception as e:
        print(f"Chat Error: {e}")

# --- ФОНОВЫЕ ЗАДАЧИ ---
async def scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        # Казино в 13:37
        if now.hour == 13 and now.minute == 37:
            for cid in list(user_history.keys()):
                try:
                    await bot.send_message(cid, "🎰 КАЗИНО ОТКРЫТО! КТО НЕ РИСКУЕТ — ТОТ ПЕС!")
                    await bot.send_dice(cid, emoji='🎰')
                except: pass
            await asyncio.sleep(65)
        else:
            await asyncio.sleep(40)

async def health(request): return web.Response(text="Bashmak Online")

async def main():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    
    asyncio.create_task(scheduler())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
