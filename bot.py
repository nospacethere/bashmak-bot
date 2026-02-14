import os, asyncio, datetime, pytz, random
from collections import deque
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.types import BotCommand
from openai import AsyncOpenAI # Используем библиотеку openai для OpenRouter
from aiohttp import web

# --- КОНФИГ ---
TOKEN = os.getenv("BOT_TOKEN")
# Ключ от OpenRouter (создай на openrouter.ai)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Настройка клиента под OpenRouter
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ПАМЯТЬ
user_history = {} 
def get_history(chat_id):
    if chat_id not in user_history: 
        user_history[chat_id] = deque(maxlen=100)
    return user_history[chat_id]

async def ask_model(messages, model="deepseek/deepseek-chat", temp=0.8):
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temp,
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Ошибка: {e}")
        return "Мозг кота временно недоступен. Попробуй позже."

# --- ФУНКЦИЯ СВОДКИ ---
async def send_daily_summary(chat_id):
    history = get_history(chat_id)
    clean_history = [m for m in list(history) if not m['content'].startswith('/')]
    if not clean_history: 
        return "Тут было слишком тихо. Никто ничего не сказал, а я не собираюсь выдумывать."
    
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean_history])
    prompt = (
        f"Ты — Башмак, язвительный и прямой кот. Составь краткий и смешной итог переписки:\n{text_dump}\n"
        "ВАЖНО: Пиши только по фактам из текста, не выдумывай то, чего не было. "
        "Стеби участников, подмечай тупость, но оставайся в контексте. Максимум 5-6 предложений."
    )
    
    return await ask_model([{"role": "user", "content": prompt}])

# --- КОМАНДЫ ---
@dp.message(Command("roast"))
async def cmd_roast(message: types.Message):
    history = get_history(message.chat.id)
    clean_history = [m for m in list(history) if not m['content'].startswith('/')]
    if not clean_history: return await message.reply("Некого жарить.")
    
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean_history[-20:]])
    prompt = f"Ты кот Башмак. Разнеси этих людей на основе их последних сообщений, будь грубым и прямым:\n{text_dump}"
    res = await ask_model([{"role": "user", "content": prompt}], temp=1.0)
    await message.answer(f"🔥 **РАЗНОС:**\n{res}")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    res = await send_daily_summary(message.chat.id)
    await message.answer(f"📝 **ИТОГИ ПЕРЕПИСКИ:**\n{res}")

@dp.message(Command("start"))
async def start(message: types.Message):
    await bot.set_my_commands([
        BotCommand(command="start", description="Оживить"),
        BotCommand(command="roast", description="Прожарка"),
        BotCommand(command="summary", description="Итоги"),
    ])
    await message.answer("😼 Башмак на DeepSeek. Без лишней клоунады и грехов. Только факты и сарказм.")

# --- ЧАТ ---
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

    prompt = "Ты Башмак, язвительный кот Данила. Отвечай прямо, коротко и с сарказмом. Никаких скобочек и лишней вежливости."
    msgs = [{"role": "system", "content": prompt}]
    for m in list(history)[-10:]: 
        msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})
    
    await bot.send_chat_action(chat_id=cid, action="typing")
    reply = await ask_model(msgs)
    await message.reply(reply)

# --- ПЛАНИРОВЩИК ---
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
                try: 
                    res = await send_daily_summary(cid)
                    await bot.send_message(cid, f"📝 **ИТОГИ ДНЯ:**\n{res}")
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
