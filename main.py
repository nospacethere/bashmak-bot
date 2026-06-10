import asyncio, os
from aiohttp import web
from aiogram.types import BotCommand
from config import bot, dp, SKIP_DELETE_PREFIXES
import admin, handlers, chat, scheduler
from scheduler import scheduler

_orig_send_message = bot.send_message

async def _delete_later(msg, delay=300):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception as e:
        print(f"Auto-delete failed for msg {msg.message_id}: {e}")

async def _patched_send_message(chat_id, text, **kwargs):
    msg = await _orig_send_message(chat_id, text, **kwargs)
    if text and not text.startswith(SKIP_DELETE_PREFIXES):
        asyncio.create_task(_delete_later(msg))
    return msg

bot.send_message = _patched_send_message

async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bashmak is alive"))
    runner = web.AppRunner(app)
    await runner.setup()
    endpoint = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 8080)))
    await endpoint.start()

    commands = [
        BotCommand(command="top", description="🏆 Зал славы казино"),
        BotCommand(command="inventory", description="🎒 Мой инвентарь"),
        BotCommand(command="get_item", description="🎁 Купить случайный предмет (10 фишек)"),
        BotCommand(command="use", description="🎲 Использовать предмет: /use <название>"),
        BotCommand(command="day", description="🗓️ Текущий день сезона"),
        BotCommand(command="hof", description="🏛 Зал славы всех сезонов"),
    ]
    await bot.set_my_commands(commands)
    await bot.delete_webhook(drop_pending_updates=True)

    print("Waiting 10s for old instance to shut down...")
    await asyncio.sleep(10)
    asyncio.create_task(scheduler())
    print("Bot started polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
