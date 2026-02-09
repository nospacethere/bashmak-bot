import os, asyncio, datetime, pytz, random
from collections import deque
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.types import BotCommand
from groq import Groq
from aiohttp import web

TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

user_history = {} 
def get_history(chat_id):
    if chat_id not in user_history: user_history[chat_id] = deque(maxlen=100) # Пул увеличен до 50
    return user_history[chat_id]

async def ask_groq_async(messages, model="llama-3.3-70b-versatile", temp=0.8):
    loop = asyncio.get_running_loop()
    def _request():
        try:
            return client.chat.completions.create(
                messages=messages, model=model, max_tokens=150, temperature=temp
            ).choices[0].message.content
        except: return "Мозги заклинило."
    return await loop.run_in_executor(None, _request)

# --- ФУНКЦИЯ СВОДКИ (для команды и для авто-отправки) ---
async def send_daily_summary(chat_id):
    history = get_history(chat_id)
    if not history: return
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in history])
    prompt = f"Коротко и едко перескажи итоги дня в этом чате:\n{text_dump}\nМаксимум 2 предложения."
    res = await ask_groq_async([{"role": "user", "content": prompt}])
    await bot.send_message(chat_id, f"📝 **ИТОГИ ДНЯ:**\n{res}")

# --- КОМАНДЫ ---
@dp.message(Command("roast"))
async def cmd_roast(message: types.Message):
    history = get_history(message.chat.id)
    if not history: return await message.reply("Пусто.")
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in history])
    prompt = f"Ты — циничный Башмак. Сделай ОЧЕНЬ короткий и злой разнос:\n{text_dump}"
    res = await ask_groq_async([{"role": "user", "content": prompt}], temp=0.9)
    await message.answer(f"🔥 **ПРОЖАРКА:**\n{res}")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    await send_daily_summary(message.chat.id)

@dp.message(Command("start"))
async def start(message: types.Message):
    await bot.set_my_commands([
        BotCommand(command="start", description="Оживить"),
        BotCommand(command="roast", description="Разнос"),
        BotCommand(command="summary", description="Итоги сейчас"),
    ])
    await message.answer("😼 Пул 50, сводка в 22:00. Жду.")

# --- ТЕКСТ ---
@dp.message()
async def chat(message: types.Message):
    if message.from_user.is_bot or not message.text: return
    cid = message.chat.id
    history = get_history(cid)
    if not message.text.startswith('/'):
        history.append({"role": "user", "name": message.from_user.first_name, "content": message.text})
    
    bot_info = await bot.get_me()
    if not (message.chat.type == ChatType.PRIVATE or "башмак" in message.text.lower() or (message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id)): return

    prompt = "Ты Башмак, злой кот. Отвечай ОЧЕНЬ коротко (1 фраза). Без скобок ))) и действий."
    msgs = [{"role": "system", "content": prompt}]
    for m in list(history)[-7:]: msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})
    
    await bot.send_chat_action(chat_id=cid, action="typing")
    reply = await ask_groq_async(msgs)
    await message.reply(reply)

# --- ПЛАНИРОВЩИК (13:37 и 22:00) ---
async def scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        # Казино в 13:37
        if now.hour == 13 and now.minute == 37:
            for cid in list(user_history.keys()):
                try: await bot.send_dice(cid, emoji='🎰')
                except: pass
            await asyncio.sleep(61)
        # Сводка в 22:00
        if now.hour == 22 and now.minute == 0:
            for cid in list(user_history.keys()):
                try: await send_daily_summary(cid)
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
