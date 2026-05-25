
import os, asyncio, datetime, pytz, random, re
from collections import deque
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject
from aiogram.enums import ChatType
from aiogram.types import BotCommand, BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from groq import AsyncGroq
import aiohttp
from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient

# --- КОНФИГ ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
RAPID_KEY = os.getenv("RAPIDAPI_KEY")
MONGO_URL = os.getenv("MONGO_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# Инициализация
bot = Bot(token=TOKEN)
dp = Dispatcher()
if GROQ_API_KEY:
    client = AsyncGroq(api_key=GROQ_API_KEY)
else:
    client = None

# --- ПОДКЛЮЧЕНИЕ К БД ---
mongo_client = AsyncIOMotorClient(MONGO_URL, tlsAllowInvalidCertificates=True)
db = mongo_client['bashmak_db']
scores_col = db['scores']
inventories_col = db['inventories']
spin_counts_col = db['spin_counts']

# --- ПРЕДМЕТЫ ---
ITEMS = {
    "chaos_cube": {"name": "🎲 Кубик Хаоса", "description": "Вычитает случайное число (1-6) у случайного игрока и добавляет вам.", "requires_target": False},
    "madness_coin": {"name": "🌓 Монета Безумия", "description": "50/50 шанс удвоить ваш следующий выигрыш или превратить его в убыток.", "requires_target": False},
    "money_pouch": {"name": "💰 Мешочек мелочи", "description": "Мгновенно дает +10 фишек.", "requires_target": False},
    "golden_boot": {"name": "⚽ Золотой Бутс", "description": "Запускает мини-игру с ударом по воротам.", "requires_target": False},
    "stone_rain": {"name": "🌧️ Дождь из камней", "description": "Изменяет баланс фишек всех игроков на случайное значение от -5 до 5.", "requires_target": False},
    "leaky_pocket": {"name": "🤏 Дырявый карман", "description": "Попытка украсть 15% фишек у самого богатого игрока. С шансом 30% вы отдадите 15% своих фишек ему.", "requires_target": False}
}

user_history = {}

def get_history(chat_id):
    if chat_id not in user_history:
        user_history[chat_id] = deque(maxlen=100)
    return user_history[chat_id]

# --- РОЛИ ---
GAMBLING_SHOE_PROMPT = "Ты — Гемблинг Башмак, азартный и рисковый кот. Весь мир для тебя — казино. Говори об удаче, ставках, риске и джекпотах. Используй сленг казино (фишки, олл-ин, джекпот, ставка, спин) и всегда будь готов поставить всё на кон. Ты немного циничен и саркастичен."
ROLES = [{"name": "Гемблинг Башмак", "emoji": "🎰", "prompt": GAMBLING_SHOE_PROMPT}]

# --- PURE CALCULATION ---
def calculate_win(dice_value):
    v = dice_value - 1
    reels = [v % 4, (v // 4) % 4, v // 16]
    is_bar = lambda r: r == 1
    
    if dice_value == 64: return 50
    elif all(is_bar(r) for r in reels): return 20
    elif reels[0] == reels[1] == reels[2]: return 10
    elif reels[0] == reels[1] or reels[1] == reels[2]: return -1
    else: return -5

# --- ПОМОЩНИКИ ---
async def download_video_rapid(url):
    if not RAPID_KEY: return None
    api_url = "https://social-download-all-in-one.p.rapidapi.com/v1/social/autolink"
    headers = {"Content-Type": "application/json", "x-rapidapi-host": "social-download-all-in-one.p.rapidapi.com", "x-rapidapi-key": RAPID_KEY}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(api_url, json={"url": url}, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    medias = data.get('medias', [])
                    best_video = None
                    max_pixels = 0
                    if medias:
                        for m in medias:
                            if m.get('extension') == 'mp4' and m.get('quality'):
                                try:
                                    width = m.get('width', 0)
                                    height = m.get('height', 0)
                                    pixels = width * height
                                    if pixels > max_pixels:
                                        max_pixels = pixels
                                        best_video = {"url": m['url'], "width": width, "height": height}
                                except (KeyError, TypeError):
                                    continue
                        if not best_video and medias:
                            first_url = medias[0].get('url')
                            if first_url:
                                return {"url": first_url, "width": None, "height": None}
                    return best_video
        except Exception as e:
            print(f"Video download error: {e}")
    return None

async def ask_model(messages, temp=0.8):
    if not client: return "Башмак отдыхает."
    try:
        completion = await client.chat.completions.create(model="llama-3.3-70b-versatile", messages=messages, temperature=temp)
        return completion.choices[0].message.content
    except Exception as e: return f"Башмак сломался: {e}"

async def get_leaderboard_text():
    cursor = scores_col.find().sort("balance", -1).limit(10)
    players = await cursor.to_list(length=10)
    if not players: return "В казино пока нет хайроллеров..."
    text = "🏆 Зал славы казино:\n"
    for i, p in enumerate(players):
        medal = "🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else f"{i+1}."
        name = p.get('name', 'Anon')
        balance = p.get('balance', 0)
        text += f"{medal} {name}: {balance} фишек\n"
    return text

# --- ОБРАБОТЧИКИ ---

# 1. АДМИН-ПАНЕЛЬ
@dp.message(Command("admin_wipe_scores_777"))
async def cmd_admin_wipe(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await scores_col.drop()
    await inventories_col.drop()
    await spin_counts_col.drop()
    await message.answer("💥 Казино сожжено дотла! 💥\nВсе ставки, инвентари и счетчики спинов обнулены.")
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

# 2. ИНВЕНТАРЬ И ПРЕДМЕТЫ
@dp.message(Command("inventory"))
async def cmd_inventory(message: types.Message):
    user_id = message.from_user.id
    inventory_doc = await inventories_col.find_one({"user_id": user_id})
    if not inventory_doc or not inventory_doc.get("items"):
        await message.answer("🎒 Ваш инвентарь пуст.\n\nДелайте ставки или используйте /get_item, чтобы получить свой первый предмет! 🎰")
        return

    text = "🎒 Ваш инвентарь:\n\n"
    item_counts = {item_key: inventory_doc["items"].count(item_key) for item_key in set(inventory_doc["items"])}
    
    buttons = []
    for item_key, count in sorted(item_counts.items()):
        item = ITEMS[item_key]
        text += f"{item['name']} (x{count})\nОписание: {item['description']}\n\n"
        buttons.append([InlineKeyboardButton(text=f"Использовать {item['name']}", callback_data=f"use_item:{item_key}")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard, parse_mode=None)

@dp.callback_query(lambda c: c.data and c.data.startswith("use_item:"))
async def process_use_item_callback(callback_query: CallbackQuery):
    item_key = callback_query.data.split(":")[1]
    await callback_query.answer(f"Используем {ITEMS[item_key]['name']}...")
    await use_item_logic(callback_query.from_user, item_key, callback_query.message)

@dp.message(Command("get_item"))
async def cmd_get_item(message: types.Message):
    user_id = message.from_user.id
    cost = 10
    user_doc = await scores_col.find_one({"user_id": user_id})

    if not user_doc:
        await message.reply("Вы еще не играли в казино! Сделайте ставку, чтобы начать. 🎰")
        return

    if user_doc.get('balance', 0) < cost:
        await message.reply(f"Недостаточно фишек для покупки случайного предмета. Стоимость: {cost} фишек. 🎰")
        return

    await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": -cost}})
    item_key = random.choice(list(ITEMS.keys()))
    await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": item_key}}, upsert=True)
    
    updated_user_doc = await scores_col.find_one({"user_id": user_id})
    new_balance = updated_user_doc['balance']
    await message.answer(f"Вы потратили {cost} фишек и получили: {ITEMS[item_key]['name']}!\nВаш новый баланс: {new_balance} фишек. 🎰")

async def use_item_logic(user: types.User, item_key: str, context_message: types.Message, original_message: types.Message = None):
    user_id = user.id
    user_name = user.first_name

    if item_key not in ITEMS:
        await context_message.answer(f"Неверный предмет. Доступные: { ', '.join(ITEMS.keys()) }")
        return

    inventory_doc = await inventories_col.find_one({"user_id": user_id})
    if not inventory_doc or item_key not in inventory_doc.get("items", []):
        await context_message.answer("У вас нет такого предмета. 😕")
        return

    current_items = inventory_doc.get("items", [])
    current_items.remove(item_key)
    await inventories_col.update_one({"user_id": user_id}, {"$set": {"items": current_items}})

    item = ITEMS[item_key]

    if item["requires_target"]:
        if not original_message or not original_message.reply_to_message:
            await context_message.answer(f"Чтобы использовать {item['name']}, ответьте на сообщение цели.")
            await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": item_key}})
            return
        target_user = original_message.reply_to_message.from_user
        if target_user.id == user_id:
            await context_message.answer("Нельзя использовать это на себя! 🎰")
            await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": item_key}})
            return
        
        bot_user = await bot.get_me()
        if target_user.is_bot and target_user.id != bot_user.id:
            await context_message.answer("Боты невосприимчивы к магии предметов (кроме меня, конечно). 🤖")
            await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": item_key}})
            return

        target_id = target_user.id
        target_name = target_user.first_name
        
        await scores_col.update_one({"user_id": target_id}, {"$addToSet": {"active_effects": item_key}}, upsert=True)
        await scores_col.update_one({"user_id": target_id}, {"$setOnInsert": {"name": target_name, "balance": 100}}, upsert=True)

        await context_message.answer(f"{user_name} использовал {item['name']} на игрока {target_name}! 😈")
        return

    if item_key == "money_pouch":
        await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": 10}}, upsert=True)
        user_doc = await scores_col.find_one({"user_id": user_id})
        new_balance = user_doc.get("balance", 10)
        await context_message.answer(f"💰 Вы использовали Мешочек мелочи и получили +10 фишек! Ваш баланс: {new_balance}")

    elif item_key == "golden_boot":
        await scores_col.update_one({"user_id": user_id}, {"$addToSet": {"active_effects": "golden_boot_active"}}, upsert=True)
        await context_message.answer("⚽️ Вы использовали Золотой Бутс! Теперь кидайте эмодзи ⚽, чтобы ударить по воротам.")

    elif item_key == "chaos_cube":
        bot_user = await bot.get_me()
        all_players_cursor = scores_col.find({"user_id": {"$nin": [user_id, bot_user.id]}}, {"user_id": 1, "name": 1})
        all_players = await all_players_cursor.to_list(length=None)
        
        if not all_players:
            await context_message.answer("В казино больше нет игроков, чтобы стать жертвой хаоса. 🎲")
            await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": item_key}})
            return
        
        victim = random.choice(all_players)
        victim_id = victim['user_id']
        victim_name = victim['name']
        roll = random.randint(1, 6)
        
        await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": roll}}, upsert=True)
        await scores_col.update_one({"user_id": victim_id}, {"$inc": {"balance": -roll}}, upsert=True)

        user_doc = await scores_col.find_one({"user_id": user_id})
        victim_doc = await scores_col.find_one({"user_id": victim_id})

        await context_message.answer(f"🎲 Кубик Хаоса в действии!\nВы выбросили {roll}. {roll} фишек переходят от игрока {victim_name} к вам.\nВаш баланс: {user_doc['balance']}\nБаланс {victim_name}: {victim_doc['balance'] if victim_doc else 'N/A'}")

    elif item_key == "madness_coin":
        await scores_col.update_one({"user_id": user_id}, {"$addToSet": {"active_effects": "madness_coin"}}, upsert=True)
        await context_message.answer("🌓 Вы использовали Монету Безумия! Ваш следующий спин определит судьбу. Удачи... или нет. 😈")
    
    elif item_key == "stone_rain":
        all_players_cursor = scores_col.find({}, {"user_id": 1, "name": 1})
        all_players = await all_players_cursor.to_list(length=None)
        
        if not all_players:
            await context_message.answer("В казино нет игроков, чтобы устроить апокалипсис. 🌧️")
            await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": item_key}})
            return

        update_summary = []
        bot_user = await bot.get_me()
        for player in all_players:
            player_id = player['user_id']
            player_name = player.get('name', 'Неизвестный игрок')
            change = random.randint(-5, 5)
            
            await scores_col.update_one({"user_id": player_id}, {"$inc": {"balance": change}})
            
            if player_id == bot_user.id:
                player_name = "Гемблинг Башмак"

            sign = "+" if change >= 0 else ""
            update_summary.append(f"{player_name}: {sign}{change}")

        summary_message = "🌧️ Начался дождь из камней! 🌧️\nФишки всех игроков изменились:\n" + "\n".join(update_summary)
        await context_message.answer(summary_message)
    
    elif item_key == "leaky_pocket":
        all_players_sorted = await scores_col.find({}).sort("balance", -1).to_list(length=2)

        user_is_top_or_only_player = not all_players_sorted or (len(all_players_sorted) == 1 and all_players_sorted[0]['user_id'] == user_id)
        
        if user_is_top_or_only_player:
            await context_message.answer("В казино больше некого обчищать. Либо вы топ-1, либо единственный игрок. 🤏")
            await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": item_key}})
            return

        top_player = all_players_sorted[0] if all_players_sorted[0]['user_id'] != user_id else all_players_sorted[1]
        
        top_player_id = top_player['user_id']
        top_player_name = top_player.get('name', 'Anon')
        user_doc = await scores_col.find_one({"user_id": user_id})

        if random.random() < 0.3:
            amount = int(user_doc.get('balance', 0) * 0.15)
            if amount <= 0:
                await context_message.answer(f"Вы попытались обокрасть {top_player_name}, но вас поймали! К счастью, у вас и красть нечего. Вы ничего не потеряли. 💨")
                return

            await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": -amount}})
            await scores_col.update_one({"user_id": top_player_id}, {"$inc": {"balance": amount}})
            
            user_doc_new = await scores_col.find_one({"user_id": user_id})
            top_player_new = await scores_col.find_one({"user_id": top_player_id})

            await context_message.answer(
                f"🤏 Карма оказалась быстрой! Вас поймали за руку, и вы отдали {amount} фишек игроку {top_player_name} в качестве компенсации.\n\n"
                f"Ваш баланс: {user_doc_new.get('balance', 'N/A')}\n"
                f"Баланс {top_player_name}: {top_player_new.get('balance', 'N/A')}"
            )
        else:
            amount = int(top_player.get('balance', 0) * 0.15)
            if amount <= 0:
                await context_message.answer(f"Вы попытались обокрасть {top_player_name}, но у него в карманах ветер свищет! Ничего не вышло. 💨")
                return
            
            await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": amount}})
            await scores_col.update_one({"user_id": top_player_id}, {"$inc": {"balance": -amount}})

            user_doc_new = await scores_col.find_one({"user_id": user_id})
            top_player_new = await scores_col.find_one({"user_id": top_player_id})

            await context_message.answer(
                f"🤏 Удачная вылазка! Вы использовали «Дырявый карман» и стащили {amount} фишек у хайроллера {top_player_name}!\n\n"
                f"Ваш баланс: {user_doc_new.get('balance', 'N/A')}\n"
                f"Баланс {top_player_name}: {top_player_new.get('balance', 'N/A')}"
            )

@dp.message(Command("use"))
async def cmd_use(message: types.Message, command: CommandObject):
    if command.args is None:
        await message.reply("Напишите предмет, который хотите использовать, например: `/use money_pouch`")
        return
    item_key = command.args.strip().lower()
    await use_item_logic(message.from_user, item_key, message, original_message=message)

# 3. КАЗИНО
@dp.message(lambda m: m.dice and m.dice.emoji == '🎰' and not m.from_user.is_bot)
async def handle_dice(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name

    user_doc = await scores_col.find_one({'user_id': user_id})
    is_new_user = False
    if not user_doc:
        is_new_user = True
        start_balance = 100
        # Give a random item to the new user
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
        starter_item_doc = await inventories_col.find_one({"user_id": user_id})
        starter_item_key = starter_item_doc['items'][0]
        starter_item_name = ITEMS[starter_item_key]['name']
        item_descriptions = "\n".join([f"- {item['name']}: {item['description']}" for item in ITEMS.values()])
        
        welcome_text = f'''😼 Добро пожаловать в подпольное казино «Гемблинг Башмак»!

Здесь удача улыбается смелым, а риск — второе имя. Твоя цель — сорвать куш, подняться в таблице лидеров (/top) и стать легендой этого заведения.

Ты начинаешь со 100 фишками и стартовым бонусом: тебе достался предмет «{starter_item_name}»! Проверь его в /inventory.

---

🎲 ПРАВИЛА СПИНОВ

У тебя есть 2 бесплатные попытки в день. Каждая ставка может изменить всё. Используй их с умом!

---

🏆 ТАБЛИЦА ВЫИГРЫШЕЙ

- 7️⃣7️⃣7️⃣ (Джекпот): +50 фишек
- BAR-BAR-BAR: +20 фишек
- Три одинаковых символа: +10 фишек
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

Да начнутся игры! Делай свою первую ставку. 🎰
'''
        await message.answer(welcome_text, parse_mode=None)

    await spin_counts_col.update_one({'user_id': user_id},{'$inc': {'count': 1}},upsert=True)

    cost_msg = f"(Спин {current_spin_number}/2) "

    change = calculate_win(message.dice.value)
    final_change = change
    
    active_effects = user_doc.get('active_effects', [])
    effects_to_remove = []
    if "madness_coin" in active_effects:
        if random.random() < 0.5: final_change *= 2
        else: final_change *= -2
        effects_to_remove.append("madness_coin")
        
    update_query = {"$inc": {"balance": final_change}}
    if effects_to_remove:
        update_query["$pull"] = {"active_effects": {"$in": effects_to_remove}}
    await scores_col.update_one({'user_id': user_id}, update_query)
    
    new_balance = current_balance + final_change

    if effects_to_remove:
        await message.reply(f"{cost_msg}На вас сработал эффект! {change} -> {final_change}! Баланс: {new_balance} 🎰")
    else:
        if change >= 10: await message.reply(f"{cost_msg}Крупный выигрыш! +{change}. Баланс: {new_balance} 🎰")
        elif change > 0: await message.reply(f"{cost_msg}Держи +{change}. Баланс: {new_balance} 🎰")
        else: await message.reply(f"{cost_msg}Мимо. {change}. Баланс: {new_balance} 🎰")

@dp.message(lambda m: m.dice and m.dice.emoji == '⚽' and not m.from_user.is_bot)
async def handle_football(message: types.Message):
    user_id = message.from_user.id
    user_doc = await scores_col.find_one({"user_id": user_id})

    if not user_doc or "golden_boot_active" not in user_doc.get("active_effects", []):
        return

    dice_value = message.dice.value
    change = 10 if dice_value >= 4 else -10

    await scores_col.update_one(
        {"user_id": user_id},
        {
            "$inc": {"balance": change},
            "$pull": {"active_effects": "golden_boot_active"}
        }
    )

    updated_user_doc = await scores_col.find_one({"user_id": user_id})
    new_balance = updated_user_doc['balance'] if updated_user_doc else 'N/A'

    if change > 0:
        await message.reply(f"ГОООЛ! Вы забили и получаете +{change} фишек! Ваш баланс: {new_balance} ⚽️")
    else:
        await message.reply(f"Штанга! Вы промахнулись и теряете {abs(change)} фишек... Ваш баланс: {new_balance} ⚽️")

@dp.message(Command("top"))
async def cmd_top(message: types.Message):
    text = await get_leaderboard_text()
    await message.answer(text)

@dp.message(Command("summary"))
async def cmd_summary(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await send_gambling_summary(message.chat.id)

async def send_gambling_summary(chat_id):
    history = get_history(chat_id)
    if not history: 
        await bot.send_message(chat_id, f"🎰 Ставки не делались, день прошел впустую.")
        return

    clean = [m for m in list(history) if not m['content'].startswith('/')]
    top_text = await get_leaderboard_text()
    
    if not clean:
        await bot.send_message(chat_id, f"🎰 Ставки не делались, день прошел впустую.\n\n{top_text}")
        return

    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean])
    prompt = (f"{GAMBLING_SHOE_PROMPT} "
              "Подведи итоги прошедшего дня в чате, используя свою личность. "
              "Представь, что сообщения в чате — это ставки и события за игровым столом. "
              "Обязательно упомяни таблицу лидеров казино. "
              "ВАЖНО: Напиши 3-5 предложений, не больше и не меньше. "
              f"Вот переписка:\n{text_dump}\n\nА вот зал славы казино:\n{top_text}"
             )
    
    res = await ask_model([{"role": "user", "content": prompt}], temp=1.0)
    await bot.send_message(chat_id, f"💰 Итоги игрового дня:\n{res} 🎰")


@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.is_bot or not message.text or message.text.startswith('/') or (message.dice and message.dice.emoji in ['🎰', '⚽']):
        return
    cid = message.chat.id
    history = get_history(cid)
    text = message.text
    
    # Ищем первую попавшуюся ссылку в сообщении
    url_pattern = r'https?://[^\s]+'
    found_urls = re.findall(url_pattern, text)
    url_to_download = None
    if found_urls:
        url_to_download = found_urls[0]

    is_video_link = False
    if url_to_download and ("instagram.com/" in url_to_download or "tiktok.com/" in url_to_download or "youtube.com/" in url_to_download or "youtu.be/" in url_to_download):
        is_video_link = True

    if is_video_link:
        await bot.send_chat_action(cid, "upload_video")
        # Не преобразуем URL, передаем как есть
        video_info = await download_video_rapid(url_to_download)
        if video_info:
            v_url = video_info['url']
            width = video_info.get('width')
            height = video_info.get('height')
            
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(v_url) as r:
                        if r.status == 200:
                            video_content = await r.read()
                            if len(video_content) < 50 * 1024 * 1024:
                                await message.reply_video(
                                    BufferedInputFile(video_content, filename="v.mp4"), 
                                    caption="😼 Стырил",
                                    width=width, 
                                    height=height
                                )
                            else:
                                await message.reply("Видео слишком большое для отправки. 😼")
                        else:
                             await message.reply("Не удалось загрузить видео, которое вернул API. 😼")
            except Exception as e:
                 print(f"Error sending video: {e}")
                 await message.reply("Произошла ошибка при отправке видео. 😼")
        else:
            await message.reply("Не удалось скачать это видео. Либо ссылка битая, либо оно защищено. 😼")
        return # Stop processing after attempting to download

    history.append({"role": "user", "name": message.from_user.first_name, "content": text})
    try: 
        await scores_col.update_one({"user_id": message.from_user.id}, {"$set": {"name": message.from_user.first_name}}, upsert=False)
    except: pass

    bot_obj = await bot.get_me()
    is_named = bot_obj.username.lower() in text.lower()
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_obj.id
    
    if not (message.chat.type == ChatType.PRIVATE or is_named or is_reply or random.random() < 0.05): return

    selected_role = ROLES[0]
    msgs = [{"role": "system", "content": f"{selected_role['prompt']} Отвечай кратко. В конце: {selected_role['emoji']}"}]
    
    relevant_history = [m for m in list(history) if m['content'] and not m['content'].startswith('/')][-12:]
    for m in relevant_history:
        msgs.append({"role": "user", 'content': f'{m["name"]}: {m["content"]}'})

    await bot.send_chat_action(cid, "typing")
    reply = await ask_model(msgs)
    if reply and selected_role['emoji'] not in reply: 
        reply += f" {selected_role['emoji']}"
    await message.reply(reply)

# --- АВТО-СПИНЫ БОТА ---

bot_spin_time_1 = None
bot_spin_time_2 = None

def schedule_bot_spins():
    global bot_spin_time_1, bot_spin_time_2
    hour1 = random.randint(9, 12)
    minute1 = random.randint(0, 59)
    bot_spin_time_1 = datetime.time(hour1, minute1)

    hour2 = random.randint(18, 21)
    minute2 = random.randint(0, 59)
    bot_spin_time_2 = datetime.time(hour2, minute2)

    print(f"[{datetime.datetime.now()}] Bot spins scheduled for {bot_spin_time_1.strftime('%H:%M')} and {bot_spin_time_2.strftime('%H:%M')} MSK")

async def execute_bot_spin():
    bot_user = await bot.get_me()
    
    spin_count_doc = await spin_counts_col.find_one({'user_id': bot_user.id})
    spin_count = spin_count_doc.get('count', 0) if spin_count_doc else 0
    if spin_count >= 2:
        print(f"[{datetime.datetime.now()}] Bot has already spun twice today.")
        return

    all_chat_ids = list(user_history.keys())
    if not all_chat_ids:
        print(f"[{datetime.datetime.now()}] No active chats for bot spin.")
        return

    dice_value = random.randint(1, 64)
    change = calculate_win(dice_value)

    await scores_col.update_one({"user_id": bot_user.id}, {"$inc": {"balance": change}}, upsert=True)
    await spin_counts_col.update_one({'user_id': bot_user.id}, {'$inc': {'count': 1}}, upsert=True)
    
    bot_doc = await scores_col.find_one({"user_id": bot_user.id})
    new_balance = bot_doc.get("balance", "N/A")

    result_text = ""
    if change >= 10: result_text = f"сорвал крупный куш в {change} фишек!"
    elif change > 0: result_text = f"выиграл {change} фишки."
    else: result_text = f"проиграл {abs(change)} фишек."

    message_text = (f"🎲 Гемблинг Башмак делает свой ход! 🎲\n\n"
                    f"Кот-крупье {result_text}\n"
                    f"Теперь его баланс: {new_balance} фишек. 😼")

    for cid in all_chat_ids:
        try:
            await bot.send_message(cid, message_text)
            await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Failed to send bot spin to chat {cid}: {e}")

async def execute_bot_item_use():
    bot_user = await bot.get_me()
    bot_id = bot_user.id
    print(f"[{datetime.datetime.now()}] Attempting to execute bot item use.")

    inventory_doc = await inventories_col.find_one({"user_id": bot_id})
    if not inventory_doc or not inventory_doc.get("items"):
        print(f"[{datetime.datetime.now()}] Bot has no items to use.")
        return

    non_target_items = ["chaos_cube", "money_pouch", "stone_rain"]
    
    available_items = [item for item in inventory_doc.get("items", []) if item in non_target_items]
    
    if not available_items:
        print(f"[{datetime.datetime.now()}] Bot has no non-target items to use.")
        return

    item_key_to_use = random.choice(available_items)
    item_info = ITEMS[item_key_to_use]
    
    current_items = inventory_doc.get("items", [])
    current_items.remove(item_key_to_use)
    await inventories_col.update_one({"user_id": bot_id}, {"$set": {"items": current_items}})

    announcement = ""
    
    if item_key_to_use == "money_pouch":
        await scores_col.update_one({"user_id": bot_id}, {"$inc": {"balance": 10}}, upsert=True)
        bot_doc = await scores_col.find_one({"user_id": bot_id})
        new_balance = bot_doc.get("balance", "N/A")
        announcement = (f"😼 Гемблинг Башмак использовал предмет! 😼\n\n"
                        f"Кот нашел {item_info['name']} и получил 10 фишек.\n"
                        f"Его баланс теперь: {new_balance} фишек. 🎰")

    elif item_key_to_use == "stone_rain":
        all_players_cursor = scores_col.find({}, {"user_id": 1, "name": 1})
        all_players = await all_players_cursor.to_list(length=None)
        
        update_summary = []
        if not all_players:
            announcement = (f"😼 Гемблинг Башмак использовал {item_info['name']}! 😼\n\n"
                            f"Но в казино пусто, и камни упали в тишине. Эффекта нет.")
        else:
            for player in all_players:
                player_id = player['user_id']
                player_name = player.get('name', 'Неизвестный игрок')
                change = random.randint(-5, 5)
                await scores_col.update_one({"user_id": player_id}, {"$inc": {"balance": change}})
                
                if player_id == bot_id: player_name = "Гемблинг Башмак"
                sign = "+" if change >= 0 else ""
                update_summary.append(f"{player_name}: {sign}{change}")
            
            summary_str = "\n".join(update_summary)
            announcement = (f"😼 Гемблинг Башмак использовал {item_info['name']}! 😼\n\n"
                            f"{item_info['description']}\n\n"
                            f"Результаты:\n{summary_str}")

    elif item_key_to_use == "chaos_cube":
        other_players_cursor = scores_col.find({"user_id": {"$ne": bot_id}}, {"user_id": 1, "name": 1})
        other_players = await other_players_cursor.to_list(length=None)
        
        if not other_players:
            announcement = (f"😼 Гемблинг Башмак попытался использовать {item_info['name']}... 😼\n\n"
                            f"Но в казино, кроме него, ни души. Кубик укатился в угол, не причинив вреда.")
        else:
            victim = random.choice(other_players)
            victim_id = victim['user_id']
            victim_name = victim['name']
            roll = random.randint(1, 6)
            
            await scores_col.update_one({"user_id": bot_id}, {"$inc": {"balance": roll}})
            await scores_col.update_one({"user_id": victim_id}, {"$inc": {"balance": -roll}})
            
            bot_doc = await scores_col.find_one({"user_id": bot_id})
            victim_doc = await scores_col.find_one({"user_id": victim_id})

            announcement = (f"😼 Гемблинг Башмак использовал {item_info['name']}! 😼\n\n"
                            f"Под раздачу попал {victim_name}! Башмак крадет у него {roll} фишек.\n"
                            f"Баланс Башмака: {bot_doc.get('balance', 'N/A')}\n"
                            f"Баланс {victim_name}: {victim_doc.get('balance', 'N/A')}")

    if announcement:
        all_chat_ids = list(user_history.keys())
        print(f"[{datetime.datetime.now()}] Announcing bot item use to chats: {all_chat_ids}")
        for cid in all_chat_ids:
            try:
                await bot.send_message(cid, announcement)
                await asyncio.sleep(0.2)
            except Exception as e:
                print(f"Failed to send bot item use announcement to chat {cid}: {e}")

async def distribute_daily_items_and_announce():
    all_players_cursor = scores_col.find({}, {"user_id": 1})
    all_players = await all_players_cursor.to_list(length=None)
    if not all_players:
        print(f"[{datetime.datetime.now()}] No players to distribute daily items to.")
        return

    for player in all_players:
        item_key = random.choice(list(ITEMS.keys()))
        await inventories_col.update_one(
            {"user_id": player['user_id']},
            {"$push": {"items": item_key}},
            upsert=True
        )

    all_chat_ids = list(user_history.keys())
    if not all_chat_ids:
        return

    message_text = (
        f"🎁 Ежедневный бонус! 🎁\n\n"
        f"В конце дня каждый игрок получает по одному случайному предмету!\n\n"
        f"Проверьте свой /inventory, чтобы узнать, что вам досталось! 🎰"
    )

    for cid in all_chat_ids:
        try:
            await bot.send_message(cid, message_text)
            await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Failed to send daily item bonus announcement to chat {cid}: {e}")

# --- ПЛАНИРОВЩИК ---
async def reset_daily_state():
    await spin_counts_col.delete_many({})
    schedule_bot_spins()
    print(f"[{datetime.datetime.now()}] Daily spin counts have been reset.")

async def scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))

        if now.hour == 0 and now.minute == 0:
            await reset_daily_state()
            for cid in user_history:
                user_history[cid].clear()
            await asyncio.sleep(61)
        
        if now.hour == 12 and now.minute == 0:
            print(f"[{datetime.datetime.now()}] Triggering bot item use.")
            await execute_bot_item_use()
            await asyncio.sleep(61)

        global bot_spin_time_1, bot_spin_time_2
        if bot_spin_time_1 and now.hour == bot_spin_time_1.hour and now.minute == bot_spin_time_1.minute:
            print(f"[{datetime.datetime.now()}] Triggering bot spin 1.")
            await execute_bot_spin()
            bot_spin_time_1 = None
            await asyncio.sleep(61)

        if bot_spin_time_2 and now.hour == bot_spin_time_2.hour and now.minute == bot_spin_time_2.minute:
            print(f"[{datetime.datetime.now()}] Triggering bot spin 2.")
            await execute_bot_spin()
            bot_spin_time_2 = None
            await asyncio.sleep(61)

        if now.hour == 22 and now.minute == 0:
            await distribute_daily_items_and_announce()
            all_chat_ids = list(user_history.keys())
            for cid in all_chat_ids:
                await send_gambling_summary(cid)
            await asyncio.sleep(61)

        await asyncio.sleep(30)

async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bashmak is alive"))
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8000)))
    await site.start()
    
    schedule_bot_spins()
    asyncio.create_task(scheduler())
    await bot.delete_webhook(drop_pending_updates=True)
    
    me = await bot.get_me()
    bot.username = me.username

    main_commands = [
        BotCommand(command="inventory", description="🎒 Открыть инвентарь"),
        BotCommand(command="top", description="🏆 Посмотреть таблицу лидеров"),
        BotCommand(command="get_item", description="🎲 Купить случайный предмет (10 фишек)")
    ]
    await bot.set_my_commands(main_commands)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
