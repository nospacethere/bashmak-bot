import asyncio, datetime, pytz
from aiogram import types
from aiogram.filters import Command, CommandObject
from config import bot, dp, ADMIN_ID, scores_col, inventories_col, spin_counts_col, game_state_col, amulets_col, chats_col, hof_col, ITEMS, ZODIAC_RUS, PLAYER_ZODIACS
from scheduler import schedule_bot_spins, distribute_daily_items_and_announce, execute_bot_spin, send_daily_horoscopes
from utils import get_all_chat_ids, broadcast_message, send_gambling_summary
from items import execute_bot_single_item
from config import user_history

@dp.message(Command("admin_wipe_scores_777"))
async def cmd_admin_wipe(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await scores_col.drop()
    await inventories_col.drop()
    await spin_counts_col.drop()
    await game_state_col.drop()
    await amulets_col.drop()
    await chats_col.drop()
    await message.answer("💥 Казино сожжено дотла! 💥\nВсе ставки, инвентари, счетчики спинов, амулеты, чаты и состояние игры обнулены.")
    bot_user = await bot.get_me()
    await scores_col.update_one({"user_id": bot_user.id}, {"$set": {"name": "Гемблинг Башмак", "balance": 100}}, upsert=True)
    await message.answer("Крупье тоже в игре. Гемблинг Башмак ставит на кон свои 100 фишек. 😼")

@dp.message(Command("admin_give_item"))
async def cmd_admin_give_item(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    item_key = command.args.strip().lower() if command.args else None
    if not item_key or item_key not in ITEMS:
        valid_keys = ", ".join([f"`{k}`" for k in ITEMS.keys()])
        await message.answer(f"Неверное название предмета. Доступные: {valid_keys}")
        return
    await inventories_col.update_one({"user_id": message.from_user.id}, {"$push": {"items": item_key}}, upsert=True)
    await message.answer(f"Вы получили: {ITEMS[item_key]['name']}")

@dp.message(Command("admin_force_daily_reset"))
async def cmd_force_daily_reset(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("⏳ Принудительно запускаю ежедневный сброс и раздачу предметов...")
    all_ids = await get_all_chat_ids()
    for cid in all_ids:
        try:
            await send_gambling_summary(cid)
        except Exception as e:
            print(f"Failed to send summary to {cid}: {e}")
    await spin_counts_col.delete_many({})
    await game_state_col.update_one({}, {"$set": {"last_daily_reset_date": None}}, upsert=True)
    await message.answer("✅ Счетчики спинов сброшены.")
    for cid in list(user_history.keys()):
        user_history[cid].clear()
    await message.answer("✅ История чатов очищена.")
    await distribute_daily_items_and_announce()
    schedule_bot_spins()
    await message.answer("✅ Ежедневные предметы розданы и анонсированы.")
    await message.answer("🎉 Готово! Все ежедневные задачи выполнены.")

@dp.message(Command("admin_force_bot_action"))
async def cmd_admin_force_bot_action(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("😼 Заставляю Башмака отработать всё за today...")
    await force_bot_full_action()
    await message.answer("✅ Башмак отработал все предметы и спины!")

@dp.message(Command("admin_add_points"))
async def cmd_admin_add_points(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    if not command.args:
        await message.answer("Укажите: /admin_add_points <user_id> <сумма>")
        return
    parts = command.args.strip().split()
    if len(parts) != 2:
        await message.answer("Нужно 2 аргумента: /admin_add_points <user_id> <сумма>")
        return
    try:
        target_id = int(parts[0])
        amount = int(parts[1])
    except ValueError:
        await message.answer("user_id и сумма должны быть числами")
        return
    user_doc = await scores_col.find_one({"user_id": target_id})
    if not user_doc:
        await message.answer(f"Игрок с id {target_id} не найден в базе")
        return
    await scores_col.update_one({"user_id": target_id}, {"$inc": {"balance": amount}})
    new_bal = (await scores_col.find_one({"user_id": target_id}))["balance"]
    name = user_doc.get("name", str(target_id))
    await message.answer(f"✅ {name}: {amount:+} фишек. Баланс: {new_bal}")

@dp.message(Command("admin_set_casino_chat"))
async def cmd_admin_set_casino_chat(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await game_state_col.update_one({}, {"$set": {"casino_chat_id": message.chat.id}}, upsert=True)
    await message.answer(f"✅ Этот чат ({message.chat.id}) назначен игровым казино!")

@dp.message(Command("admin_start_horoscope"))
async def cmd_admin_start_horoscope(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await game_state_col.update_one(
        {},
        {"$set": {"horoscope_enabled": True, "horoscope_chat_id": message.chat.id}},
        upsert=True,
    )
    await message.answer("🔮 Гороскоп включён! Сейчас выдам на сегодня...")
    try:
        await send_daily_horoscopes()
        today = datetime.datetime.now(pytz.timezone('Europe/Moscow')).date().isoformat()
        await game_state_col.update_one({}, {"$set": {f"horoscope_done_{today}": True}})
    except Exception as e:
        await message.answer(f"⚠️ Ошибка при отправке гороскопа: {e}")

@dp.message(Command("admin_stop_horoscope"))
async def cmd_admin_stop_horoscope(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await game_state_col.update_one({}, {"$set": {"horoscope_enabled": False}}, upsert=True)
    await message.answer("🌙 Гороскоп отключён.")

@dp.message(Command("admin_set_zodiac"))
async def cmd_admin_set_zodiac(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    if not command.args:
        await message.answer("Укажите: /admin_set_zodiac <имя> <знак>")
        return
    parts = command.args.strip().split()
    if len(parts) != 2:
        await message.answer("Нужно 2 аргумента: /admin_set_zodiac <имя> <знак>")
        return
    name, sign_rus = parts[0], parts[1]
    sign_eng = None
    for eng, rus in ZODIAC_RUS.items():
        if rus.lower() == sign_rus.lower():
            sign_eng = eng
            break
    if not sign_eng:
        await message.answer("Знак не распознан. Доступные: " + ", ".join(ZODIAC_RUS.values()))
        return
    res = await scores_col.update_many({"name": name}, {"$set": {"zodiac": sign_eng}})
    PLAYER_ZODIACS[name] = sign_eng
    await message.answer(f"✅ {name} → {ZODIAC_RUS[sign_eng]} (обновлено игроков: {res.modified_count})")

@dp.message(Command("admin_start_season"))
async def cmd_admin_start_season(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    start_date = datetime.datetime.now(pytz.timezone('Europe/Moscow')).replace(tzinfo=None)
    season_number = (await hof_col.count_documents({})) + 1
    await game_state_col.update_one(
        {},
        {
            "$set": {
                "start_date": start_date,
                "game_ended": False,
                "season_number": season_number,
                "last_daily_reset_date": None,
                "casino_chat_id": message.chat.id,
            }
        },
        upsert=True,
    )
    await spin_counts_col.delete_many({})
    schedule_bot_spins()
    await broadcast_message(
        f"🎰 Гемблинг Лига Башмака №{season_number} официально открыта!\n\n"
        f"14 дней удачи, риска и больших ставок. Делайте ваши спины! 🎲",
        delay=0.3,
    )
    await message.answer(f"✅ Сезон №{season_number} запущен!")

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await send_gambling_summary(message.chat.id)

async def force_bot_full_action():
    bot_user = await bot.get_me()
    bot_id = bot_user.id
    bot_usable = ["chaos_cube", "money_pouch", "stone_rain", "golden_boot", "madness_coin", "double_down"]

    inv_doc = await inventories_col.find_one({"user_id": bot_id})
    if inv_doc and inv_doc.get("items"):
        items_copy = list(inv_doc["items"])
        for item_key in items_copy:
            if item_key in bot_usable:
                try:
                    inv_doc["items"].remove(item_key)
                except ValueError:
                    continue
                await inventories_col.update_one(
                    {"user_id": bot_id},
                    {"$set": {"items": inv_doc["items"]}},
                )
                await execute_bot_single_item(item_key)
                await asyncio.sleep(5)

    for _ in range(2):
        spin_count_doc = await spin_counts_col.find_one({'user_id': bot_id})
        spins_done = spin_count_doc.get('count', 0) if spin_count_doc else 0
        if spins_done < 2:
            await execute_bot_spin()
            await asyncio.sleep(5)
