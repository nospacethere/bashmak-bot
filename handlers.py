import datetime, random, pytz
from aiogram import types
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from config import bot, dp, scores_col, inventories_col, spin_counts_col, game_state_col, amulets_col, hof_col, chats_col, ITEMS, user_history
from utils import calculate_win, get_leaderboard_text, handle_vampire_amulet, get_casino_chat_id
from items import use_item_logic

WELCOME_TEXT = """😼 Добро пожаловать в подпольное казино «Гемблинг Башмак»!

Здесь удача улыбается смелым, а риск — второе имя. Твоя цель — сорвать куш, подняться в таблице лидеров (/top) и стать легендой этого заведения.

Ты начинаешь со 100 фишками и стартовым бонусом: тебе достался предмет «{starter_item_name}»! Проверь его в /inventory.

---

🎲 ПРАВИЛА СПИНОВ

У тебя есть 2 бесплатные попытки в день. Каждая ставка может изменить всё. Используй их с умом!

Игра длится 14 дней. В конце сезона казино закрывается, а лучшие игроки попадают в Зал Славы! Сегодня 1-й день. (/day)

---

🏆 ТАБЛИЦА ВЫИГРЫШЕЙ

- 7️⃣7️⃣7️⃣ (Джекпот): +50 фишек
- Три одинаковых символа (включая BAR): +20 фишек
- Два одинаковых символа: -1 фишка
- Проигрыш: -5 фишек

---

🎁 ЛАВКА КОНТРАБАНДЫ

За фишки можно купить особые предметы через команду /get_item. Они могут перевернуть игру.
{item_descriptions}

---

Команды для игры:
- /top — посмотреть зал славы.
- /inventory — проверить свои предметы.
- /get_item — купить случайный предмет за 10 фишек.
- /day — узнать текущий день сезона.

Да начнутся игры! Делай свою первую ставку. 🎰
"""

@dp.message(Command("inventory"))
async def cmd_inventory(message: types.Message):
    casino_id = await get_casino_chat_id()
    if casino_id and message.chat.id != casino_id: return
    user_id = message.from_user.id
    inv_doc = await inventories_col.find_one({"user_id": user_id})
    if not inv_doc or not inv_doc.get("items"):
        await message.answer("🎒 Ваш инвентарь пуст.\n\nДелайте ставки или используйте /get_item, чтобы получить свой первый предмет! 🎰")
        return
    text = "🎒 Ваш инвентарь:\n\n"
    item_counts = {k: inv_doc["items"].count(k) for k in set(inv_doc["items"])}
    buttons = []
    for item_key, count in sorted(item_counts.items()):
        item = ITEMS[item_key]
        text += f"{item['name']} (x{count})\nОписание: {item['description']}\n\n"
        buttons.append([InlineKeyboardButton(text=f"Использовать {item['name']}", callback_data=f"use_item:{item_key}")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard, parse_mode=None)

@dp.callback_query(lambda c: c.data and c.data.startswith("use_item:"))
async def process_use_item_callback(callback_query: CallbackQuery):
    casino_id = await get_casino_chat_id()
    if casino_id and callback_query.message.chat.id != casino_id: return
    item_key = callback_query.data.split(":")[1]
    await callback_query.answer(f"Используем {ITEMS[item_key]['name']}...")
    await use_item_logic(callback_query.from_user, item_key, callback_query.message)

@dp.message(Command("get_item"))
async def cmd_get_item(message: types.Message):
    casino_id = await get_casino_chat_id()
    if casino_id and message.chat.id != casino_id: return
    user_id = message.from_user.id
    gs = await game_state_col.find_one()
    if gs and gs.get("game_ended"):
        await message.reply("🏁 Сезон окончен, лавка контрабанды закрыта. Ждите новый сезон! 🎰")
        return
    if gs and 'start_date' not in gs:
        await message.reply("🏁 Сезон ещё не запущен. Ждите команды крупье! 🎰")
        return
    user_doc = await scores_col.find_one({"user_id": user_id})
    if not user_doc:
        await message.reply("Вы еще не играли в казино! Сделайте ставку, чтобы начать. 🎰")
        return
    cost = 10
    if user_doc.get('balance', 0) < cost:
        await message.reply(f"Недостаточно фишек для покупки случайного предмета. Стоимость: {cost} фишек. 🎰")
        return
    pool = [k for k in ITEMS.keys()]
    item_key = random.choice(pool)
    await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": -cost}})
    await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": item_key}}, upsert=True)
    new_balance = (await scores_col.find_one({"user_id": user_id})).get('balance', 'N/A')
    await message.answer(f"Вы потратили {cost} фишек и получили: {ITEMS[item_key]['name']}!\nВаш новый баланс: {new_balance} фишек. 🎰")

@dp.message(Command("use"))
async def cmd_use(message: types.Message, command: CommandObject):
    casino_id = await get_casino_chat_id()
    if casino_id and message.chat.id != casino_id: return
    if command.args is None:
        await message.reply("Напишите предмет, который хотите использовать, например: `/use money_pouch`")
        return
    item_key = command.args.strip().lower()
    await use_item_logic(message.from_user, item_key, message)

@dp.message(lambda m: m.dice and m.dice.emoji == '🎰' and not m.from_user.is_bot)
async def handle_dice(message: types.Message):
    casino_id = await get_casino_chat_id()
    if casino_id and message.chat.id != casino_id: return
    await chats_col.update_one({'chat_id': message.chat.id}, {'$set': {'last_seen': datetime.datetime.now(pytz.utc)}}, upsert=True)
    user_id = message.from_user.id
    user_name = message.from_user.first_name

    gs = await game_state_col.find_one()
    if gs and gs.get("game_ended"):
        await message.reply("🏁 Игровой сезон завершён! Дождитесь нового сезона или попросите админа сбросить игру. 🎰")
        return
    if not gs or 'start_date' not in gs:
        await message.reply("🏁 Сезон ещё не запущен. Админ должен запустить его командой /admin_start_season. 🎰")
        return

    user_doc = await scores_col.find_one({'user_id': user_id})
    is_new_user = False
    if not user_doc:
        is_new_user = True
        start_balance = 100
        starter_item_key = random.choice(list(ITEMS.keys()))
        await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": starter_item_key}}, upsert=True)
        await scores_col.insert_one({
            "user_id": user_id, "name": user_name, "balance": start_balance, "active_effects": []
        })
        user_doc = await scores_col.find_one({'user_id': user_id})

    spin_count_doc = await spin_counts_col.find_one({'user_id': user_id})
    spin_count = spin_count_doc.get('count', 0) if spin_count_doc else 0
    current_spin_number = spin_count + 1
    if current_spin_number > 2:
        await message.reply("На сегодня твои попытки в казино закончились! Возвращайся завтра. 🎰")
        return

    current_balance = user_doc.get('balance', 0)
    if is_new_user:
        sd = await inventories_col.find_one({"user_id": user_id})
        sk = sd['items'][0] if sd and sd.get('items') else starter_item_key
        sn = ITEMS[sk]['name']
        descriptions = "\n".join([f"- {item['name']}: {item['description']}" for item in ITEMS.values()])
        await message.answer(WELCOME_TEXT.format(starter_item_name=sn, item_descriptions=descriptions), parse_mode=None)

    await spin_counts_col.update_one({'user_id': user_id}, {'$inc': {'count': 1}}, upsert=True)
    cost_msg = f"(Спин {current_spin_number}/2) "
    base_change = calculate_win(message.dice.value)
    final_change = base_change

    active_effects = user_doc.get('active_effects', [])
    effects_to_remove = []
    effect_msgs = []

    if "double_down" in active_effects:
        final_change *= 2
        effect_msgs.append("⏫ Двойная Ставка удваивает результат!")
        effects_to_remove.append("double_down")

    if "madness_coin" in active_effects:
        is_shield = random.random() < 0.5
        cb = final_change
        if is_shield and final_change < 0:
            final_change = 0
            effect_msgs.append(f"🌓 Сработал ЩИТ Монеты Безумия! Проигрыш {cb} отменен.")
        elif not is_shield and final_change > 0:
            final_change = 0
            effect_msgs.append(f"🌓 Сработала ПУСТОТА Монеты Безумия! Выигрыш {cb} отменен.")
        else:
            effect_msgs.append(f"🌓 Монета Безумия была использована, но ее эффект не пригодился.")
        effects_to_remove.append("madness_coin")

    update_query = {"$inc": {"balance": final_change}}
    if effects_to_remove:
        update_query["$pull"] = {"active_effects": {"$in": effects_to_remove}}
    await scores_col.update_one({'user_id': user_id}, update_query)
    new_balance = current_balance + final_change

    if base_change > 0:
        amulet_msg, new_balance = await handle_vampire_amulet(user_id, base_change, new_balance, game_name="спина")
        if amulet_msg:
            effect_msgs.append(amulet_msg)

    full_effect_message = " ".join(effect_msgs)
    if full_effect_message:
        await message.reply(f"{cost_msg}{full_effect_message} Итог: {final_change}. Баланс: {new_balance} 🎰")
    elif base_change >= 10:
        await message.reply(f"{cost_msg}Крупный выигрыш! +{base_change}. Баланс: {new_balance} 🎰")
    elif base_change > 0:
        await message.reply(f"{cost_msg}Держи +{base_change}. Баланс: {new_balance} 🎰")
    else:
        await message.reply(f"{cost_msg}Мимо. {base_change}. Баланс: {new_balance} 🎰")

@dp.message(lambda m: m.dice and m.dice.emoji == '⚽' and not m.from_user.is_bot)
async def handle_football(message: types.Message):
    casino_id = await get_casino_chat_id()
    if casino_id and message.chat.id != casino_id: return
    user_id = message.from_user.id
    gs = await game_state_col.find_one()
    if gs and gs.get("game_ended"):
        return
    if not gs or 'start_date' not in gs:
        return
    user_doc = await scores_col.find_one({"user_id": user_id})
    if not user_doc or "golden_boot_active" not in user_doc.get("active_effects", []):
        return

    dice_value = message.dice.value
    change = 10 if dice_value in (1, 4, 5) else -10

    await scores_col.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": change}, "$pull": {"active_effects": "golden_boot_active"}},
    )
    updated_user_doc = await scores_col.find_one({"user_id": user_id})
    new_balance = updated_user_doc['balance'] if updated_user_doc else 'N/A'
    effect_msg = ""

    if change > 0 and updated_user_doc:
        amulet_msg, new_balance = await handle_vampire_amulet(user_id, change, new_balance, updated_user_doc, "футбола")
        effect_msg = amulet_msg

    if change > 0:
        await message.reply(f"ГОООЛ! Вы забили и получаете +{change} фишек! Баланс: {new_balance}{effect_msg} ⚽️")
    else:
        await message.reply(f"Штанга! Вы промахнулись и теряете {abs(change)} фишек... Баланс: {new_balance} ⚽️")

@dp.message(Command("top"))
async def cmd_top(message: types.Message):
    casino_id = await get_casino_chat_id()
    if casino_id and message.chat.id != casino_id: return
    text = await get_leaderboard_text()
    await message.answer(text)

@dp.message(Command("day"))
async def cmd_day(message: types.Message):
    casino_id = await get_casino_chat_id()
    if casino_id and message.chat.id != casino_id: return
    gs = await game_state_col.find_one()
    if not gs or 'start_date' not in gs:
        await message.answer("🗓️ Сезон ещё не запущен. Ждите команды крупье!")
        return
    start_date = gs.get('start_date')
    now = datetime.datetime.now(pytz.timezone('Europe/Moscow')).replace(tzinfo=None)
    day_number = (now - start_date).days + 1
    if day_number > 14:
        await message.answer(f"🗓️ Игровой сезон (день {day_number}/14) уже должен был завершиться. Ждем финала!")
    else:
        await message.answer(f"🗓️ Идет {day_number}-й день из 14 игрового сезона.")

@dp.message(Command("hof"))
async def cmd_hof(message: types.Message, command: CommandObject):
    total = await hof_col.count_documents({})
    if total == 0:
        await message.answer("🏛 Зал славы пока пуст. Первый сезон ещё не завершён!")
        return
    if command.args and command.args.strip().isdigit():
        n = int(command.args.strip())
    else:
        n = total
    season = await hof_col.find_one({"season_number": n})
    if not season:
        await message.answer(f"🏛 Сезон №{n} не найден. Всего завершено сезонов: {total}")
        return
    players = season.get("top_players", [])
    text = f"🏛 Гемблинг Лига Башмака №{n}\n\n"
    for i, p in enumerate(players):
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i + 1}."
        text += f"{medal} {p['name']}: {p['balance']} фишек\n"
    await message.answer(text)
