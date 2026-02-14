import os, asyncio, datetime, pytz, random
from collections import deque
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.types import BotCommand, BufferedInputFile
from groq import AsyncGroq
import aiohttp
from aiohttp import web

TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
RAPID_KEY = os.getenv("RAPIDAPI_KEY")

client = AsyncGroq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

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

# --- ФУНКЦИЯ ЗАГРУЗКИ (RapidAPI) ---
async def download_video_rapid(url):
    if not RAPID_KEY: return None
    api_url = "https://social-download-all-in-one.p.rapidapi.com/v1/social/autolink"
    headers = {
        "Content-Type": "application/json",
        "x-rapidapi-host": "social-download-all-in-one.p.rapidapi.com",
        "x-rapidapi-key": RAPID_KEY
    }
    payload = {"url": url}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(api_url, json=payload, headers=headers, timeout=20) as response:
                if response.status == 200:
                    data = await response.json()
                    medias = data.get('medias', [])
                    if medias:
                        # Ищем лучший MP4
                        for item in medias:
                            if item.get('extension') == 'mp4':
                                return item.get('url')
                        return medias[0].get('url')
        except Exception as e:
            print(f"DEBUG: Ошибка API: {e}")
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

async def send_confused_summary(chat_id):
    history = get_history(chat_id)
    clean = [m for m in list(history) if not m['content'].startswith('/')]
    if not clean: return
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean])
    prompt = f"Ты Башмак. Сделай язвительный итог дня (5-10 предложений). ПЕРЕПУТАЙ ВСЁ, ври нагло:\n{text_dump}"
    res = await ask_model([{"role": "user", "content": prompt}], temp=1.2)
    try: await bot.send_message(chat_id, f"🌀 **ПЬЯНЫЙ ПЕРЕСКАЗ ДНЯ:**\n{res}")
    except: pass

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    await send_confused_summary(message.chat.id)

@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.is_bot or not message.text: return
    cid = message.chat.id
    history = get_history(cid)

    # 1. ЗАГРУЗКА ВИДЕО
    if any(x in message.text for x in ["instagram.com/", "tiktok.com/", "youtube.com/shorts", "youtu.be/"]):
        await bot.send_chat_action(cid, "upload_video")
        video_url = await download_video_rapid(message.text)
        
        if video_url:
            try:
                # КАЧАЕМ ВИДЕО В ПАМЯТЬ ПЕРЕД ОТПРАВКОЙ (Лечит ошибку failed to get HTTP URL content)
                async with aiohttp.ClientSession() as session:
                    async with session.get(video_url, timeout=30) as resp:
                        if resp.status == 200:
                            video_bytes = await resp.read()
                            video_file = BufferedInputFile(video_bytes, filename="bashmak_video.mp4")
                            await message.reply_video(video_file, caption="😼 Стырил для тебя")
                            return
            except Exception as e:
                print(f"DEBUG: Ошибка отправки: {e}")
                await message.reply("😿 Видео слишком жирное или ссылка протухла.")

    if not message.text.startswith('/'):
        history.append({"role": "user", "name": message.from_user.first_name, "content": message.text})

    bot_obj = await bot.get_me()
    is_named = "башмак" in message.text.lower()
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_obj.id
    if not (message.chat.type == ChatType.PRIVATE or is_named or is_reply or random.random() < 0.15): return

    selected_role = None
    if is_reply and message.reply_to_message.text:
        for role in ROLES:
            if message.reply_to_message.text.strip().endswith(role["emoji"]):
                selected_role = role
                break
    if not selected_role: selected_role = random.choice(ROLES)

    sys_prompt = f"{selected_role['prompt']} Отвечай только на русском, кратко. В конце: {selected_role['emoji']}"
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
        if now.hour == 13 and now.minute == 37:
            for cid in list(user_history.keys()):
                try: await bot.send_dice(cid, emoji='🎰')
                except: pass
            await asyncio.sleep(61)
        if now.hour == 22 and now.minute == 0:
            for cid in list(user_history.keys()):
                await send_confused_summary(cid)
                user_history[cid].clear()
            await asyncio.sleep(61)
        await asyncio.sleep(30)

async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bashmak is alive"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    asyncio.create_task(scheduler())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
