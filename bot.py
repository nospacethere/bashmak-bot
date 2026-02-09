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

# ПАМЯТЬ (теперь 100 сообщений)
user_history = {} 
def get_history(chat_id):
    if chat_id not in user_history: 
        user_history[chat_id] = deque(maxlen=100)
    return user_history[chat_id]

async def ask_groq_async(messages, model="llama-3.3-70b-versatile", temp=0.7):
    loop = asyncio.get_running_loop()
    def _request():
        try:
            return client.chat.completions.create(
                messages=messages, model=model, max_tokens=200, temperature=temp
            ).choices[0].message.content
        except Exception as e:
            print(f"Ошибка Groq: {e}")
            return "Бля, у меня мозги заклинило. Видимо, кто-то слишком много тупил в чате."
    return await loop.run_in_executor(None, _request)

# --- ФУНКЦИЯ СВОДКИ ---
async def send_daily_summary(chat_id):
    history = get_history(chat_id)
    # Фильтруем историю, чтобы не было пустых строк или одних команд
    clean_history = [m for m in list(history) if not m['content'].startswith('/')]
    if not clean_history: 
        return "Тут было так скучно, что даже подытоживать нечего."
    
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean_history[-30:]])
    prompt = f"Ты — Башмак. Коротко и едко перескажи главные темы этого диалога:\n{text_dump}\nПиши как саркастичный кот. Максимум 2-3 предложения. Никаких скобочек."
    
    res = await ask_groq_async([{"role": "user", "content": prompt}])
    return res

# --- КОМАНДЫ ---
@dp.message(Command("roast"))
async def cmd_roast(message: types.Message):
    history = get_history(message.chat.id)
    clean_history = [m for m in list(history) if not m['content'].startswith('/')]
    if not clean_history: return await message.reply("Чат пустой, жарить некого.")
    
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean_history[-15:]])
    # Смягчаем промпт для обхода фильтров "ненависти"
    prompt = f"Ты — мастер ироничных замечаний. Пошути над этими сообщениями в стиле Башмака:\n{text_dump}\nБудь краток и язвителен."
    res = await ask_groq_async([{"role": "user", "content": prompt}], temp=0.9)
    await message.answer(f"🔥 **ПРОЖАРКА:**\n{res}")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    res = await send_daily_summary(message.chat.id)
    await message.answer(f"📝 **ИТОГО:**\n{res}")

@dp.message(Command("start"))
async def start(message: types.Message):
    await bot.set_my_commands([
        BotCommand(command="start", description="Оживить"),
        BotCommand(command="roast", description="Разнос чата"),
        BotCommand(command="summary", description="Итоги сейчас"),
    ])
    await message.answer("😼 Башмак на связи. Пул 100, 13:37 кубик, 22:00 сводка. Всё работает.")

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

    prompt = "Ты Башмак, язвительный кот. Отвечай ОЧЕНЬ коротко (1 фраза). СТРОГИЙ ЗАПРЕТ на скобки типа ))) и действия в скобках."
    msgs = [{"role": "system", "content": prompt}]
    # Берем последние 7 сообщений для контекста
    recent = list(history)[-7:]
    for m in recent: msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})
    
    await bot.send_chat_action(chat_id=cid, action="typing")
    reply = await ask_groq_async(msgs)
    await message.reply(reply)

# --- ПЛАНИРОВЩИК ---
async def scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        # 13:37 - Кубик
        if now.hour == 13 and now.minute == 37:
            for cid in list(user_history.keys()):
                try: await bot.send_dice(cid, emoji='🎰')
                except: pass
            await asyncio.sleep(61)
        # 22:00 - Сводка дня
        if now.hour == 22 and now.minute == 0:
            for cid in list(user_history.keys()):
                try: 
                    res = await send_daily_summary(cid)
                    await bot.send_message(cid, f"📝 **АВТО-ИТОГИ ДНЯ:**\n{res}")
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
