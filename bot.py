import os, asyncio, datetime, pytz, random
from collections import deque
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.types import BotCommand
from groq import AsyncGroq
import aiohttp
from aiohttp import web

TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = AsyncGroq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Обновленные и более стабильные инстансы
COBALT_INSTANCES = [
    "https://cobalt.perennialte.ch/api/json",
    "https://api.cobalt.tools/api/json",
    "https://co.wuk.sh/api/json"
]

user_history = {} 
def get_history(chat_id):
    if chat_id not in user_history: 
        user_history[chat_id] = deque(maxlen=100)
    return user_history[chat_id]

ROLES = [
    {"name": "Стандарт", "emoji": "😼", "prompt": "Ты — Башмак, язвительный кот. Сарказм, краткость."},
    {"name": "Тупой", "emoji": "🥴", "prompt": "Ты — Башмак-тормоз. Путай буквы, пиши тупо."},
    {"name": "Параноик", "emoji": "🕵️", "prompt": "Ты — Башмак-параноик. Ищи слежку везде."}
]

async def download_via_cobalt(url):
    # Упрощенный payload, чтобы избежать ошибки 400
    payload = {
        "url": url,
        "videoQuality": "720"
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        for api_url in COBALT_INSTANCES:
            try:
                async with session.post(api_url, json=payload, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        # Проверяем все возможные поля с ссылкой
                        return data.get('url') or data.get('text')
            except:
                continue
    return None

async def ask_model(messages, temp=0.8):
    try:
        completion = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=temp
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Мозг кота завис: {e}"

async def send_confused_summary(chat_id):
    history = get_history(chat_id)
    clean = [m for m in list(history) if not m['content'].startswith('/')]
    if not clean: return

    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean])
    prompt = f"Ты Башмак. Сделай краткий (5-10 предложений) итог дня, специально перепутав кто что говорил и исказив факты до абсурда:\n{text_dump}"
    
    res = await ask_model([{"role": "user", "content": prompt}], temp=1.0)
    try: await bot.send_message(chat_id, f"🌀 **ПЬЯНЫЕ ИТОГИ ДНЯ:**\n{res}")
    except: pass

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    await send_confused_summary(message.chat.id)

@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.is_bot or not message.text: return
    cid = message.chat.id
    history = get_history(cid)

    # Работа с видео
    if any(x in message.text for x in ["instagram.com/", "tiktok.com/", "youtube.com/shorts"]):
        video_url = await download_via_cobalt(message.text)
        if video_url:
            try:
                await message.reply_video(video_url, caption="😼 Башмак притащил")
                return
            except: pass

    # Запись истории
    if not message.text.startswith('/'):
        history.append({"role": "user", "name": message.from_user.first_name, "content": message.text})

    # Шанс ответа
    is_named = "башмак" in message.text.lower()
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == (await bot.get_me()).id
    if not (message.chat.type == ChatType.PRIVATE or is_named or is_reply or random.random() < 0.15): return

    role = random.choice(ROLES)
    msgs = [{"role": "system", "content": f"{role['prompt']} Пиши на русском, в конце {role['emoji']}"}]
    for m in list(history)[-10:]:
        msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})

    res = await ask_model(msgs)
    await message.reply(res)

async def scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        # 13:37 Казино
        if now.hour == 13 and now.minute == 37:
            for cid in list(user_history.keys()):
                try: await bot.send_dice(cid, emoji='🎰')
                except: pass
            await asyncio.sleep(61)
        # 22:00 Итоги
        if now.hour == 22 and now.minute == 0:
            for cid in list(user_history.keys()):
                await send_confused_summary(cid)
                user_history[cid].clear()
            await asyncio.sleep(61)
        await asyncio.sleep(30)

async def main():
    # Веб-сервер для Koyeb
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bashmak OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    
    asyncio.create_task(scheduler())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
