import os, asyncio, datetime, pytz, random
from collections import deque
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.types import BotCommand, FSInputFile
from openai import AsyncOpenAI
from aiohttp import web
import yt_dlp

TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ОБНОВЛЕННЫЙ СПИСОК МОДЕЛЕЙ
MODELS = [
    "google/gemini-2.0-flash-exp:free",
    "deepseek/deepseek-r1:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemini-flash-1.5-8b" # Запасная дешевая
]

user_history = {} 
def get_history(chat_id):
    if chat_id not in user_history: 
        user_history[chat_id] = deque(maxlen=100)
    return user_history[chat_id]

ROLES = [
    {"name": "Стандарт", "emoji": "😼", "prompt": "Ты — Башмак, язвительный кот. Сарказм, краткость."},
    {"name": "Философ", "emoji": "🧘‍♂️", "prompt": "Ты — Башмак-философ. Рассуждай о тщетности бытия."},
    {"name": "Добряк", "emoji": "✨", "prompt": "Ты — подозрительно добрый Башмак. Люби всех, это пугает."},
    {"name": "Тупой", "emoji": "🥴", "prompt": "Ты — Башмак-тормоз. Путай буквы, пиши тупо."},
    {"name": "Инфоцыган", "emoji": "💎", "prompt": "Ты — Успешный Башмак. Продавай курсы и успешный успех."},
    {"name": "Параноик", "emoji": "🕵️", "prompt": "Ты — Башмак-параноик. Ищи слежку ФСБ."},
    {"name": "Анимешник", "emoji": "🏮", "prompt": "Ты — Башмак-отаку. Сравнивай всех с аниме."}
]

# УСИЛЕННЫЙ ЗАГРУЗЧИК
def download_reels(url):
    ydl_opts = {
        'outtmpl': '/tmp/%(id)s.%(ext)s',
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'max_filesize': 48 * 1024 * 1024,
        'quiet': True,
        'no_warnings': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.instagram.com/',
        }
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            clean_url = url.split('?')[0]
            info = ydl.extract_info(clean_url, download=True)
            return ydl.prepare_filename(info)
    except Exception as e:
        print(f"Ошибка загрузки: {e}")
        return None

async def ask_model(messages, temp=0.8):
    last_err = ""
    for model in MODELS:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temp,
                max_tokens=500
            )
            return response.choices[0].message.content
        except Exception as e:
            last_err = str(e)
            print(f"Модель {model} упала: {e}")
            continue
    return f"Кот реально спит. Все модели OpenRouter выдают ошибку: {last_err}"

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    history = get_history(message.chat.id)
    clean = [m for m in list(history) if not m['content'].startswith('/')]
    if not clean: return await message.reply("Пусто.")
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean])
    prompt = f"Ты Башмак. Сделай краткий язвительный итог (без выдумок):\n{text_dump}"
    res = await ask_model([{"role": "user", "content": prompt}])
    await message.answer(f"📝 **ИТОГИ:**\n{res}")

@dp.message(Command("roast"))
async def cmd_roast(message: types.Message):
    history = get_history(message.chat.id)
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in list(history)[-20:]])
    res = await ask_model([{"role": "user", "content": f"Разнеси их:\n{text_dump}"}])
    await message.answer(f"🔥 **РАЗНОС:**\n{res}")

@dp.message(Command("start"))
async def start(message: types.Message):
    await bot.set_my_commands([
        BotCommand(command="summary", description="Итоги"),
        BotCommand(command="roast", description="Прожарка"),
    ])
    await message.answer("😼 Башмак на связи. Починил модели и подкрутил загрузчик.")

@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.is_bot or not message.text: return
    cid = message.chat.id
    history = get_history(cid)

    # 1. ОБРАБОТКА ССЫЛОК
    if "instagram.com/" in message.text and ("/reel" in message.text or "/p/" in message.text):
        await bot.send_chat_action(cid, "upload_video")
        video_path = await asyncio.to_thread(download_reels, message.text)
        if video_path and os.path.exists(video_path):
            try:
                await message.answer_video(FSInputFile(video_path), caption="😼 Башмак притащил")
                os.remove(video_path)
                return 
            except:
                if os.path.exists(video_path): os.remove(video_path)
        else:
            await message.reply("😿 Инстаграм не отдает видео. Похоже, меня забанили за подозрительную активность.")

    # 2. ИСТОРИЯ
    if not message.text.startswith('/'):
        history.append({"role": "user", "name": message.from_user.first_name, "content": message.text})

    # 3. УСЛОВИЯ ОТВЕТА
    bot_info = await bot.get_me()
    is_named = "башмак" in message.text.lower()
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    is_random = random.random() < 0.10 

    if not (message.chat.type == ChatType.PRIVATE or is_named or is_reply or is_random): return

    # 4. ВЫБОР РОЛИ
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
    for m in list(history)[-12:]: 
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
