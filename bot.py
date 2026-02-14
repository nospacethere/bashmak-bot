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

client = AsyncGroq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# СПИСОК СЕРВЕРОВ COBALT (Для надежности)
COBALT_INSTANCES = [
    "https://api.cobalt.tools/api/json",
    "https://co.wuk.sh/api/json",
    "https://cobalt.xy24.eu/api/json",
    "https://api.server.cobalt.tools/api/json"
]

# ПАМЯТЬ
user_history = {} 
def get_history(chat_id):
    if chat_id not in user_history: 
        user_history[chat_id] = deque(maxlen=100)
    return user_history[chat_id]

# ЛИЧНОСТИ
ROLES = [
    {"name": "Стандарт", "emoji": "😼", "prompt": "Ты — Башмак, язвительный кот. Сарказм, краткость."},
    {"name": "Философ", "emoji": "🧘‍♂️", "prompt": "Ты — Башмак-философ. Рассуждай о тщетности бытия."},
    {"name": "Добряк", "emoji": "✨", "prompt": "Ты — подозрительно добрый Башмак. Люби всех, это пугает."},
    {"name": "Тупой", "emoji": "🥴", "prompt": "Ты — Башмак-тормоз. Путай буквы, пиши тупо."},
    {"name": "Инфоцыган", "emoji": "💎", "prompt": "Ты — Успешный Башмак. Продавай курсы и успешный успех."},
    {"name": "Параноик", "emoji": "🕵️", "prompt": "Ты — Башмак-параноик. Ищи слежку везде."},
    {"name": "Анимешник", "emoji": "🏮", "prompt": "Ты — Башмак-отаку. Сравнивай всё с аниме."}
]

# --- ФУНКЦИЯ ЗАГРУЗКИ ЧЕРЕЗ API ---
async def download_via_cobalt(url):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    payload = {
        "url": url,
        "vCodec": "h264",
        "vQuality": "720",
        "aFormat": "mp3",
        "filenamePattern": "classic"
    }
    
    async with aiohttp.ClientSession() as session:
        for api_url in COBALT_INSTANCES:
            try:
                async with session.post(api_url, json=payload, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('status') == 'error':
                            print(f"Cobalt error on {api_url}: {data.get('text')}")
                            continue
                            
                        # Если API вернул прямую ссылку
                        if data.get('url'):
                            return data['url']
                        # Если API вернул picker (иногда бывает)
                        if data.get('picker'):
                            for item in data['picker']:
                                if item.get('type') == 'video':
                                    return item['url']
            except Exception as e:
                print(f"Failed {api_url}: {e}")
                continue
    return None

# --- ЗАПРОС К GROQ ---
async def ask_model(messages, temp=0.8):
    try:
        completion = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=temp,
            max_tokens=800
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Groq поперхнулся: {e}"

# --- КОМАНДЫ ---
@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    await send_confused_summary(message.chat.id)

# Специальная функция для "пьяного" итога
async def send_confused_summary(chat_id):
    history = get_history(chat_id)
    clean = [m for m in list(history) if not m['content'].startswith('/')]
    if not clean: 
        try: await bot.send_message(chat_id, "День прошел в тишине, даже соврать не о чем.")
        except: pass
        return

    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean])
    
    # Тот самый промпт для путаницы
    prompt = (
        f"Ты Башмак. Твоя задача — подвести итоги дня, НО ты должен ВСЁ ПЕРЕПУТАТЬ.\n"
        f"Вот переписка:\n{text_dump}\n\n"
        f"Задача:\n"
        f"1. Припиши фразы одних людей другим (нагло ври).\n"
        f"2. Искази смысл событий до абсурда.\n"
        f"3. Добавь пару фактов, которых вообще не было.\n"
        f"4. Стиль: язвительный, немного 'сбой в матрице'.\n"
        f"5. Объем: 5-10 предложений."
    )
    
    res = await ask_model([{"role": "user", "content": prompt}], temp=1.0) # Температура 1.0 для безумия
    try: await bot.send_message(chat_id, f"🌀 **СБОЙ ИТОГОВ ДНЯ:**\n{res}")
    except: pass

@dp.message(Command("roast"))
async def cmd_roast(message: types.Message):
    history = get_history(message.chat.id)
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in list(history)[-20:]])
    res = await ask_model([{"role": "user", "content": f"Жестко прожарь этих людей:\n{text_dump}"}])
    await message.answer(f"🔥 **РАЗНОС:**\n{res}")

@dp.message(Command("start"))
async def start(message: types.Message):
    await bot.set_my_commands([
        BotCommand(command="summary", description="Безумные итоги"),
        BotCommand(command="roast", description="Прожарка"),
    ])
    await message.answer("😼 Башмак V4. API для видео, Groq для мозга и кубик для азарта.")

# --- ЧАТ ---
@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.is_bot or not message.text: return
    cid = message.chat.id
    history = get_history(cid)

    # 1. ЛОВИМ ВИДЕО (Instagram/TikTok/YouTube Shorts)
    # Cobalt жрет почти всё, не только инсту
    if any(x in message.text for x in ["instagram.com/", "tiktok.com/", "youtube.com/shorts"]):
        await bot.send_chat_action(cid, "upload_video")
        video_url = await download_via_cobalt(message.text)
        
        if video_url:
            try:
                # Отправляем URL напрямую - телеграм сам скачает и покажет как видео
                await message.reply_video(video_url, caption="😼 Стырено через API")
                return # Не комментируем ссылками
            except Exception as e:
                print(f"Send failed: {e}")
        else:
            # Если API не справился, можно просто промолчать или ругнуться
            pass

    # 2. ИСТОРИЯ
    if not message.text.startswith('/'):
        history.append({"role": "user", "name": message.from_user.first_name, "content": message.text})

    # 3. ТРИГГЕРЫ
    bot_info = await bot.get_me()
    is_named = "башмак" in message.text.lower()
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    is_random = random.random() < 0.10 

    if not (message.chat.type == ChatType.PRIVATE or is_named or is_reply or is_random): return

    # 4. РОЛЬ
    selected_role = None
    if is_reply and message.reply_to_message.text:
        for role in ROLES:
            if message.reply_to_message.text.strip().endswith(role["emoji"]):
                selected_role = role
                break
    if not selected_role: selected_role = random.choice(ROLES)

    # 5. ОТВЕТ
    sys_prompt = f"{selected_role['prompt']} Отвечай на русском, кратко, в конце смайл: {selected_role['emoji']}"
    msgs = [{"role": "system", "content": sys_prompt}]
    for m in list(history)[-12:]: 
        msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})

    await bot.send_chat_action(cid, "typing")
    reply = await ask_model(msgs)
    if selected_role['emoji'] not in reply: reply += f" {selected_role['emoji']}"
    await message.reply(reply)

# --- ПЛАНИРОВЩИК ---
async def scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        
        # 13:37 -> КУБИК 🎰
        if now.hour == 13 and now.minute == 37:
            for chat_id in list(user_history.keys()):
                try: await bot.send_dice(chat_id, emoji='🎰')
                except: pass
            await asyncio.sleep(61)
            
        # 22:00 -> ПУТАНЫЕ ИТОГИ 📝
        if now.hour == 22 and now.minute == 0:
            for chat_id in list(user_history.keys()):
                await send_confused_summary(chat_id)
                # Очищаем историю после итогов, чтобы завтра начать с чистого листа
                user_history[chat_id].clear()
            await asyncio.sleep(61)
            
        await asyncio.sleep(30)

async def main():
    # Фейковый веб-сервер для Koyeb (чтобы не падал health check)
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bashmak Alive"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    
    # Запуск бота
    asyncio.create_task(scheduler())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__": asyncio.run(main())
