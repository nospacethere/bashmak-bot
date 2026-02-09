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

# --- ПАМЯТЬ ---
# Используем deque с макс длиной 50, чтобы старые сообщения сами удалялись
user_history = {} 

def get_history(chat_id):
    if chat_id not in user_history:
        user_history[chat_id] = deque(maxlen=50)
    return user_history[chat_id]

# --- ФУНКЦИЯ ЗАПРОСА К МОЗГАМ ---
async def ask_groq_async(messages, max_tokens=600, temperature=0.7):
    # Делаем вызов асинхронным через run_in_executor, чтобы бот не тупил при генерации
    loop = asyncio.get_running_loop()
    def _request():
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
    get_history(message.chat.id) # Инициализация памяти
    await message.answer("😼 Башмак проснулся. Я — кот Данила. Готовьтесь к унижениям и мудрости.")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    cid = message.chat.id
    history = get_history(cid)
    
    if len(history) < 5:
        await message.answer("Тут слишком тихо. Напишите хоть что-то, чтобы я мог это обосрать.")
        return

    # Собираем текст
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in history])
    
    prompt = (
        f"Ты — Башмак, циничный и угарный кот. Вот переписка кожаных мешков:\n{text_dump}\n\n"
        "Твоя задача: написать СМЕШНОЙ саммари (итог) того, о чем они говорили.\n"
        "1. Выдели главные темы.\n"
        "2. Стеби их нещадно.\n"
        "3. Используй сленг, можно немного мата, но без криминала.\n"
        "4. Формат: Заголовок + 3-4 пули (пункта).\n"
        "Язык: Русский."
    )
    
    try:
        msg = await message.answer("⏳ Читаю ваши бредни...")
        res = await ask_groq_async([{"role": "user", "content": prompt}])
        await msg.edit_text(f"📝 **ОТЧЕТ БАШМАКА:**\n\n{res}", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"Мозг отвалился: {e}")

@dp.message(Command("roast"))
async def cmd_roast(message: types.Message):
    """Новая фича: Прожарка участников"""
    cid = message.chat.id
    history = get_history(cid)
    
    if not history:
        await message.answer("Кого жарить? Тут пусто.")
        return

    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in history])
    prompt = (
        f"Ты — стендап-комик в теле кота. Вот последние сообщения:\n{text_dump}\n\n"
        "Выбери самого активного или глупого участника и сделай про него смешную, жесткую прожарку (roast). "
        "Высмеивай их стиль общения, орфографию и темы. Будь злым, но смешным."
    )

    try:
        res = await ask_groq_async([{"role": "user", "content": prompt}])
        await message.answer(f"🔥 **ПРОЖАРКА:**\n\n{res}", parse_mode="Markdown")
    except:
        await message.answer("Мне лень жарить, я спать.")

# --- ОБРАБОТКА СООБЩЕНИЙ ---
@dp.message()
async def chat(message: types.Message):
    # Игнорим сообщения от ботов и пустые
    if message.from_user.is_bot or not message.text:
        return

    cid = message.chat.id
    text = message.text
    text_lower = text.lower()
    user_name = message.from_user.first_name
    
    # 1. Запоминаем (всегда)
    history = get_history(cid)
    # Не запоминаем команды
    if not text.startswith('/'):
        history.append({"role": "user", "name": user_name, "content": text})

    # 2. Триггеры ответа
    bot_info = await bot.get_me()
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    is_named = any(n in text_lower for n in ["башмак", "кот", "кис", bot_info.username.lower()])
    
    # В группах отвечаем только если позвали, в личке — всегда
    is_private = message.chat.type == "private"
    should_answer = is_named or is_reply or is_private

    # Шанс рандомного врыва в разговор (5%)
    if not should_answer and random.random() < 0.05:
        should_answer = True

    if not should_answer:
        return

    # 3. Выбор личности
    rand = random.random()
    
    # Базовый контекст с историей
    msgs_for_ai = [{"role": "system", "content": "Ты — Башмак, кот Данила. Ты живешь в Телеграме."}]
    
    # Добавляем последние 10 сообщений для контекста разговора
    recent_history = list(history)[-10:]
    for m in recent_history:
        msgs_for_ai.append({"role": "user", "content": f"{m['name']}: {m['content']}"})

    # Стили общения
    if rand < 0.15: # 15% Боярин
        style = "Ты — Древнерусский Кот-Боярин. Говоришь на старославянском, пафосно, называешь всех 'холопами' или 'смердами'. Ответ короткий."
    elif rand < 0.50: # 35% Токсик
        style = "Ты — уличный кот-гопник. Используешь сленг, 'че', 'слыш'. Ты дерзкий, но справедливый. Любишь рыбу и пивас. Ответ 1-2 предложения."
    elif rand < 0.80: # 30% Обычный угар
        style = "Ты — просто ленивый домашний кот. Тебе все лень. Ты отвечаешь с сарказмом и неохотой. Просишь еды."
    else: # 20% Философ
        style = "Ты — кот-философ с глубокого похмелья. Рассуждаешь о тщетности бытия и пустоте миски. Очень мрачно и смешно."

    # Добавляем стиль В КОНЕЦ, чтобы он перекрыл историю
    msgs_for_ai.append({"role": "system", "content": f"{style} ОТВЕЧАЙ КОРОТКО (макс 2 предложения). НЕ используй иероглифы."})

    try:
        # Имитация печати
        async with message.chat_action("typing"):
            reply = await ask_groq_async(msgs_for_ai, max_tokens=200, temperature=0.8)
            await message.reply(reply)
    except Exception as e:
        print(f"Error: {e}")

# --- ПЛАНИРОВЩИК (КАЗИНО И ИТОГИ) ---
async def scheduler():
    print("⏰ Планировщик запущен...")
    while True:
        try:
            now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
            
            # --- 13:37 CASINO TIME ---
            if now.hour == 13 and now.minute == 37:
                for cid in list(user_history.keys()): # list() нужен, чтобы словарь не менялся во время итерации
                    try:
                        await bot.send_message(cid, "🎰 ВРЕМЯ ЛУДОМАНИИ! СТАВЛЮ СВОЙ ВИСКАС!")
                        dice_msg = await bot.send_dice(cid, emoji='🎰')
                        
                        # Ждем чуть-чуть, пока кубик прокрутится
                        await asyncio.sleep(4)
                        
                        val = dice_msg.dice.value
                        # 64 - это джекпот (три семерки или типа того в тг)
                        if val in [1, 22, 43, 64]: # Выигрышные комбо (условно)
                            await bot.send_message(cid, "ДЖЕКПОТ БЛЯТЬ!! С ВАС СМЕТАНА! 🥛")
                        elif val < 10:
                            await bot.send_message(cid, "Лох не мамонт... Я проиграл.")
                        else:
                            await bot.send_message(cid, "Ну такое. Ни рыбы, ни мяса.")
                            
                    except Exception as e:
                        print(f"Ошибка казино в {cid}: {e}")
                
                # Спим 65 секунд, чтобы не отправить дважды в одну минуту
                await asyncio.sleep(65)

            # --- 22:00 ИТОГИ ДНЯ ---
            elif now.hour == 22 and now.minute == 0:
                for cid, history in user_history.items():
                    if len(history) > 5:
                        text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in history])
                        prompt = f"Подведи итоги дня для чата. Будь краток и язвителен. История:\n{text_dump}"
                        try:
                            res = await ask_groq_async([{"role": "user", "content": prompt}])
                            await bot.send_message(cid, f"🌙 **БАШМАК УХОДИТ СПАТЬ:**\n\n{res}", parse_mode="Markdown")
                        except: pass
                await asyncio.sleep(65)

            else:
                # Проверяем каждую минуту
                await asyncio.sleep(40)

        except Exception as e:
            print(f"Ошибка в планировщике: {e}")
            await asyncio.sleep(60)

# --- ЗАПУСК ---
async def health(request): 
    return web.Response(text="Bashmak is alive and gambling")

async def main():
    # Запускаем веб-сервер для Koyeb (чтобы не усыплял)
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8000)
    await site.start()
    
    # Запускаем планировщик в фоне
    asyncio.create_task(scheduler())
    
    # Удаляем вебхук на всякий случай и запускаем бота
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Башмак пошел спать.")
