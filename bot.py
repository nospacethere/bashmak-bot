import os
import asyncio
import datetime
import pytz
import random
from collections import deque
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ChatType
from groq import Groq
from aiohttp import web

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

bot_id = None

# --- ПАМЯТЬ ---
user_history = {} 

def get_history(chat_id):
    if chat_id not in user_history:
        user_history[chat_id] = deque(maxlen=50)
    return user_history[chat_id]

async def ask_groq_async(messages, max_tokens=1000, temperature=0.8):
    loop = asyncio.get_running_loop()
    def _request():
        try:
            return client.chat.completions.create(
                messages=messages, 
                model="llama-3.3-70b-versatile",
                max_tokens=max_tokens,
                temperature=temperature
            ).choices[0].message.content
        except Exception as e:
            print(f"Groq Error: {e}")
            return "У меня временный паралич мозжечка. Спроси позже."
    
    return await loop.run_in_executor(None, _request)

# --- КОМАНДЫ ---

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("😼 Башмак в сети. Фильтры подрезаны, ирония на максимуме. Жги.")

@dp.message(Command("roast"))
async def cmd_roast(message: types.Message):
    cid = message.chat.id
    history = get_history(cid)
    if not history:
        await message.answer("Чат пустой, кого мне обсирать? Стены?")
        return

    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in history])
    
    # Промпт переписан так, чтобы НЕ триггерить фильтры безопасности
    prompt = (
        f"Ты — Башмак, мастер экстремального сарказма и черного юмора. "
        f"Перед тобой переписка этих персонажей:\n{text_dump}\n\n"
        "Твоя задача: сделай разнос этого чата в стиле жесткого стендапа. "
        "1. Высмеивай их логику, ошибки и само ведение диалога.\n"
        "2. Будь максимально язвительным и циничным.\n"
        "3. СТРОЖАЙШИЙ ЗАПРЕТ на скобки типа ')))' и действия в скобках типа '(смеется)'.\n"
        "4. Пиши только текст от своего имени. Используй крепкое словцо, если оно уместно для шутки."
    )

    msg = await message.answer("🔥 Разогреваю сковородку...")
    res = await ask_groq_async([{"role": "user", "content": prompt}], temperature=0.9)
    await msg.edit_text(f"☠️ **РАЗНОС:**\n\n{res}", parse_mode="Markdown")

# --- ОБРАБОТКА ЧАТА ---
@dp.message()
async def chat(message: types.Message):
    global bot_id
    if message.from_user.is_bot or not message.text: return

    if not bot_id:
        me = await bot.get_me()
        bot_id = me.id

    cid = message.chat.id
    text = message.text
    text_lower = text.lower()
    
    history = get_history(cid)
    if not text.startswith('/'):
        history.append({"role": "user", "name": message.from_user.first_name, "content": text})

    is_named = "башмак" in text_lower or "bashmak" in text_lower
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_id
    is_private = message.chat.type == ChatType.PRIVATE
    
    if not (is_private or is_named or is_reply):
        return

    system_prompt = (
        "Ты — Башмак, кот Данила. Ты циничный, прямой и не терпишь тупости. "
        "Твои ответы должны быть короткими (1-2 предложения) и острыми. "
        "ПРАВИЛА:\n"
        "1. НИКОГДА НЕ ИСПОЛЬЗУЙ СКОБКИ ))).\n"
        "2. НИКАКИХ ОПИСАНИЙ ДЕЙСТВИЙ (улыбается, чешет за ухом). Это запрещено.\n"
        "3. Если Данил просит быть прямым — будь прямым. Никакой вежливости из службы поддержки."
    )

    msgs = [{"role": "system", "content": system_prompt}]
    recent = list(history)[-7:]
    for m in recent:
        msgs.append({"role": "user", "content": f"{m['name']}: {m['content']}"})

    try:
        await bot.send_chat_action(chat_id=cid, action="typing")
        reply = await ask_groq_async(msgs)
        await message.reply(reply)
    except Exception as e:
        print(f"Chat Error: {e}")

# --- ФОН ---
async def scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        if now.hour == 13 and now.minute == 37:
            for cid in list(user_history.keys()):
                try: await bot.send_dice(cid, emoji='🎰')
                except: pass
            await asyncio.sleep(65)
        await asyncio.sleep(40)

async def health(request): return web.Response(text="Bashmak is alive")

async def main():
    app = web.Application(); app.router.add_get("/", health)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    asyncio.create_task(scheduler())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
