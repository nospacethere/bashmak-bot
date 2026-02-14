import os, asyncio, datetime, pytz, random
from collections import deque
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.types import BotCommand
from groq import Groq
from aiohttp import web

# --- КОНФИГ ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ПАМЯТЬ
user_history = {} 
def get_history(chat_id):
    if chat_id not in user_history: 
        user_history[chat_id] = deque(maxlen=100)
    return user_history[chat_id]

# --- 7 ГРЕХОВ БАШМАКА ---
SINS = [
    {"name": "Гордыня", "emoji": "👑", "style": "высокомерно, считай всех ничтожествами, а себя богом"},
    {"name": "Жадность", "emoji": "💰", "style": "одержим деньгами, выгодой и тем, как бы всё забрать себе"},
    {"name": "Похоть", "emoji": "🫦", "style": "чрезмерно игриво, двусмысленно и флиртующе (но без жести)"},
    {"name": "Зависть", "emoji": "🐍", "style": "жалуйся, что у других всё лучше, язвительно принижай чужие успехи"},
    {"name": "Чревоугодие", "emoji": "🍗", "style": "постоянно думай о еде, сравнивай всё с сосисками и жратвой"},
    {"name": "Гнев", "emoji": "🤬", "style": "агрессивно, капсом, используй ругательства, злись на всё подряд"},
    {"name": "Лень", "emoji": "😴", "style": "сонно, апатично, тебе лень даже писать, отвечай максимально нехотя"}
]

async def ask_groq_async(messages, model="llama-3.3-70b-versatile", temp=0.9):
    loop = asyncio.get_running_loop()
    def _request():
        try:
            return client.chat.completions.create(
                messages=messages, model=model, max_tokens=300, temperature=temp
            ).choices[0].message.content
        except: return "Мозги заклинило от твоей тупости."
    return await loop.run_in_executor(None, _request)

# --- АБСУРДНАЯ СВОДКА ---
async def send_daily_summary(chat_id):
    history = get_history(chat_id)
    clean_history = [m for m in list(history) if not m['content'].startswith('/')]
    if not clean_history: return "Тут была тишина, я сам себе придумал драку с пылесосом."
    
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean_history])
    prompt = (
        f"Ты — Башмак, который перепил валерьянки. Сделай нелепый и смешной пересказ чата:\n{text_dump}\n"
        "ПРАВИЛА: Путай факты, ври, обвиняй людей в том, чего они не делали, смешивай имена. "
        "Это должно звучать как живой бред кота, а не отчет робота. Максимум 10 предложений."
    )
    
    res = await ask_groq_async([{"role": "user", "content": prompt}], temp=1.0)
    return res

# --- КОМАНДЫ ---
@dp.message(Command("roast"))
async def cmd_roast(message: types.Message):
    history = get_history(message.chat.id)
    clean_history = [m for m in list(history) if not m['content'].startswith('/')]
    if not clean_history: return await message.reply("Некого жарить, все вымерли.")
    
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean_history[-20:]])
    prompt = f"Ты циничный кот. Выдай максимально неадекватный и смешной разнос этих людей:\n{text_dump}"
    res = await ask_groq_async([{"role": "user", "content": prompt}], temp=1.0)
    await message.answer(f"🔥 **ПРИСТУП ЯРОСТИ:**\n{res}")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    res = await send_daily_summary(message.chat.id)
    await message.answer(f"📝 **БРЕДОВЫЕ ИТОГИ:**\n{res}")

@dp.message(Command("start"))
async def start(message: types.Message):
    await bot.set_my_commands([
        BotCommand(command="start", description="Пробудить демона"),
        BotCommand(command="roast", description="Прожарка"),
        BotCommand(command="summary", description="Сводка бреда"),
    ])
    await message.answer("😼 Башмак и его 7 грехов в деле. Пул 100 забит. Жду.")

# --- ТЕКСТОВЫЙ ЧАТ ---
@dp.message()
async def chat(message: types.Message):
    if message.from_user.is_bot or not message.text: return
    cid = message.chat.id
    history = get_history(cid)
    
    if not message.text.startswith('/'):
        history.append({"role": "user", "name": message.from_user.first_name, "content": message.text})
    
    bot_info = await bot.get_me()
    is_named = "башмак" in message.text.lower()
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    if not (message.chat.type == ChatType.PRIVATE or is_named or is_reply): return

    # ВЫБОР ГРЕХА
    sin = random.choice(SINS)
    prompt = (
        f"Ты — кот Башмак в состоянии греха '{sin['name']}'. Твой стиль: {sin['style']}. "
        "Отвечай не длинно максимум 3-4 осмысленных предложения. СТРОГИЙ ЗАПРЕТ на скобки типа ))) и действия в скобках. "
        f"В конце сообщения ОБЯЗАТЕЛЬНО поставь ОДИН символ {sin['emoji']}."
    )

    msgs = [{"role": "system", "content": prompt}]
    for m in list(history)[-8:]: msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})
    
    await bot.send_chat_action(chat_id=cid, action="typing")
    reply = await ask_groq_async(msgs)
    await message.reply(reply)

# --- ПЛАНИРОВЩИК ---
async def scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        # 13:37 - Казино
        if now.hour == 13 and now.minute == 37:
            for cid in list(user_history.keys()):
                try: await bot.send_dice(cid, emoji='🎰')
                except: pass
            await asyncio.sleep(61)
        # 22:00 - Абсурдные итоги
        if now.hour == 22 and now.minute == 0:
            for cid in list(user_history.keys()):
                try: 
                    res = await send_daily_summary(cid)
                    await bot.send_message(cid, f"📝 **ЕЖЕДНЕВНЫЙ ГЛЮК (ИТОГИ):**\n{res}")
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


