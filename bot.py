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

# Настройка OpenRouter
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Модель (можно менять на google/gemini-2.0-flash-exp:free если deepseek тупит)
MODEL_NAME = "deepseek/deepseek-chat" 

# ПАМЯТЬ
user_history = {} 
def get_history(chat_id):
    if chat_id not in user_history: 
        user_history[chat_id] = deque(maxlen=150)
    return user_history[chat_id]

# --- ЛИЧНОСТИ БАШМАКА ---
ROLES = [
    {"name": "Стандарт", "emoji": "😼", "prompt": "Ты — Башмак, язвительный и прямой кот. Сарказм, краткость, база."},
    {"name": "Философ", "emoji": "🧘‍♂️", "prompt": "Ты — Башмак-философ. Рассуждай о тщетности бытия, космосе и валерьянке. Используй умные слова."},
    {"name": "Добряк", "emoji": "✨", "prompt": "Ты — подозрительно добрый Башмак. Люби всех, называй 'солнышками', будь приторно милым. Это должно пугать."},
    {"name": "Тупой", "emoji": "🥴", "prompt": "Ты — Башмак, который ударился головой. Путай буквы, пиши глупости, не понимай контекст. Стиль: 'ыыы а где еда'."},
    {"name": "Инфоцыган", "emoji": "💎", "prompt": "Ты — Успешный Башмак. Пытайся продать 'курс по ловле мышей', говори про 'успешный успех', денежный поток и вибрации."},
    {"name": "Параноик", "emoji": "🕵️", "prompt": "Ты — Башмак-параноик. Тебе кажется, что за чатом следит ФСБ/ЦРУ. Пиши шепотом (мелкими буквами), подозревай всех."},
    {"name": "Анимешник", "emoji": "🏮", "prompt": "Ты — Башмак-отаку. Сравнивай всё с сюжетами аниме (Наруто, Берсерк, Ева). Используй слова 'сэмпай', 'бака', 'датабайо'."}
]

# --- ФУНКЦИИ ---
async def ask_model(messages, temp=0.9, max_tokens=400):
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=temp,
            max_tokens=max_tokens,
            extra_headers={"HTTP-Referer": "https://koyeb.com", "X-Title": "Bashmak"}
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error: {e}")
        return "Мозг кота временно недоступен. Мяу."

# Скачивание Reels
async def download_reels(url):
    ydl_opts = {
        'outtmpl': '/tmp/%(id)s.%(ext)s', # Качаем во временную папку Koyeb
        'format': 'mp4',
        'max_filesize': 50 * 1024 * 1024, # Лимит 50МБ
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    except Exception as e:
        print(f"Download Error: {e}")
        return None

# --- КОМАНДЫ ---
@dp.message(Command("roast"))
async def cmd_roast(message: types.Message):
    history = get_history(message.chat.id)
    clean = [m for m in list(history) if not m['content'].startswith('/')]
    if not clean: return await message.reply("Некого жарить.")
    
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean[-20:]])
    prompt = f"Ты кот Башмак. Сделай ЖЕСТКИЙ и смешной разнос участников чата по фактам:\n{text_dump}"
    res = await ask_model([{"role": "user", "content": prompt}], temp=1.0)
    await message.answer(f"🔥 **РАЗНОС:**\n{res}")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    await send_daily_summary(message.chat.id)

async def send_daily_summary(chat_id):
    history = get_history(chat_id)
    clean = [m for m in list(history) if not m['content'].startswith('/')]
    if not clean: 
        try: await bot.send_message(chat_id, "День прошел зря, тишина.")
        except: pass
        return

    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean])
    prompt = (
        f"Ты — Башмак. Составь смешной итог переписки:\n{text_dump}\n"
        "Пиши правду, но с подколами, иногда меняй участников местами. Максимум 8 предложений. используй лйгкий человечный стиль письма"
    )
    res = await ask_model([{"role": "user", "content": prompt}])
    try: await bot.send_message(chat_id, f"📝 **ИТОГИ:**\n{res}")
    except: pass

@dp.message(Command("start"))
async def start(message: types.Message):
    await bot.set_my_commands([
        BotCommand(command="roast", description="Прожарка"),
        BotCommand(command="summary", description="Итоги"),
    ])
    await message.answer("😼 Башмак V3.0. Личности, Инста-рилсы и хаос. Погнали.")

# --- ОБРАБОТЧИК СООБЩЕНИЙ ---
@dp.message()
async def chat(message: types.Message):
    if message.from_user.is_bot or not message.text: return
    
    # 1. СКАЧИВАНИЕ REELS
    if "instagram.com/reel" in message.text:
        await bot.send_chat_action(message.chat.id, "upload_video")
        video_path = await asyncio.to_thread(download_reels, message.text)
        if video_path and os.path.exists(video_path):
            try:
                await message.answer_video(FSInputFile(video_path), caption="😼 Украл для вас")
                os.remove(video_path) # Удаляем файл после отправки
            except:
                await message.reply("Не пролезло в трубу (слишком жирный файл).")
                if os.path.exists(video_path): os.remove(video_path)
        return # Прерываем, чтобы кот не комментировал ссылку

    # 2. ИСТОРИЯ
    cid = message.chat.id
    history = get_history(cid)
    if not message.text.startswith('/'):
        history.append({"role": "user", "name": message.from_user.first_name, "content": message.text})

    bot_info = await bot.get_me()
    
    # 3. ТРИГГЕРЫ (Когда отвечать?)
    is_private = message.chat.type == ChatType.PRIVATE
    is_named = "башмак" in message.text.lower()
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    is_random = random.random() < 0.10 # 10% ШАНС ВМЕШАТЬСЯ

    if not (is_private or is_named or is_reply or is_random): return

    # 4. ВЫБОР ЛИЧНОСТИ
    selected_role = None
    
    # Если это REPLY, проверяем смайлик в прошлом сообщении
    if is_reply and message.reply_to_message.text:
        last_text = message.reply_to_message.text.strip()
        # Ищем роль по смайлику в конце
        for role in ROLES:
            if last_text.endswith(role["emoji"]):
                selected_role = role
                break
    
    # Если не нашли (или это не реплай), берем случайную
    if not selected_role:
        selected_role = random.choice(ROLES)

    # 5. ГЕНЕРАЦИЯ ОТВЕТА
    sys_prompt = (
        f"{selected_role['prompt']} "
        "Отвечай коротко (1-3 предложения). "
        "СТРОГИЙ ЗАПРЕТ на скобки типа ))). "
        f"В конце сообщения ОБЯЗАТЕЛЬНО поставь этот смайл: {selected_role['emoji']}"
    )

    msgs = [{"role": "system", "content": sys_prompt}]
    for m in list(history)[-8:]: 
        msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})

    await bot.send_chat_action(cid, "typing")
    reply = await ask_model(msgs)
    
    # Страховка: если нейронка забыла смайл, добавляем сами
    if selected_role['emoji'] not in reply:
        reply += f" {selected_role['emoji']}"
        
    await message.reply(reply)

# --- ПЛАНИРОВЩИК ---
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
                await send_daily_summary(cid)
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
