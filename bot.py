import os, asyncio, datetime, pytz, random
from collections import deque
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.types import BotCommand, FSInputFile
from openai import AsyncOpenAI
from aiohttp import web
import yt_dlp

# --- КОНФИГ ---
TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Модель R1 (как на твоем скрине)
MODEL_NAME = "google/gemini-2.0-flash-exp:free" 

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
    {"name": "Параноик", "emoji": "🕵️", "prompt": "Ты — Башмак-параноик. Ищи слежку ФСБ."},
    {"name": "Анимешник", "emoji": "🏮", "prompt": "Ты — Башмак-отаку. Сравнивай всех с аниме (Наруто, Берсерк)."}
]

# --- СИНХРОННАЯ ФУНКЦИЯ (для yt-dlp) ---
def download_reels(url):
    ydl_opts = {
        'outtmpl': '/tmp/%(id)s.%(ext)s',
        'format': 'mp4',
        'max_filesize': 45 * 1024 * 1024,
        'quiet': True,
        'no_warnings': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            clean_url = url.split('?')[0]
            info = ydl.extract_info(clean_url, download=True)
            return ydl.prepare_filename(info)
    except Exception as e:
        print(f"DL Error: {e}")
        return None

async def ask_model(messages, temp=0.8):
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=temp,
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Кот спит. (Ошибка: {e})"

# --- КОМАНДЫ ---
@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    history = get_history(message.chat.id)
    clean = [m for m in list(history) if not m['content'].startswith('/')]
    if not clean: return await message.reply("Стебать нечего, все молчали.")
    
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean])
    prompt = (
        f"Ты Башмак. Сделай краткий итог переписки:\n{text_dump}\n"
        "СТРОГО: Не выдумывай бред про 1987 год, Путина или носки. Только факты из текста в язвительной форме. "
        "Максимум 5 предложений."
    )
    res = await ask_model([{"role": "user", "content": prompt}])
    await message.answer(f"📝 **ИТОГИ:**\n{res}")

@dp.message(Command("roast"))
async def cmd_roast(message: types.Message):
    history = get_history(message.chat.id)
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in list(history)[-20:]])
    res = await ask_model([{"role": "user", "content": f"Разнеси этих людей за их тупость:\n{text_dump}"}])
    await message.answer(f"🔥 **РАЗНОС:**\n{res}")

@dp.message(Command("start"))
async def start(message: types.Message):
    await bot.set_my_commands([
        BotCommand(command="summary", description="Итоги"),
        BotCommand(command="roast", description="Прожарка"),
    ])
    await message.answer("😼 Башмак готов. Кидай рилсы или зови меня.")

# --- ГЛАВНЫЙ ОБРАБОТЧИК ---
@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.is_bot or not message.text: return
    cid = message.chat.id
    history = get_history(cid)

    # 1. ЛОВИМ ССЫЛКИ (Reels/Posts)
    if "instagram.com/" in message.text and ("/reel" in message.text or "/p/" in message.text):
        await bot.send_chat_action(cid, "upload_video")
        # Теперь правильно вызываем синхронную функцию в потоке
        video_path = await asyncio.to_thread(download_reels, message.text)
        
        if video_path and os.path.exists(video_path):
            try:
                await message.answer_video(FSInputFile(video_path), caption="😼 Башмак притащил")
                os.remove(video_path)
                return # Чтобы бот не отвечал текстом на ссылку
            except Exception as e:
                if os.path.exists(video_path): os.remove(video_path)
                print(f"Send error: {e}")

    # 2. ЗАПИСЬ В ИСТОРИЮ
    if not message.text.startswith('/'):
        history.append({"role": "user", "name": message.from_user.first_name, "content": message.text})

    # 3. УСЛОВИЯ ОТВЕТА
    bot_info = await bot.get_me()
    is_named = "башмак" in message.text.lower()
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    is_random = random.random() < 0.10 # Твои 10%

    if not (message.chat.type == ChatType.PRIVATE or is_named or is_reply or is_random): return

    # 4. ВЫБОР ЛИЧНОСТИ (по Reply или рандом)
    selected_role = None
    if is_reply and message.reply_to_message.text:
        for role in ROLES:
            if message.reply_to_message.text.strip().endswith(role["emoji"]):
                selected_role = role
                break
    
    if not selected_role: selected_role = random.choice(ROLES)

    # 5. ГЕНЕРАЦИЯ
    sys_prompt = f"{selected_role['prompt']} Отвечай кратко, без скобок, в конце смайл: {selected_role['emoji']}"
    msgs = [{"role": "system", "content": sys_prompt}]
    for m in list(history)[-10:]: 
        msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})

    await bot.send_chat_action(cid, "typing")
    reply = await ask_model(msgs)
    if selected_role['emoji'] not in reply: reply += f" {selected_role['emoji']}"
    await message.reply(reply)

# --- ЗАПУСК ---
async def scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        if now.hour == 22 and now.minute == 0:
            for chat_id in list(user_history.keys()):
                # Вызов саммари
                pass 
        await asyncio.sleep(60)

async def main():
    app = web.Application(); app.router.add_get("/", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    asyncio.create_task(scheduler())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__": asyncio.run(main())

