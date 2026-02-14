import os, asyncio, datetime, pytz, random
from collections import deque
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.types import BotCommand, FSInputFile
from groq import AsyncGroq  # Теперь используем Groq
from aiohttp import web
import yt_dlp

# --- КОНФИГ ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = AsyncGroq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Модели Groq (от самой умной к самой быстрой)
MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama-3-70b-8192",
    "llama3-8b-8192"
]

user_history = {} 
def get_history(chat_id):
    if chat_id not in user_history: 
        user_history[chat_id] = deque(maxlen=100)
    return user_history[chat_id]

ROLES = [
    {"name": "Стандарт", "emoji": "😼", "prompt": "Ты — Башмак, язвительный кот Данила. Сарказм, краткость, база."},
    {"name": "Философ", "emoji": "🧘‍♂️", "prompt": "Ты — Башмак-философ. Рассуждай о тщетности бытия."},
    {"name": "Добряк", "emoji": "✨", "prompt": "Ты — подозрительно добрый Башмак. Люби всех, это пугает."},
    {"name": "Тупой", "emoji": "🥴", "prompt": "Ты — Башмак-тормоз. Путай буквы, пиши тупо."},
    {"name": "Инфоцыган", "emoji": "💎", "prompt": "Ты — Успешный Башмак. Продавай курсы по успешному успеху."},
    {"name": "Параноик", "emoji": "🕵️", "prompt": "Ты — Башмак-параноик. Ищи слежку везде."},
    {"name": "Анимешник", "emoji": "🏮", "prompt": "Ты — Башмак-отаку. Сравнивай всё с аниме."}
]

def download_reels(url):
    ydl_opts = {
        'outtmpl': '/tmp/%(id)s.%(ext)s',
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'max_filesize': 48 * 1024 * 1024,
        'quiet': True,
        'no_warnings': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Referer': 'https://www.instagram.com/',
        }
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            clean_url = url.split('?')[0]
            info = ydl.extract_info(clean_url, download=True)
            return ydl.prepare_filename(info)
    except: return None

async def ask_model(messages):
    last_err = ""
    for model in MODELS:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.8,
                max_tokens=500
            )
            return response.choices[0].message.content
        except Exception as e:
            last_err = str(e)
            print(f"Groq {model} error: {e}")
            continue
    return f"Башмак в коме. Даже Groq сдох: {last_err}"

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    history = get_history(message.chat.id)
    clean = [m for m in list(history) if not m['content'].startswith('/')]
    if not clean: return await message.reply("Пусто.")
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean])
    prompt = f"Ты Башмак. Сделай краткий язвительный итог дня (без бреда):\n{text_dump}"
    res = await ask_model([{"role": "user", "content": prompt}])
    await message.answer(f"📝 **ИТОГИ:**\n{res}")

@dp.message(Command("roast"))
async def cmd_roast(message: types.Message):
    history = get_history(message.chat.id)
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in list(history)[-20:]])
    res = await ask_model([{"role": "user", "content": f"Разнеси их за тупость:\n{text_dump}"}])
    await message.answer(f"🔥 **РАЗНОС:**\n{res}")

@dp.message(Command("start"))
async def start(message: types.Message):
    await bot.set_my_commands([
        BotCommand(command="summary", description="Итоги"),
        BotCommand(command="roast", description="Прожарка"),
    ])
    await message.answer("😼 Башмак переехал на Groq. Теперь летаю.")

@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.is_bot or not message.text: return
    cid = message.chat.id
    history = get_history(cid)

    # 1. ССЫЛКИ
    if "instagram.com/" in message.text and ("/reel" in message.text or "/p/" in message.text):
        await bot.send_chat_action(cid, "upload_video")
        video_path = await asyncio.to_thread(download_reels, message.text)
        if video_path and os.path.exists(video_path):
            try:
                await message.answer_video(FSInputFile(video_path), caption="😼 Доставил")
                os.remove(video_path)
                return 
            except:
                if os.path.exists(video_path): os.remove(video_path)
        else:
            await message.reply("😿 Инстаграм блокирует меня. Попробуй позже.")

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
    for m in list(history)[-15:]: 
        msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})

    await bot.send_chat_action(cid, "typing")
    reply = await ask_model(msgs)
    if selected_role['emoji'] not in reply: reply += f" {selected_role['emoji']}"
    await message.reply(reply)

async def scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        if now.hour == 22 and now.minute == 0:
            for chat_id in list(user_history.keys()):
                try:
                    history = get_history(chat_id)
                    clean = [m for m in list(history) if not m['content'].startswith('/')]
                    if clean:
                        text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean])
                        prompt = f"Ты Башмак. Сделай язвительный итог дня:\n{text_dump}"
                        res = await ask_model([{"role": "user", "content": prompt}])
                        await bot.send_message(chat_id, f"📝 **ИТОГИ ДНЯ:**\n{res}")
                        user_history[chat_id].clear()
                except: pass
            await asyncio.sleep(61)
        await asyncio.sleep(30)

async def main():
    app = web.Application(); app.router.add_get("/", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    asyncio.create_task(scheduler())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__": asyncio.run(main())
