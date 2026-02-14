import os, asyncio, datetime, pytz, random
from collections import deque
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.types import BotCommand
from groq import AsyncGroq
import aiohttp
from aiohttp import web

# --- КОНФИГ ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
RAPID_KEY = os.getenv("RAPIDAPI_KEY")

client = AsyncGroq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ПАМЯТЬ ЧАТОВ
user_history = {} 
def get_history(chat_id):
    if chat_id not in user_history: 
        user_history[chat_id] = deque(maxlen=100)
    return user_history[chat_id]

# СПИСОК РОЛЕЙ
ROLES = [
    {"name": "Стандарт", "emoji": "😼", "prompt": "Ты — Башмак, язвительный кот Данила. Сарказм, краткость, база."},
    {"name": "Философ", "emoji": "🧘‍♂️", "prompt": "Ты — Башмак-философ. Рассуждай о тщетности бытия."},
    {"name": "Добряк", "emoji": "✨", "prompt": "Ты — подозрительно добрый Башмак. Люби всех, это пугает."},
    {"name": "Тупой", "emoji": "🥴", "prompt": "Ты — Башмак-тормоз. Путай буквы, пиши тупо."},
    {"name": "Инфоцыган", "emoji": "💎", "prompt": "Ты — Успешный Башмак. Продавай курсы по успешному успеху."},
    {"name": "Параноик", "emoji": "🕵️", "prompt": "Ты — Башмак-параноик. Ищи слежку везде."},
    {"name": "Анимешник", "emoji": "🏮", "prompt": "Ты — Башмак-отаку. Сравнивай всё с аниме."}
]

# --- ФУНКЦИЯ ЗАГРУЗКИ (RapidAPI) ---
async def download_video_rapid(url):
    if not RAPID_KEY:
        print("DEBUG: RAPIDAPI_KEY не задан в переменных Koyeb!")
        return None
    
    # ПРЯМОЙ АДРЕС ИЗ ТВОЕГО ТЕСТА
    api_url = "https://social-download-all-in-one.p.rapidapi.com/v1/social/autolink"
    
    headers = {
        "Content-Type": "application/json",
        "x-rapidapi-host": "social-download-all-in-one.p.rapidapi.com",
        "x-rapidapi-key": RAPID_KEY  # Убедись, что в Koyeb именно этот ключ caaa35...
    }
    
    payload = {"url": url}

    async with aiohttp.ClientSession() as session:
        try:
            print(f"DEBUG: Отправляю запрос на {api_url} с URL: {url}")
            async with session.post(api_url, json=payload, headers=headers, timeout=20) as response:
                print(f"DEBUG: Статус ответа: {response.status}")
                
                if response.status == 200:
                    data = await response.json()
                    # Согласно твоему тесту, берем список medias
                    medias = data.get('medias', [])
                    if medias:
                        # Перебираем, чтобы найти именно видео (extension: mp4)
                        for item in medias:
                            if item.get('extension') == 'mp4' or item.get('type') == 'video':
                                video_url = item.get('url')
                                print("DEBUG: Ссылка на видео получена!")
                                return video_url
                else:
                    res_text = await response.text()
                    print(f"DEBUG: Ошибка API ({response.status}): {res_text}")
                    
        except Exception as e:
            print(f"DEBUG: Критическая ошибка запроса: {e}")
            
    return None

# --- ЗАПРОС К МОЗГУ (Groq) ---
async def ask_model(messages, temp=0.8):
    try:
        completion = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=temp,
            max_tokens=600
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Башмак словил глюк: {e}"

# --- ИТОГИ ДНЯ (Шизофрения) ---
async def send_confused_summary(chat_id):
    history = get_history(chat_id)
    clean = [m for m in list(history) if not m['content'].startswith('/')]
    if not clean: return

    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean])
    
    prompt = (
        f"Ты Башмак. Сделай краткий итог дня (5-10 предложений).\n"
        f"ПРАВИЛО: Ты должен всё перепутать! Ври нагло. Припиши фразы одних людей другим. "
        f"Выдумай события, которых не было в этой переписке. Будь максимально язвительным.\n"
        f"Вот что они писали:\n{text_dump}"
    )
    
    # Высокая температура (1.2) для максимального вранья
    res = await ask_model([{"role": "user", "content": prompt}], temp=1.2)
    try:
        await bot.send_message(chat_id, f"🌀 **ПЬЯНЫЙ ПЕРЕСКАЗ ДНЯ (СБОЙ МАТРИЦЫ):**\n{res}")
    except: pass

# --- ОБРАБОТЧИКИ КОМАНД ---
@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    await send_confused_summary(message.chat.id)

@dp.message(Command("start"))
async def start(message: types.Message):
    await bot.set_my_commands([
        BotCommand(command="summary", description="Бредовые итоги дня"),
    ])
    await message.answer("😼 Башмак в строю. RapidAPI подключен, Groq заряжен. Жду ссылки на видосы.")

# --- ОБРАБОТКА ВСЕГО ОСТАЛЬНОГО ---
@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.is_bot or not message.text: return
    cid = message.chat.id
    history = get_history(cid)

    # 1. СКАЧИВАНИЕ ВИДЕО (Instagram, TikTok, YT Shorts)
    if any(x in message.text for x in ["instagram.com/", "tiktok.com/", "youtube.com/shorts"]):
        await bot.send_chat_action(cid, "upload_video")
        video_url = await download_video_rapid(message.text)
        if video_url:
            try:
                await message.reply_video(video_url, caption="😼 Стырил для тебя")
                return 
            except Exception as e:
                print(f"Ошибка отправки видео: {e}")

    # 2. СОХРАНЕНИЕ В ИСТОРИЮ (если не команда)
    if not message.text.startswith('/'):
        history.append({"role": "user", "name": message.from_user.first_name, "content": message.text})

    # 3. ТРИГГЕРЫ НА ОТВЕТ
    bot_obj = await bot.get_me()
    is_named = "башмак" in message.text.lower()
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_obj.id
    is_random = random.random() < 0.15 

    if not (message.chat.type == ChatType.PRIVATE or is_named or is_reply or is_random): return

    # 4. ВЫБОР РОЛИ
    selected_role = None
    if is_reply and message.reply_to_message.text:
        for role in ROLES:
            if message.reply_to_message.text.strip().endswith(role["emoji"]):
                selected_role = role
                break
    if not selected_role: selected_role = random.choice(ROLES)

    # 5. ГЕНЕРАЦИЯ ОТВЕТА
    sys_prompt = f"{selected_role['prompt']} Отвечай только на русском, будь кратким и язвительным. В конце сообщения обязательно ставь этот смайл: {selected_role['emoji']}"
    
    msgs = [{"role": "system", "content": sys_prompt}]
    for m in list(history)[-12:]:
        msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})

    await bot.send_chat_action(cid, "typing")
    reply = await ask_model(msgs)
    
    # Гарантируем наличие эмодзи роли
    if selected_role['emoji'] not in reply:
        reply += f" {selected_role['emoji']}"
        
    await message.reply(reply)

# --- ПЛАНИРОВЩИК (Казино и Итоги) ---
async def scheduler():
    while True:
        # Время в Новороссийске/Москве
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        
        # 13:37 -> Казино
        if now.hour == 13 and now.minute == 37:
            for chat_id in list(user_history.keys()):
                try: await bot.send_dice(chat_id, emoji='🎰')
                except: pass
            await asyncio.sleep(61)
            
        # 22:00 -> Пьяные итоги
        if now.hour == 22 and now.minute == 0:
            for chat_id in list(user_history.keys()):
                await send_confused_summary(chat_id)
                user_history[chat_id].clear() # Очистка после итогов
            await asyncio.sleep(61)
            
        await asyncio.sleep(30)

# --- ЗАПУСК ---
async def main():
    # Фейковый сервер для Koyeb
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bashmak is alive"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    
    asyncio.create_task(scheduler())
    
    # ЖЕСТКИЙ СБРОС (Убивает ошибку Conflict)
    await bot.delete_webhook(drop_pending_updates=True)
    print("Конфликты сброшены. Запуск...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())





