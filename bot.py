
import os, asyncio, datetime, pytz, random
from collections import deque
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject
from aiogram.enums import ChatType
from aiogram.types import BotCommand, BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
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
    "black_mark": {"name": "💀 Чёрная метка", "description": "Удваивает следующий выигрыш или проигрыш цели.", "requires_target": True},
    "madness_coin": {"name": "🌓 Монета Безумия", "description": "50/50 шанс удвоить выигрыш цели или превратить его в убыток.", "requires_target": True},
    "money_pouch": {"name": "💰 Мешочек мелочи", "description": "Мгновенно дает +10 фишек.", "requires_target": False},
    "golden_boot": {"name": "⚽ Золотой Бутс", "description": "Запускает мини-игру с ударом по воротам.", "requires_target": False}
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
    
    if dice_value == 64: return 80
    elif all(is_bar(r) for r in reels): return 40
    elif reels[0] == reels[1] == reels[2]: return 15
    elif reels[0] == reels[1] or reels[1] == reels[2]: return 3
    else: return -2

# --- ПОМОЩНИКИ ---
async def download_video_rapid(url):
    if not RAPID_KEY: return None
    api_url = "https://social-download-all-in-one.p.rapidapi.com/v1/social/autolink"
    headers = {"Content-Type": "application/json", "x-rapidapi-host": "social-download-all-in-one.p.rapidapi.com", "x-rapidapi-key": RAPID_KEY}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(api_url, json={"url": url}, headers=headers, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    medias = data.get('medias', [])
                    if medias:
                        for m in medias:
                            if m.get('extension') == 'mp4': return m.get('url')
                        return medias[0].get('url')
        except: pass
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
    text = "🏆 **ЗАЛ СЛАВЫ КАЗИНО:**\n"
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
    await message.answer("💥 **КАЗИНО СОЖЖЕНО ДОТЛА!** 💥\nВсе ставки, инвентари и счетчики спинов обнулены.")
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
    await message.answer(f"Вы получили: **{ITEMS[item_key]['name']}**")

# 2. ИНВЕНТАРЬ И ПРЕДМЕТЫ
@dp.message(Command("inventory"))
async def cmd_inventory(message: types.Message):
    user_id = message.from_user.id
    inventory_doc = await inventories_col.find_one({"user_id": user_id})
    if not inventory_doc or not inventory_doc.get("items"):
        await message.answer("🎒 **Ваш инвентарь пуст.**\n\n_Делайте ставки или используйте /get_item, чтобы получить свой первый предмет!_ 🎰")
        return

    text = "🎒 **ВАШ ИНВЕНТАРЬ**\n\n"
    item_counts = {item_key: inventory_doc["items"].count(item_key) for item_key in set(inventory_doc["items"])}
    
    for item_key, count in sorted(item_counts.items()):
        item = ITEMS[item_key]
        text += f"**{item['name']}** (x{count})\n_{item['description']}_\n\n"

    buttons = []
    for item_key in sorted(item_counts.keys()):
        item = ITEMS[item_key]
        buttons.append([InlineKeyboardButton(text=f"Использовать {item['name']}", switch_inline_query_current_chat=f"/use {item_key} ")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard)

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
    await message.answer(f"Вы потратили {cost} фишек и получили: **{ITEMS[item_key]['name']}**!\nВаш новый баланс: {new_balance} фишек. 🎰")

@dp.message(Command("use"))
async def cmd_use(message: types.Message, command: CommandObject):
    user_id = message.from_user.id

    if command.args is None:
        await message.reply("Напишите предмет, который хотите использовать, например: `/use money_pouch`")
        return

    item_key = command.args.strip().lower()

    if item_key not in ITEMS:
        await message.reply(f"Неверный предмет. Доступные: { ', '.join(ITEMS.keys()) }")
        return

    inventory_doc = await inventories_col.find_one({"user_id": user_id, "items": item_key})
    if not inventory_doc:
        await message.reply("У вас нет такого предмета. 😕")
        return

    item = ITEMS[item_key]

    if item["requires_target"]:
        if not message.reply_to_message:
            await message.reply(f"Чтобы использовать **{item['name']}**, ответьте на сообщение цели.")
            return
        target_user = message.reply_to_message.from_user
        if target_user.id == user_id:
            await message.reply("Нельзя использовать это на себя! 🎰")
            return
        
        bot_user = await bot.get_me()
        if target_user.is_bot and target_user.id != bot_user.id:
            await message.reply("Боты невосприимчивы к магии предметов (кроме меня, конечно). 🤖")
            return

        target_id = target_user.id
        target_name = target_user.first_name
        
        await inventories_col.update_one({"user_id": user_id}, {"$pull": {"items": item_key}})
        await scores_col.update_one({"user_id": target_id},{"$addToSet": {"active_effects": item_key}},upsert=True)
        await scores_col.update_one({"user_id": target_id}, {"$setOnInsert": {"name": target_name, "balance": 100}}, upsert=True)

        await message.answer(f"{message.from_user.first_name} использовал **{item['name']}** на игрока {target_name}! 😈")
        return

    # --- PREDMETY BEZ CELI ---
    await inventories_col.update_one({"user_id": user_id}, {"$pull": {"items": item_key}}) # General pull for non-target items

    if item_key == "money_pouch":
        await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": 10}})
        user_doc = await scores_col.find_one({"user_id": user_id})
        await message.reply(f"💰 Вы использовали **Мешочек мелочи** и получили +10 фишек! Ваш баланс: {user_doc['balance']}")

    elif item_key == "golden_boot":
        await message.reply("⚽️ Вы использовали **Золотой Бутс**! Теперь кидайте эмодзи ⚽, чтобы ударить по воротам.")

    elif item_key == "chaos_cube":
        bot_user = await bot.get_me()
        all_players_cursor = scores_col.find({"user_id": {"$nin": [user_id, bot_user.id]}}, {"user_id": 1, "name": 1})
        all_players = await all_players_cursor.to_list(length=None)
        if not all_players:
            await message.reply("В казино больше нет игроков, чтобы стать жертвой хаоса. 🎲")
            # Return the item if no victims
            await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": item_key}})
            return
        
        victim = random.choice(all_players)
        victim_id = victim['user_id']
        victim_name = victim['name']
        roll = random.randint(1, 6)
        
        await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": roll}})
        await scores_col.update_one({"user_id": victim_id}, {"$inc": {"balance": -roll}})

        user_doc = await scores_col.find_one({"user_id": user_id})
        victim_doc = await scores_col.find_one({"user_id": victim_id})

        await message.answer(f"🎲 **Кубик Хаоса** в действии!\nВы выбросили {roll}. {roll} фишек переходят от игрока {victim_name} к вам.\nВаш баланс: {user_doc['balance']}\nБаланс {victim_name}: {victim_doc['balance'] if victim_doc else 'N/A'}")

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
        await scores_col.insert_one({
            "user_id": user_id, "name": user_name, "balance": start_balance, "active_effects": []
        })
        user_doc = await scores_col.find_one({'user_id': user_id})

    spin_count_doc = await spin_counts_col.find_one({'user_id': user_id})
    spin_count = spin_count_doc.get('count', 0) if spin_count_doc else 0
    current_spin_number = spin_count + 1

    if current_spin_number > 5:
        await message.reply("На сегодня твои попытки в казино закончились! Возвращайся завтра. 🎰")
        return

    costs = {3: 5, 4: 12, 5: 20}
    entry_cost = costs.get(current_spin_number, 0)
    current_balance = user_doc.get('balance', 0)

    if current_balance < entry_cost:
        await message.reply(f"Недостаточно фишек для {current_spin_number}-го спина! Нужно {entry_cost}, а у тебя {current_balance}. 😕")
        return
        
    if entry_cost > 0:
        await scores_col.update_one({'user_id': user_id}, {'$inc': {'balance': -entry_cost}})
        current_balance -= entry_cost

    if is_new_user and current_spin_number == 1:
        await message.answer(
            "🎰 **Добро пожаловать в Казино!** 🎰\n\n"
            "Делайте ставки, срывайте джекпот и соревнуйтесь! У вас 5 попыток в день.\n\n"
            "- **Спины 1-2:** Бесплатно\n- **Спин 3:** -5 фишек\n- **Спин 4:** -12 фишек\n- **Спин 5 (Тёмное Казино):** -20 фишек, высокий риск!\n\n"
            "Используйте `/get_item`, чтобы купить предметы. Проверяйте `/inventory`.\n\n"
            "Ваш стартовый капитал: 100 фишек. Желаю удачи! 😼"
        )

    await spin_counts_col.update_one({'user_id': user_id},{'$inc': {'count': 1}},upsert=True)

    if current_spin_number == 5:
        await message.answer(f"За вход в **ТЁМНОЕ КАЗИНО** списано {entry_cost} фишек... 😈")
        await asyncio.sleep(1)

        outcome = random.choice(['nothing', 'chips', 'items'])

        if outcome == 'nothing':
            await message.reply(f"💨 **ПУСТОТА!** 💨\nТьма поглотила твою ставку. Ты не получаешь ничего.\nТвой баланс: {current_balance} фишек. 🎰")

        elif outcome == 'chips':
            await scores_col.update_one({'user_id': user_id}, {'$inc': {'balance': 50}})
            new_balance = current_balance + 50
            await message.reply(f"🎉 **УСПЕХ!** 🎉\nТы обыграл тьму и получаешь **+50 фишек**! Твой новый баланс: {new_balance}. ✨")

        elif outcome == 'items':
            items_to_give = [random.choice(list(ITEMS.keys())) for _ in range(3)]
            await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": {"$each": items_to_give}}}, upsert=True)
            
            item_names = [ITEMS[key]['name'] for key in items_to_give]
            items_text = "\n".join(f"- **{name}**" for name in item_names)
            
            await message.reply(f"🎉 **ДЖЕКПОТ!** 🎉\nТьма дарует тебе сокровища! Ты получил 3 предмета:\n{items_text}\n\nЗагляни в /inventory! 🎁")
        return

    cost_msg = f"(Спин {current_spin_number}/5) "
    if entry_cost > 0: cost_msg += f"(-{entry_cost} фишек) "

    change = calculate_win(message.dice.value)
    final_change = change
    
    active_effects = user_doc.get('active_effects', [])
    effects_to_remove = []
    if "black_mark" in active_effects:
        final_change *= 2
        effects_to_remove.append("black_mark")
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
        await message.reply(f"{cost_msg}На вас сработал эффект! {change} -> **{final_change}**! Баланс: {new_balance} 🎰")
    else:
        if change >= 15: await message.reply(f"{cost_msg}Крупный выигрыш! +{change}. Баланс: {new_balance} 🎰")
        elif change > 0: await message.reply(f"{cost_msg}Держи +{change}. Баланс: {new_balance} 🎰")
        else: await message.reply(f"{cost_msg}Мимо. {change}. Баланс: {new_balance} 🎰")

@dp.message(lambda m: m.dice and m.dice.emoji == '⚽' and not m.from_user.is_bot)
async def handle_football(message: types.Message):
    user_id = message.from_user.id
    dice_value = message.dice.value
    if dice_value >= 4:
        change = 50
        await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": change}}, upsert=True)
        user_doc = await scores_col.find_one({"user_id": user_id})
        await message.reply(f"ГОООЛ! Вы забили и получаете +{change} фишек! Ваш баланс: {user_doc['balance']} ⚽️")
    else:
        change = -25
        await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": change}}, upsert=True)
        user_doc = await scores_col.find_one({"user_id": user_id})
        await message.reply(f"Штанга! Вы промахнулись и теряете {abs(change)} фишек... Ваш баланс: {user_doc['balance']} ⚽️")

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
        await bot.send_message(chat_id, f"🎰 **Ставки не делались, день прошел впустую.**")
        return

    clean = [m for m in list(history) if not m['content'].startswith('/')]
    top_text = await get_leaderboard_text()
    
    if not clean:
        await bot.send_message(chat_id, f"🎰 **Ставки не делались, день прошел впустую.**\n\n{top_text}")
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
    await bot.send_message(chat_id, f"💰 **ИТОГИ ИГРОВОГО ДНЯ:**\n{res} 🎰")

@dp.message()
async def handle_message(message: types.Message):
    # Ignore commands, bots, and dice messages in this handler
    if message.from_user.is_bot or not message.text or message.text.startswith('/') or (message.dice and message.dice.emoji in ['🎰', '⚽']):
        return
    cid = message.chat.id
    history = get_history(cid)
    
    if any(x in message.text for x in ["instagram.com/", "tiktok.com/", "youtube.com/shorts", "youtu.be/"]):
        await bot.send_chat_action(cid, "upload_video")
        v_url = await download_video_rapid(message.text)
        if v_url:
            async with aiohttp.ClientSession() as s:
                async with s.get(v_url) as r:
                    if r.status == 200:
                        await message.reply_video(BufferedInputFile(await r.read(), filename="v.mp4"), caption="😼 Стырил")
                        return

    history.append({"role": "user", "name": message.from_user.first_name, "content": message.text})
    try: 
        await scores_col.update_one({"user_id": message.from_user.id}, {"$set": {"name": message.from_user.first_name}}, upsert=False)
    except: pass

    bot_obj = await bot.get_me()
    is_named = bot_obj.username.lower() in message.text.lower()
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

# --- ПЛАНИРОВЩИК ---
async def reset_daily_state():
    await spin_counts_col.delete_many({})
    print(f"[{datetime.datetime.now()}] Daily spin counts have been reset.")

async def scheduler():
    while True:
        now = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
        if now.hour == 0 and now.minute == 0:
            await reset_daily_state()
            for cid in user_history:
                user_history[cid].clear()
            await asyncio.sleep(61)

        if now.hour == 22 and now.minute == 0:
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
    
    asyncio.create_task(scheduler())
    await bot.delete_webhook(drop_pending_updates=True)
    
    me = await bot.get_me()
    # Set bot username for later use, e.g. in message handlers
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
