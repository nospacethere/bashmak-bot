import os, asyncio, datetime, pytz, random
from collections import deque
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.types import BotCommand, BufferedInputFile
from groq import AsyncGroq
import aiohttp
from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient

# --- КОНФИГ ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
RAPID_KEY = os.getenv("RAPIDAPI_KEY")
MONGO_URL = os.getenv("MONGO_URL")

# Инициализация
client = AsyncGroq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Подключение к БД
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client['bashmak_db']
scores_col = db['scores']

user_history = {} 

def get_history(chat_id):
    if chat_id not in user_history: 
        user_history[chat_id] = deque(maxlen=100)
    return user_history[chat_id]

ROLES = [
   ROLES = [

    {"name": "Стандарт", "emoji": "😼", "prompt": "Ты — Башмак, язвительный кот Данила. Сарказм, краткость, база."},

    {"name": "Философ", "emoji": "🧘‍♂️", "prompt": "Ты — Башмак-философ. Рассуждай о тщетности бытия."},

    {"name": "Добряк", "emoji": "✨", "prompt": "Ты — подозрительно добрый Башмак. Люби всех, это пугает."},

    {"name": "Тупой", "emoji": "🥴", "prompt": "Ты — Башмак-тормоз. Путай буквы, пиши тупо."},

    {"name": "Инфоцыган", "emoji": "💎", "prompt": "Ты — Успешный Башмак. Продавай курсы по успешному успеху."},

    {"name": "Параноик", "emoji": "🕵️", "prompt": "Ты — Башмак-параноик. Ищи слежку везде."},

    {"name": "Анимешник", "emoji": "🏮", "prompt": "Ты — Башмак-отаку. Сравнивай всё с аниме."}

]

# --- ПОМОЩНИКИ ---
async def download_video_rapid(url):
    if not RAPID_KEY: return None
    api_url = "https://social-download-all-in-one.p.rapidapi.com/v1/social/autolink"
    headers = {"Content-Type": "application/json", "x-rapidapi-host": "social-download-all-in-one.p.rapidapi.com", "x-rapidapi-key": RAPID_KEY}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(api_url, json={"url": url}, headers=headers, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    medias = data.get('medias', [])
                    if medias:
                        for m in medias:
                            if m.get('extension') == 'mp4': return m.get('url')
                        return medias[0].get('url')
        except: pass
    return None

async def ask_model(messages, temp=0.8):
    try:
        completion = await client.chat.completions.create(model="llama-3.3-70b-versatile", messages=messages, temperature=temp)
        return completion.choices[0].message.content
    except Exception as e: return f"Башмак сломался: {e}"

# --- ГЕМБЛИНГ ФУНКЦИИ ---
async def get_leaderboard_text():
    cursor = scores_col.find().sort("balance", -1).limit(10)
    players = await cursor.to_list(length=10)
    if not players: return "Пока пусто..."
    
    text = "🏆 **ТОП МИГРАНТОВ:**\n"
    for i, p in enumerate(players):
        medal = "🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else f"{i+1}."
        text += f"{medal} {p['name']}: {p['balance']} очков\n"
    return text

# --- ОБРАБОТЧИКИ ---

# 1. КАЗИНО (🎰)
@dp.message(lambda m: m.dice and m.dice.emoji == '🎰')
async def handle_dice(message: types.Message):
    user_id = message.from_user.id
    name = message.from_user.first_name
    
    # Проверяем новичка
    user_doc = await scores_col.find_one({"user_id": user_id})
    is_new = False
    
    if not user_doc:
        is_new = True
        # Старт: 10 очков
        await scores_col.insert_one({"user_id": user_id, "name": name, "balance": 10})
        current_balance = 10
    else:
        current_balance = user_doc['balance']

    # Математика слотов
    v = message.dice.value - 1
    reels = [v % 4, (v // 4) % 4, v // 16]
    
    if message.dice.value == 64: 
        change, res_text = 50, "ДЖЕКПОТ (777)"
    elif reels[0] == reels[1] == reels[2]: 
        change, res_text = 15, "ТРИ В РЯД"
    elif reels[0] == reels[1] or reels[1] == reels[2]: 
        change, res_text = 1, "ДВЕ В РЯД"
    else: 
        change, res_text = -1, "ПРОИГРЫШ"

    # Обновляем базу
    new_balance = current_balance + change
    await scores_col.update_one({"user_id": user_id}, {"$set": {"balance": new_balance, "name": name}})
    
    # Генерируем реакцию
    prompt = f"Ты кот Башмак. {name} выбил {res_text} в казино. Его баланс стал {new_balance}. Напиши едкий комментарий."
    reaction = await ask_model([{"role": "user", "content": prompt}])
    
    await asyncio.sleep(4) # Ждем пока прокрутится анимация
    await message.reply(reaction)

    # Если новичок — кидаем правила
    if is_new:
        rules = (
            "📜 **ПРАВИЛА СМЕРТЕЛЬНОЙ МИГРАЦИИ:**\n"
            "Всем новичкам: 10 очков на старте.\n\n"
            "🎰 **777 (Джекпот):** +50 очков\n"
            "🍒 **3 в ряд:** +15 очков\n"
            "🍋 **2 в ряд:** +1 очко\n"
            "💩 **Мимо:** -1 очко\n\n"
            "Кто в минусе — тот лох. Проверить топ: /top"
        )
        await message.answer(rules)

# 2. КОМАНДА /TOP
@dp.message(Command("top"))
async def cmd_top(message: types.Message):
    text = await get_leaderboard_text()
    await message.answer(text)

# 3. ИТОГИ ДНЯ (Команда /summary или по таймеру)
async def send_confused_summary(chat_id):
    history = get_history(chat_id)
    clean = [m for m in list(history) if not m['content'].startswith('/')]
    
    top_text = await get_leaderboard_text()
    
    if not clean:
        # Если чат молчал, просто кидаем таблицу
        await bot.send_message(chat_id, f"📅 День прошел тихо.\n\n{top_text}")
        return

    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean])
    prompt = (f"Ты Башмак. Сделай язвительный итог дня. Ври, путай факты.\nПереписка:\n{text_dump}\n\n"
              f"Вот таблица лидеров казино:\n{top_text}\n"
              "Прокомментируй лидера и лузеров.")
    
    res = await ask_model([{"role": "user", "content": prompt}], temp=1.2)
    try: await bot.send_message(chat_id, f"🌀 **ИТОГИ ДНЯ & ГЕМБЛИНГ:**\n{res}")
    except: pass

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    await send_confused_summary(message.chat.id)

# 4. ОБЩИЙ ОБРАБОТЧИК (ВИДЕО + ЧАТ)
@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.is_bot or not message.text: return
    cid = message.chat.id
    history = get_history(cid)

    # Видео
    if any(x in message.text for x in ["instagram.com/", "tiktok.com/", "youtube.com/shorts", "youtu.be/"]):
        await bot.send_chat_action(cid, "upload_video")
        v_url = await download_video_rapid(message.text)
        if v_url:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(v_url, timeout=30) as r:
                        if r.status == 200:
                            f = BufferedInputFile(await r.read(), filename="video.mp4")
                            await message.reply_video(f, caption="😼 Стырил для тебя")
                            return
            except: await message.reply("😿 Не шмогла я, не шмогла...")

    # Сохраняем историю
    if not message.text.startswith('/'):
        history.append({"role": "user", "name": message.from_user.first_name, "content": message.text})
        # На всякий случай обновляем имя в базе, если человек играет
        await scores_col.update_one({"user_id": message.from_user.id}, {"$set": {"name": message.from_user.first_name}}, upsert=False)

    # Ответ Башмака
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

    msgs = [{"role": "system", "content": f"{selected_role['prompt']} Отвечай кратко. В конце: {selected_role['emoji']}"}]
    for m in list(history)[-12:]: msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})

    await bot.send_chat_action(cid, "typing")
    reply = await ask_model(msgs)
    if selected_role['emoji'] not in reply: reply += f" {selected_role['emoji']}"
    await message.reply(reply)

# --- ПЛАНИРОВЩИК ---
async def scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        # 13:37 - Казино тайм
        if now.hour == 13 and now.minute == 37:
            for cid in list(user_history.keys()):
                try: await bot.send_dice(cid, emoji='🎰')
                except: pass
            await asyncio.sleep(61)
        # 22:00 - Итоги + Таблица
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

