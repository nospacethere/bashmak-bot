import os, asyncio, datetime, pytz, random, uuid
from collections import deque
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ChatType, ParseMode
from aiogram.types import BotCommand, BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from groq import AsyncGroq
import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
RAPID_KEY = os.getenv("RAPIDAPI_KEY")
MONGO_URL = os.getenv("MONGO_URL")
BOT_NAME = "Гемблшмак"
BOT_ID = 666

# --- INITIALIZATION ---
bot = Bot(token=TOKEN, parse_mode=ParseMode.MARKDOWN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# --- DATABASE ---
mongo_client = AsyncIOMotorClient(MONGO_URL, tlsAllowInvalidCertificates=True)
db = mongo_client['gambling_migration_db']
users_col = db['users']
state_col = db['gamble_state']

# --- ITEM CONFIG ---
ITEMS = {
    "chaos_cube": {"name": "🎲 Кубик Хаоса", "description": "Кинуть кубик (1-6) на случайного игрока. Результат отнимается у него и прибавляется вам."},
    "black_mark": {"name": "💀 Чёрная метка", "description": "Следующий спин цели удвоит свой результат (убыток x2, выигрыш x2)."},
    "madness_coin": {"name": "🌓 Монета Безумия", "description": "50/50: следующий спин цели будет x2 или x-2."},
    "small_pouch": {"name": "💰 Мешочек мелочи", "description": "Мгновенно дает +10 очков."},
    "golden_boot": {"name": "⚽ Золотой Бутс", "description": "Мини-игра 'Пенальти'. Гол = +50, Мимо = -25."},
}

# --- ROLES & HISTORY ---
ROLES = [
    {"name": "Стандарт", "emoji": "😼", "prompt": "Ты — Башмак, язвительный кот Данила. Сарказм, база, огромный патриот России."},
    # Other roles commented out as requested
]
user_history = {} 

def get_history(chat_id):
    if chat_id not in user_history: 
        user_history[chat_id] = deque(maxlen=100)
    return user_history[chat_id]

# --- HELPERS ---
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

async def get_user(user_id, name):
    user = await users_col.find_one({"id": user_id})
    if not user:
        season = await state_col.find_one({"active": True})
        if not season or (datetime.datetime.now(pytz.utc) - season.get('start_date', datetime.datetime.now(pytz.utc))).days >= 18:
            await users_col.delete_many({})
            await state_col.update_one({"active": True}, {"$set": {"start_date": datetime.datetime.now(pytz.utc)}}, upsert=True)
            
        user = {
            "id": user_id,
            "name": name,
            "balance": 100,
            "inventory": [],
            "daily_spins_count": 0,
            "today_start_balance": 100,
            "last_spin_day": 0,
            "active_effects": []
        }
        await users_col.insert_one(user)
    
    today = datetime.datetime.now().timetuple().tm_yday
    if user.get('last_spin_day', 0) != today:
        user['daily_spins_count'] = 0
        user['today_start_balance'] = user['balance']
        await users_col.update_one({"id": user_id}, {"$set": {
            "daily_spins_count": 0, 
            "today_start_balance": user['balance'],
            "last_spin_day": today
        }})
    return user

async def find_target_user(message):
    if message.reply_to_message:
        return await get_user(message.reply_to_message.from_user.id, message.reply_to_message.from_user.first_name)
    return None

async def broadcast(message_text):
    active_chats = list(user_history.keys())
    for chat_id in active_chats:
        try:
            await bot.send_message(chat_id, message_text)
        except Exception as e:
            print(f"Could not broadcast to {chat_id}: {e}")

# --- CASINO & ITEMS ---

@dp.message(Command("spin"))
async def cmd_spin(message: types.Message):
    user_id = message.from_user.id
    name = message.from_user.first_name
    user = await get_user(user_id, name)
    
    spin_costs = [0, 0, 5, 12, 20]
    spin_number = user['daily_spins_count']

    if spin_number >= 5:
        await message.reply("На сегодня хватит. Приходи завтра.")
        return

    cost = spin_costs[spin_number]
    if user['balance'] < cost:
        await message.reply(f"Недостаточно очков для спина. Нужно: {cost}, у тебя: {user['balance']}.")
        return

    await users_col.update_one({"id": user_id}, {"$inc": {"balance": -cost}})
    user['balance'] -= cost
    
    if spin_number == 4: # 5th Spin - DARK CASINO
        is_success = random.choice([True, False])
        if is_success:
            if random.choice([True, False]):
                await users_col.update_one({"id": user_id}, {"$inc": {"balance": 50}})
                await message.reply("ТЕМНОЕ КАЗИНО... УСПЕХ! +50 очков.")
            else:
                item_key = random.choice(list(ITEMS.keys()))
                item = {"id": str(uuid.uuid4()), "key": item_key}
                await users_col.update_one({"id": user_id}, {"$push": {"inventory": item}})
                await message.reply(f"ТЕМНОЕ КАЗИНО... УСПЕХ! Ты получил предмет: **{ITEMS[item_key]['name']}**")
        else:
            burned_item_info = ""
            if user['inventory']:
                burned_item = random.choice(user['inventory'])
                await users_col.update_one({"id": user_id}, {"$pull": {"inventory": {"id": burned_item['id']}}})
                burned_item_info = f"и сгорел предмет: **{ITEMS[burned_item['key']]['name']}**"

            await users_col.update_one({"id": user_id}, {"$set": {"balance": user['today_start_balance']}})
            await message.reply(f"ТЕМНОЕ КАЗИНО... КРАХ! Ты потерял все очки за сегодня {burned_item_info}.")
        
        await users_col.update_one({"id": user_id}, {"$inc": {"daily_spins_count": 1}})
        return

    dice = await message.answer_dice(emoji='🎰')
    v = dice.dice.value
    reels = [(v-1) % 4, ((v-1) // 4) % 4, (v-1) // 16]

    change = 0
    if v == 1: change = 80 # 777
    elif v == 64: change = 40 # BAR BAR BAR
    elif reels[0] == reels[1] == reels[2]: change = 15
    elif reels[0] == reels[1] or reels[1] == reels[2]: change = 3
    else: change = -2
    
    effect_text = ""
    active_effects = user.get("active_effects", [])
    if "black_mark" in active_effects:
        change *= 2
        effect_text += "\n💀 Сработала *Чёрная метка* (x2)!"
        await users_col.update_one({"id": user_id}, {"$pull": {"active_effects": "black_mark"}})
    if "madness_coin" in active_effects:
        multiplier = random.choice([2, -2])
        change *= multiplier
        effect_text += f"\n🌓 Сработала *Монета Безумия* (x{multiplier})!"
        await users_col.update_one({"id": user_id}, {"$pull": {"active_effects": "madness_coin"}})

    await users_col.update_one({"id": user_id}, {"$inc": {"balance": change, "daily_spins_count": 1}})
    
    await asyncio.sleep(2)
    result_text = f"Выпало: {change} очков. Твой баланс: {user['balance'] + change}{effect_text}"
    await message.reply(result_text)

@dp.message(Command("inventory"))
async def cmd_inventory(message: types.Message):
    user = await get_user(message.from_user.id, message.from_user.first_name)
    if not user['inventory']:
        await message.reply("Твой инвентарь пуст.")
        return

    keyboard_buttons = []
    for item in user['inventory']:
        item_name = ITEMS[item['key']]['name']
        keyboard_buttons.append([InlineKeyboardButton(text=f"{item_name}", switch_inline_query_current_chat=f"/use {item['id']}")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await message.reply("Твой инвентарь. Нажми на предмет, чтобы использовать:", reply_markup=keyboard)

@dp.message(Command("use"))
async def cmd_use(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.reply("Как использовать: `/use [id_предмета]` (можно ответить на сообщение цели).")
        return
    
    item_id = args[1]
    user = await get_user(message.from_user.id, message.from_user.first_name)
    
    item_to_use = next((item for item in user['inventory'] if item['id'] == item_id), None)
    if not item_to_use:
        await message.reply("У тебя нет такого предмета.")
        return

    item_key = item_to_use['key']

    await users_col.update_one({"id": user['id']}, {"$pull": {"inventory": {"id": item_id}}})
    await message.reply(f"Ты использовал **{ITEMS[item_key]['name']}**!")

    if item_key == "small_pouch":
        await users_col.update_one({"id": user['id']}, {"$inc": {"balance": 10}})
        await message.answer("Ты получил +10 очков.")

    elif item_key == "golden_boot":
        dice = await message.answer_dice(emoji='⚽')
        is_goal = dice.dice.value in [3, 4, 5]
        await asyncio.sleep(4)
        if is_goal:
            await users_col.update_one({"id": user['id']}, {"$inc": {"balance": 50}})
            await message.reply(f"ГООООЛ! +50 очков!")
        else:
            await users_col.update_one({"id": user['id']}, {"$inc": {"balance": -25}})
            await message.reply(f"МИМО! -25 очков.")

    elif item_key == "chaos_cube":
        all_users = await users_col.find({"id": {"$ne": user['id']}}).to_list(length=100)
        if not all_users:
            await message.answer("В казино больше никого нет, кубик сгорел впустую.")
            return
        
        victim_doc = random.choice(all_users)
        dice_roll = random.randint(1, 6)
        
        await users_col.update_one({"id": victim_doc['id']}, {"$inc": {"balance": -dice_roll}})
        await users_col.update_one({"id": user['id']}, {"$inc": {"balance": dice_roll}})
        
        await message.answer(f"🎲 Ты кинул кубик на **{victim_doc['name']}**. Выпало {dice_roll}!\nТы получаешь +{dice_roll}, а он(а) теряет -{dice_roll}.")
        try:
            await bot.send_message(victim_doc['id'], f"Ахтунг! **{user['name']}** использовал на тебе Кубик Хаоса и отнял у тебя {dice_roll} очков!")
        except: pass

    elif item_key in ["black_mark", "madness_coin"]:
        target_user = await find_target_user(message)
        if not target_user:
            await message.reply("Нужно ответить на сообщение игрока, на которого хочешь использовать предмет.")
            await users_col.update_one({"id": user['id']}, {"$push": {"inventory": item_to_use}})
            return
        
        await users_col.update_one({"id": target_user['id']}, {"$push": {"active_effects": item_key}})
        await message.answer(f"Предмет **{ITEMS[item_key]['name']}** применен на **{target_user['name']}**.")
        try:
            await bot.send_message(target_user['id'], f"На тебя применили **{ITEMS[item_key]['name']}**! Эффект сработает на следующем спине.")
        except: pass

# --- GAMBLSHMAK AI ---
async def gamblshmak_turn():
    if not user_history: return
    
    bot_user = await get_user(BOT_ID, BOT_NAME)
    await broadcast("Так, лудоманы, батя в здании. Время крутить!")
    
    num_spins = random.randint(1, 5)
    for i in range(num_spins):
        await asyncio.sleep(random.uniform(5, 15))
        
        spin_costs = [0, 0, 5, 12, 20]
        spin_number = bot_user.get('daily_spins_count', 0)
        if spin_number >= 5: break
            
        cost = spin_costs[spin_number]
        if bot_user['balance'] < cost: break
            
        await users_col.update_one({"id": BOT_ID}, {"$inc": {"balance": -cost, "daily_spins_count": 1}})
        bot_user['balance'] -= cost
        bot_user['daily_spins_count'] += 1
        
        change = random.choice([-2, -2, -2, 3, 3, 15, 40, 80])
        await users_col.update_one({"id": BOT_ID}, {"$inc": {"balance": change}})
        bot_user['balance'] += change
        
        msg = f"Изи +{change}! Я гений этой игры. (Спин {i+1})" if change > 0 else f"Сука, минус {abs(change)}... Ща отыграемся. (Спин {i+1})"
        await broadcast(msg)

    if bot_user['balance'] < bot_user.get('today_start_balance', bot_user['balance']):
        await asyncio.sleep(5)
        await broadcast("Так, я в минусе... Непорядок.")
        
        all_users = await users_col.find({"id": {"$ne": BOT_ID}}).to_list(length=100)
        if all_users:
            victim_doc = random.choice(all_users)
            dice_roll = random.randint(1, 6)
            await users_col.update_one({"id": victim_doc['id']}, {"$inc": {"balance": -dice_roll}})
            await users_col.update_one({"id": BOT_ID}, {"$inc": {"balance": dice_roll}})
            await broadcast(f"🎲 Использую Кубик Хаоса на **{victim_doc['name']}**. Выпало {dice_roll}! Мне +{dice_roll}, лоху -{dice_roll}. А нехуй.")

async def daily_summary():
    if not user_history: return

    pipeline = [
        {"$project": {
            "id": "$id",
            "name": "$name",
            "balance": "$balance",
            "daily_loss": {"$subtract": ["$today_start_balance", "$balance"]}
        }},
        {"$sort": {"balance": -1}}
    ]
    all_users = await users_col.aggregate(pipeline).to_list(length=None)
    if not all_users: return

    loser_of_the_day = max(all_users, key=lambda x: x.get('daily_loss', 0))
    
    top_text = "🏆 **ИТОГИ ДНЯ** 🏆\n\n**Топ-5 игроков:**\n"
    for i, p in enumerate(all_users[:5]):
        top_text += f"{i+1}. {p['name']}: {p['balance']} очков\n"
        
    if loser_of_the_day and loser_of_the_day.get('daily_loss', 0) > 0:
        top_text += f"\n**Лох дня**: {loser_of_the_day['name']} (слил(а) {loser_of_the_day['daily_loss']} очков)\n"
    
    bot_user = next((u for u in all_users if u['id'] == BOT_ID), None)
    if bot_user:
        top_text += f"\n**Результат Гемблшмака**: {bot_user['balance']} очков\n"

    season = await state_col.find_one({"active": True})
    if season:
        days_left = 18 - (datetime.datetime.now(pytz.utc) - season['start_date']).days
        top_text += f"\nДо конца сезона осталось: **{days_left} дней**."
    
    await broadcast(top_text)

# --- GENERAL MESSAGE HANDLER & VIDEO DOWNLOADER ---
@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.is_bot or not message.text: return
    cid = message.chat.id
    
    # Populate history for scheduler
    get_history(cid)
    
    # Handle commands separately
    if message.text.startswith('/'):
        # This allows commands to be processed by their handlers
        return 

    if any(x in message.text for x in ["instagram.com/", "tiktok.com/", "youtube.com/shorts", "youtu.be/"]):
        await bot.send_chat_action(cid, "upload_video")
        v_url = await download_video_rapid(message.text)
        if v_url:
            async with aiohttp.ClientSession() as s:
                async with s.get(v_url) as r:
                    if r.status == 200:
                        await message.reply_video(BufferedInputFile(await r.read(), filename="v.mp4"), caption="😼 Стырил")
                        return

    history = get_history(cid)
    history.append({"role": "user", "name": message.from_user.first_name, "content": message.text})
    
    bot_obj = await bot.get_me()
    is_named = "башмак" in message.text.lower()
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_obj.id
    
    if not (message.chat.type == ChatType.PRIVATE or is_named or is_reply or random.random() < 0.05): return
    
    # The rest of your chat logic...

# --- MAIN ---
async def main():
    scheduler.add_job(gamblshmak_turn, CronTrigger(hour=13, minute=37), id="gamblshmak_turn")
    scheduler.add_job(daily_summary, CronTrigger(hour=20, minute=0), id="daily_summary")
    scheduler.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
