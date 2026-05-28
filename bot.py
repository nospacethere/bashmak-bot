
import os, asyncio, datetime, pytz, random, re
import yt_dlp
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
game_state_col = db['game_state']
amulets_col = db['amulets']
chats_col = db['chats'] # Новая коллекция для чатов

# --- ПРЕДМЕТЫ ---
ITEMS = {
    "chaos_cube": {"name": "🎲 Кубик Хаоса", "description": "Вычитает случайное число (1-6) у случайного игрока и добавляет вам.", "requires_target": False},
    "madness_coin": {"name": "🌓 Монета Безумия", "description": "Применяет к следующему спину один из двух эффектов (50/50): либо отменяет проигрыш, либо отменяет выигрыш.", "requires_target": False},
    "money_pouch": {"name": "💰 Мешочек мелочи", "description": "Мгновенно дает +10 фишек.", "requires_target": False},
    "golden_boot": {"name": "⚽ Золотой Бутс", "description": "Запускает мини-игру с ударом по воротам. За гол вы получаете +10 фишек, за промах -10.", "requires_target": False},
    "stone_rain": {"name": "🌧️ Дождь из камней", "description": "Изменяет баланс фишек всех игроков на случайное значение от -5 до 5.", "requires_target": False},
    "leaky_pocket": {"name": "🤏 Дырявый карман", "description": "Попытка украсть 15% фишек у самого богатого игрока. С шансом 30% вы отдадите 15% своих фишек ему.", "requires_target": False},
    "generous_jackpot": {"name": "🎉 Щедрый Джекпот", "description": "Вы получаете +10 фишек, а все остальные игроки — от 1 до 5 фишек.", "requires_target": False},
    "double_down": {"name": "⏫ Двойная Ставка", "description": "Активируйте перед спином, чтобы удвоить и выигрыш, и проигрыш.", "requires_target": False},
    "vampiric_amulet": {"name": "🩸 Вампирский Амулет", "description": "Вешается на случайного игрока. 24 часа вы получаете 50% от его выигрышей.", "requires_target": False},
    "shield_of_justice": {"name": "🛡️ Щит Справедливости", "description": "Защищает от следующей атаки или негативного события. Срабатывает автоматически.", "requires_target": False}
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
async def get_all_chat_ids():
    chats_cursor = chats_col.find({}, {'chat_id': 1})
    return [doc['chat_id'] for doc in await chats_cursor.to_list(length=None)]

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
                    if not medias:
                        direct_url = data.get('url') or data.get('video') or data.get('download')
                        if direct_url:
                            return {"url": direct_url, "width": None, "height": None}
                        return None

                    best = None
                    best_pixels = 0
                    for m in medias:
                        m_url = m.get('url')
                        if not m_url:
                            continue
                        ext = m.get('extension', '')
                        mtype = m.get('type', '')
                        if ext not in ('mp4', 'mov', 'webm') and mtype != 'video':
                            continue
                        w = m.get('width', 0) or 0
                        h = m.get('height', 0) or 0
                        pixels = w * h
                        if pixels > best_pixels:
                            best_pixels = pixels
                            best = {"url": m_url, "width": w, "height": h}

                    if best:
                        return best

                    first_url = medias[0].get('url')
                    if first_url:
                        return {"url": first_url, "width": None, "height": None}
        except Exception as e:
            print(f"Video download error: {e}")
    return None

INVIDIOUS_INSTANCES = ["https://inv.nadeko.net", "https://yewtu.be", "https://invidious.snopyta.org"]

def extract_youtube_id(url):
    import re
    patterns = [r"(?:youtube\.com/shorts/)([a-zA-Z0-9_-]+)", r"(?:youtube\.com/watch\?v=)([a-zA-Z0-9_-]+)", r"(?:youtu\.be/)([a-zA-Z0-9_-]+)", r"(?:youtube\.com/embed/)([a-zA-Z0-9_-]+)"]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None

async def download_youtube_invidious(video_id):
    for instance in INVIDIOUS_INSTANCES:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{instance}/api/v1/videos/{video_id}", timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status != 200:
                        continue
                    data = await r.json()
                    for fmt in data.get("formatStreams", []):
                        if fmt.get("container") == "mp4" and fmt.get("url"):
                            return {"url": fmt["url"], "width": fmt.get("width"), "height": fmt.get("height")}
                    best, best_px = None, 0
                    for fmt in data.get("adaptiveFormats", []):
                        if fmt.get("container") == "mp4" and fmt.get("type") == "video" and fmt.get("url"):
                            w, h = (fmt.get("width") or 0), (fmt.get("height") or 0)
                            if w * h > best_px:
                                best_px, best = w * h, {"url": fmt["url"], "width": w, "height": h}
                    if best:
                        return best
        except:
            continue
    return None

YT_COOKIES_FILE = "cookies.txt"

def get_ydl_opts():
    opts = {
        "format": "best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {"youtube": {"player_client": ["android_creator", "android"]}},
        "http_headers": {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36"}
    }
    cookies_b64 = os.getenv("YT_COOKIES")
    if cookies_b64:
        import base64
        try:
            with open(YT_COOKIES_FILE, "wb") as f:
                f.write(base64.b64decode(cookies_b64))
            opts["cookiefile"] = YT_COOKIES_FILE
            print("Loaded cookies from YT_COOKIES env")
        except Exception as e:
            print(f"Failed to load YT_COOKIES: {e}")
    elif os.path.exists(YT_COOKIES_FILE):
        opts["cookiefile"] = YT_COOKIES_FILE
        print("Loaded cookies from cookies.txt")
    return opts

async def download_youtube_video(url):
    try:
        loop = asyncio.get_event_loop()
        def extract():
            with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
        info = await loop.run_in_executor(None, extract)
        video_url = info.get('url')
        if not video_url:
            print(f"YouTube extract: no url field in response")
            return None
        width = info.get('width')
        height = info.get('height')
        duration = info.get('duration', 0) or 0
        if duration > 180:
            print(f"YouTube extract: video too long ({duration}s)")
            return None
        print(f"YouTube extract OK: {duration}s, {width}x{height}")
        return {"url": video_url, "width": width, "height": height}
    except Exception as e:
        print(f"YouTube download error: {e}")
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

    all_chat_ids_summary = await get_all_chat_ids()
    if not all_chat_ids_summary:
        await message.answer("ℹ️ Нет активных чатов для отправки итогов.")
    else:
        for cid in all_chat_ids_summary:
            try:
                await send_gambling_summary(cid)
            except Exception as e:
                print(f"Failed to send summary to {cid}: {e}")
        await message.answer("✅ Итоги дня отправлены.")

    await reset_daily_state()
    await message.answer("✅ Счетчики спинов сброшены.")

    await distribute_daily_items_and_announce()
    await message.answer("✅ Ежедневные предметы розданы и анонсированы.")

    await message.answer("🎉 Готово! Все ежедневные задачи выполнены.")

@dp.message(Command("admin_force_bot_action"))
async def cmd_admin_force_bot_action(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("😼 Заставляю Башмака отработать всё за today...")
    await force_bot_full_action()
    await message.answer("✅ Башмак отработал все предметы и спины!")

async def force_bot_full_action():
    bot_user = await bot.get_me()
    bot_id = bot_user.id
    bot_usable = ["chaos_cube", "money_pouch", "stone_rain", "golden_boot", "madness_coin", "double_down"]

    inv_doc = await inventories_col.find_one({"user_id": bot_id})
    if inv_doc and inv_doc.get("items"):
        items_to_use = [k for k in inv_doc["items"] if k in bot_usable]
        for item_key in items_to_use:
            inv_doc["items"].remove(item_key)
            await inventories_col.update_one({"user_id": bot_id}, {"$set": {"items": inv_doc["items"]}})
            await execute_bot_single_item(item_key)
            await asyncio.sleep(5)

    spin_count_doc = await spin_counts_col.find_one({'user_id': bot_id})
    spins_done = spin_count_doc.get('count', 0) if spin_count_doc else 0
    remaining = max(0, 2 - spins_done)

    for _ in range(remaining):
        await execute_bot_spin()
        await asyncio.sleep(5)

async def execute_bot_single_item(item_key):
    bot_user = await bot.get_me()
    bot_id = bot_user.id
    item_info = ITEMS[item_key]
    announcement = ""

    if item_key == "money_pouch":
        await scores_col.update_one({"user_id": bot_id}, {"$inc": {"balance": 10}}, upsert=True)
        bot_doc = await scores_col.find_one({"user_id": bot_id})
        announcement = (f"😼 Гемблинг Башмак использует предмет!\n\n"
                        f"Кот нашёл {item_info['name']} и получил 10 фишек.\n"
                        f"Его баланс: {bot_doc.get('balance', 'N/A')} фишек. 🎰")

    elif item_key == "stone_rain":
        all_players = await scores_col.find({}, {"user_id": 1, "name": 1}).to_list(length=None)
        if not all_players:
            announcement = f"😼 Башмак использовал {item_info['name']}, но в казино пусто."
        else:
            lines = []
            for p in all_players:
                change = random.randint(-5, 5)
                await scores_col.update_one({"user_id": p['user_id']}, {"$inc": {"balance": change}})
                name = "Гемблинг Башмак" if p['user_id'] == bot_id else p.get('name', 'Anon')
                sign = "+" if change >= 0 else ""
                lines.append(f"{name}: {sign}{change}")
            announcement = (f"😼 Башмак использовал {item_info['name']}!\n\n"
                            f"Результаты:\n" + "\n".join(lines))

    elif item_key == "chaos_cube":
        others = await scores_col.find({"user_id": {"$ne": bot_id}}, {"user_id": 1, "name": 1}).to_list(length=None)
        if not others:
            announcement = f"😼 Башмак попытался использовать {item_info['name']}, но некого грабить."
        else:
            victim = random.choice(others)
            roll = random.randint(1, 6)
            await scores_col.update_one({"user_id": bot_id}, {"$inc": {"balance": roll}})
            await scores_col.update_one({"user_id": victim['user_id']}, {"$inc": {"balance": -roll}})
            bd = await scores_col.find_one({"user_id": bot_id})
            vd = await scores_col.find_one({"user_id": victim['user_id']})
            announcement = (f"😼 Башмак использовал {item_info['name']}!\n\n"
                            f"Жертва: {victim['name']}, украдено {roll} фишек.\n"
                            f"Баланс Башмака: {bd.get('balance', 'N/A')}\n"
                            f"Баланс {victim['name']}: {vd.get('balance', 'N/A')}")

    elif item_key == "golden_boot":
        dv = random.randint(1, 6)
        change = 10 if dv >= 4 else -10
        await scores_col.update_one({"user_id": bot_id}, {"$inc": {"balance": change}})
        bd = await scores_col.find_one({"user_id": bot_id})
        result = "забивает гол и получает +10" if change > 0 else "промахивается и теряет 10"
        announcement = (f"😼 Башмак использовал {item_info['name']}!\n\n"
                        f"Кот {result} фишек.\n"
                        f"Баланс: {bd.get('balance', 'N/A')} ⚽️")

    elif item_key == "madness_coin":
        await scores_col.update_one({"user_id": bot_id}, {"$addToSet": {"active_effects": "madness_coin"}}, upsert=True)
        announcement = (f"😼 Башмак использовал {item_info['name']}!\n\n"
                        f"Следующий спин будет безумным. 🌓")

    elif item_key == "double_down":
        await scores_col.update_one({"user_id": bot_id}, {"$addToSet": {"active_effects": "double_down"}}, upsert=True)
        announcement = (f"😼 Башмак использовал {item_info['name']}!\n\n"
                        f"Следующий спин удвоен. ⏫")

    if announcement:
        all_ids = await get_all_chat_ids()
        for cid in all_ids:
            try:
                await bot.send_message(cid, announcement)
                await asyncio.sleep(0.2)
            except:
                pass

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

    gs = await game_state_col.find_one()
    if gs and gs.get("game_ended"):
        await message.reply("🏁 Сезон окончен, лавка контрабанды закрыта. Ждите новый сезон! 🎰")
        return

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

    gs = await game_state_col.find_one()
    if gs and gs.get("game_ended"):
        await context_message.answer("🏁 Сезон окончен, предметы больше не работают. Ждите новый сезон! 🎰")
        return

    if item_key not in ITEMS:
        await context_message.answer(f"Неверный предмет. Доступные: {', '.join(ITEMS.keys())}")
        return

    inventory_doc = await inventories_col.find_one({"user_id": user_id})
    if not inventory_doc or item_key not in inventory_doc.get("items", []):
        await context_message.answer("У вас нет такого предмета. 😕")
        return

    current_items = inventory_doc.get("items", [])
    current_items.remove(item_key)
    await inventories_col.update_one({"user_id": user_id}, {"$set": {"items": current_items}})

    item = ITEMS[item_key]

    if item.get("requires_target"):
        pass

    if item_key == "vampiric_amulet":
        bot_user = await bot.get_me()
        other_players_cursor = scores_col.find({"user_id": {"$nin": [user_id, bot_user.id]}}, {"user_id": 1, "name": 1})
        other_players = await other_players_cursor.to_list(length=None)

        if not other_players:
            await context_message.answer("🩸 В казино больше нет игроков, чтобы выпить их кровь... то есть, фишки. 🧛")
            await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": item_key}})
            return

        victim = random.choice(other_players)
        victim_id = victim['user_id']
        victim_name = victim['name']
        
        victim_doc = await scores_col.find_one({"user_id": victim_id})
        if victim_doc and "shield_of_justice_active" in victim_doc.get("active_effects", []):
            await scores_col.update_one({"user_id": victim_id}, {"$pull": {"active_effects": "shield_of_justice_active"}})
            await context_message.answer(f"🩸 Вы попытались повесить Вампирский Амулет на игрока {victim_name}, но его Щит Справедливости уничтожил амулет! Щит цели разрушен. 🛡️")
            return

        expires_at = datetime.datetime.now(pytz.utc) + datetime.timedelta(hours=24)
        await amulets_col.insert_one({"owner_id": user_id, "victim_id": victim_id, "expires_at": expires_at})
        
        await context_message.answer(f"🩸 Вы повесили Вампирский Амулет на игрока {victim_name}! Следующие 24 часа вы будете получать 50% от всех его выигрышей. 🧛")
        return

    elif item_key == "shield_of_justice":
        await scores_col.update_one({"user_id": user_id}, {"$addToSet": {"active_effects": "shield_of_justice_active"}}, upsert=True)
        await context_message.answer("🛡️ Вы активировали Щит Справедливости! Он защитит вас от следующего негативного эффекта.")
        return

    elif item_key == "money_pouch":
        await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": 10}}, upsert=True)
        user_doc = await scores_col.find_one({"user_id": user_id})
        new_balance = user_doc.get('balance', 10)
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

        victim_doc_before = await scores_col.find_one({"user_id": victim_id})
        if victim_doc_before and "shield_of_justice_active" in victim_doc_before.get("active_effects", []):
            await scores_col.update_one({"user_id": victim_id}, {"$pull": {"active_effects": "shield_of_justice_active"}})
            await context_message.answer(f"🎲 Кубик Хаоса попытался ударить по игроку {victim_name}, но его {roll} фишек были заблокированы Щитом Справедливости! 🛡️")
            return
        
        await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": roll}}, upsert=True)
        await scores_col.update_one({"user_id": victim_id}, {"$inc": {"balance": -roll}}, upsert=True)

        user_doc = await scores_col.find_one({"user_id": user_id})
        victim_doc = await scores_col.find_one({"user_id": victim_id})

        await context_message.answer(f"🎲 Кубик Хаоса в действии!\nВы выбросили {roll}. {roll} фишек переходят от игрока {victim_name} к вам.\nВаш баланс: {user_doc['balance']}\nБаланс {victim_name}: {victim_doc['balance'] if victim_doc else 'N/A'}")

    elif item_key == "madness_coin":
        await scores_col.update_one({"user_id": user_id}, {"$addToSet": {"active_effects": "madness_coin"}}, upsert=True)
        await context_message.answer("🌓 Вы использовали Монету Безумия! Ваш следующий спин определит судьбу. Удачи... или нет. 😈")
    
    elif item_key == "double_down":
        await scores_col.update_one({"user_id": user_id}, {"$addToSet": {"active_effects": "double_down"}}, upsert=True)
        await context_message.answer("⏫ Вы использовали Двойную Ставку! Ваш следующий спин будет стоить вдвое дороже... или принесет вдвое больше. Риск — благородное дело! 🎰")

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

            if change < 0:
                player_doc = await scores_col.find_one({"user_id": player_id})
                if player_doc and "shield_of_justice_active" in player_doc.get("active_effects", []):
                    await scores_col.update_one({"user_id": player_id}, {"$pull": {"active_effects": "shield_of_justice_active"}})
                    update_summary.append(f"{player_name}: удар камнем был заблокирован Щитом! 🛡️")
                    continue
            
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
        
        if random.random() < 0.3:
            user_doc_fail = await scores_col.find_one({"user_id": user_id})
            if user_doc_fail and "shield_of_justice_active" in user_doc_fail.get("active_effects", []):
                await scores_col.update_one({"user_id": user_id}, {"$pull": {"active_effects": "shield_of_justice_active"}})
                await context_message.answer(f"🤏 Вас поймали за руку, но Щит Справедливости защитил вас от потери фишек! Щит разрушен. 🛡️")
                return

            amount = int(user_doc_fail.get('balance', 0) * 0.15)
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
            top_player_doc = await scores_col.find_one({"user_id": top_player_id})
            if top_player_doc and "shield_of_justice_active" in top_player_doc.get("active_effects", []):
                await scores_col.update_one({"user_id": top_player_id}, {"$pull": {"active_effects": "shield_of_justice_active"}})
                await context_message.answer(f"🤏 Вы попытались стащить фишки у {top_player_name}, но его Щит Справедливости заблокировал кражу! Щит цели разрушен. 🛡️")
                return
            
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

    elif item_key == "generous_jackpot":
        await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": 10}}, upsert=True)
        user_doc = await scores_col.find_one({"user_id": user_id})
        new_balance = user_doc.get('balance', 10)

        bot_user = await bot.get_me()
        other_players_cursor = scores_col.find({"user_id": {"$nin": [user_id, bot_user.id]}})
        other_players = await other_players_cursor.to_list(length=None)

        update_summary = [f"Вы получили +10 фишек. Ваш новый баланс: {new_balance} фишек."]
        
        if not other_players:
            await context_message.answer(f"🎉 Вы использовали Щедрый Джекпот! {update_summary[0]}. В казино нет других игроков, чтобы поделиться щедростью.")
            return

        for player in other_players:
            player_id = player['user_id']
            player_name = player.get('name', 'Неизвестный игрок')
            amount = random.randint(1, 5)
            await scores_col.update_one({"user_id": player_id}, {"$inc": {"balance": amount}})
            player_doc_after = await scores_col.find_one({"user_id": player_id})
            player_new_balance = player_doc_after.get('balance', 'N/A')
            update_summary.append(f"{player_name} получил +{amount} фишек (итого: {player_new_balance}).")

        summary_message = "🎉 Вы использовали Щедрый Джекпот! 🎉\n\n" + "\n".join(update_summary)
        await context_message.answer(summary_message)


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
    await chats_col.update_one({'chat_id': message.chat.id}, {'$set': {'last_seen': datetime.datetime.now(pytz.utc)}}, upsert=True)
    user_id = message.from_user.id
    user_name = message.from_user.first_name

    game_state_doc = await game_state_col.find_one()

    if game_state_doc and game_state_doc.get("game_ended"):
        await message.reply("🏁 Игровой сезон завершён! Дождитесь нового сезона или попросите админа сбросить игру. 🎰")
        return

    if not game_state_doc or 'start_date' not in game_state_doc:
        start_date = datetime.datetime.now(pytz.timezone('Europe/Moscow')).replace(tzinfo=None)
        await game_state_col.update_one({}, {"$set": {"start_date": start_date}}, upsert=True)
        print(f"New game season started at {start_date}")

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

Игра длится 14 дней. В конце сезона казино закрывается, а лучшие игроки попадают в Зал Славы! Сегодня 1-й день. (/day)

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
- /day — узнать текущий день сезона.

Да начнутся игры! Делай свою первую ставку. 🎰
'''
        await message.answer(welcome_text, parse_mode=None)

    await spin_counts_col.update_one({'user_id': user_id},{'$inc': {'count': 1}},upsert=True)

    cost_msg = f"(Спин {current_spin_number}/2) "

    base_change = calculate_win(message.dice.value)
    final_change = base_change
    
    active_effects = user_doc.get('active_effects', [])
    effects_to_remove = []
    effect_messages = []

    if "double_down" in active_effects:
        final_change *= 2
        effect_messages.append(f"⏫ Двойная Ставка удваивает результат!")
        effects_to_remove.append("double_down")

    if "madness_coin" in active_effects:
        is_shield = random.random() < 0.5
        change_before_cancellation = final_change 
        
        if is_shield and final_change < 0:
            final_change = 0
            effect_messages.append(f"🌓 Сработал ЩИТ Монеты Безумия! Проигрыш {change_before_cancellation} отменен.")
        elif not is_shield and final_change > 0:
            final_change = 0
            effect_messages.append(f"🌓 Сработала ПУСТОТА Монеты Безумия! Выигрыш {change_before_cancellation} отменен.")
        else:
             effect_messages.append(f"🌓 Монета Безумия была использована, но ее эффект не пригодился.")

        effects_to_remove.append("madness_coin")
        
    update_query = {"$inc": {"balance": final_change}}
    if effects_to_remove:
        update_query["$pull"] = {"active_effects": {"$in": effects_to_remove}}
    await scores_col.update_one({'user_id': user_id}, update_query)
    
    new_balance = current_balance + final_change

    if base_change > 0:
        amulet = await amulets_col.find_one({"victim_id": user_id, "expires_at": {"$gt": datetime.datetime.now(pytz.utc)}})
        if amulet:
            victim_doc_amulet = await scores_col.find_one({'user_id': user_id})
            if victim_doc_amulet and "shield_of_justice_active" in victim_doc_amulet.get("active_effects", []):
                await scores_col.update_one({"user_id": user_id}, {"$pull": {"active_effects": "shield_of_justice_active"}})
                owner_doc = await scores_col.find_one({"user_id": amulet['owner_id']})
                owner_name = owner_doc.get('name', 'Таинственный вампир')
                effect_messages.append(f"🩸 Вампирский Амулет игрока {owner_name} попытался сработать, но ваш Щит Справедливости заблокировал кражу! Щит разрушен. 🛡️")
            else:
                owner_id = amulet['owner_id']
                stolen_amount = int(base_change * 0.5)
                
                await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": -stolen_amount}})
                await scores_col.update_one({"user_id": owner_id}, {"$inc": {"balance": stolen_amount}}, upsert=True)
                
                new_balance -= stolen_amount
                owner_doc = await scores_col.find_one({"user_id": owner_id})
                owner_name = owner_doc.get('name', 'Таинственный вампир')
                
                effect_messages.append(f"🩸 Вампирский Амулет игрока {owner_name} сработал! Он забирает у вас {stolen_amount} фишек.")
                try:
                    await bot.send_message(owner_id, f"🩸 Ваш Вампирский Амулет на игроке {user_name} принес вам {stolen_amount} фишек!")
                except Exception as e:
                    print(f"Failed to notify amulet owner {owner_id}: {e}")

    full_effect_message = " ".join(effect_messages)

    if full_effect_message:
        await message.reply(f"{cost_msg}{full_effect_message} Итог: {final_change}. Баланс: {new_balance} 🎰")
    else:
        if base_change >= 10: await message.reply(f"{cost_msg}Крупный выигрыш! +{base_change}. Баланс: {new_balance} 🎰")
        elif base_change > 0: await message.reply(f"{cost_msg}Держи +{base_change}. Баланс: {new_balance} 🎰")
        else: await message.reply(f"{cost_msg}Мимо. {base_change}. Баланс: {new_balance} 🎰")

@dp.message(lambda m: m.dice and m.dice.emoji == '⚽' and not m.from_user.is_bot)
async def handle_football(message: types.Message):
    user_id = message.from_user.id

    gs = await game_state_col.find_one()
    if gs and gs.get("game_ended"):
        return

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
    effect_msg = ""

    if change > 0:
        amulet = await amulets_col.find_one({"victim_id": user_id, "expires_at": {"$gt": datetime.datetime.now(pytz.utc)}})
        if amulet:
            if "shield_of_justice_active" in updated_user_doc.get("active_effects", []):
                await scores_col.update_one({"user_id": user_id}, {"$pull": {"active_effects": "shield_of_justice_active"}})
                owner_doc = await scores_col.find_one({"user_id": amulet['owner_id']})
                owner_name = owner_doc.get('name', 'Таинственный вампир')
                effect_msg = f" 🛡️ Щит заблокировал амулет {owner_name}!"
            else:
                owner_id = amulet['owner_id']
                stolen_amount = int(change * 0.5)
                await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": -stolen_amount}})
                await scores_col.update_one({"user_id": owner_id}, {"$inc": {"balance": stolen_amount}}, upsert=True)
                new_balance -= stolen_amount
                owner_doc = await scores_col.find_one({"user_id": owner_id})
                owner_name = owner_doc.get('name', 'Таинственный вампир')
                effect_msg = f" 🩸 Вампирский Амулет {owner_name} забирает {stolen_amount}."
                try:
                    await bot.send_message(owner_id, f"🩸 Ваш амулет на игроке {message.from_user.first_name} принес {stolen_amount} фишек с мини-игры!")
                except:
                    pass

    if change > 0:
        await message.reply(f"ГОООЛ! Вы забили и получаете +{change} фишек! Баланс: {new_balance}{effect_msg} ⚽️")
    else:
        await message.reply(f"Штанга! Вы промахнулись и теряете {abs(change)} фишек... Баланс: {new_balance} ⚽️")

@dp.message(Command("top"))
async def cmd_top(message: types.Message):
    text = await get_leaderboard_text()
    await message.answer(text)

@dp.message(Command("day"))
async def cmd_day(message: types.Message):
    game_state_doc = await game_state_col.find_one()
    if not game_state_doc or 'start_date' not in game_state_doc:
        await message.answer("🗓️ Игровой сезон еще не начался! Сделайте первую ставку, чтобы запустить его.")
        return

    start_date = game_state_doc.get('start_date')
    now = datetime.datetime.now(pytz.timezone('Europe/Moscow')).replace(tzinfo=None)
    day_number = (now - start_date).days + 1

    if day_number > 14:
        await message.answer(f"🗓️ Игровой сезон (день {day_number}/14) уже должен был завершиться. Ждем финала!")
    else:
        await message.answer(f"🗓️ Идет {day_number}-й день из 14 игрового сезона.")

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
              "Подведи краткие итоги дня в казино. "
              "Обязательно упомяни таблицу лидеров. "
              "ВАЖНО: Напиши 2-3 предложения. "
              f"Вот переписка:\n{text_dump}\n\nА вот зал славы казино:\n{top_text}"
             )
    
    res = await ask_model([{"role": "user", "content": prompt}], temp=1.0)
    await bot.send_message(chat_id, f"💰 Итоги игрового дня:\n{res} 🎰")


@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.is_bot or not message.text or message.text.startswith('/') or (message.dice and message.dice.emoji in ['🎰', '⚽']):
        return

    gs = await game_state_col.find_one()
    if gs and gs.get("game_ended"):
        return

    cid = message.chat.id
    await chats_col.update_one({'chat_id': cid}, {'$set': {'last_seen': datetime.datetime.now(pytz.utc)}}, upsert=True)
    history = get_history(cid)
    text = message.text
    
    url_pattern = r'https?://[^\s]+'
    found_urls = re.findall(url_pattern, text)
    url_to_download = None
    if found_urls:
        url_to_download = found_urls[0]

    is_video_link = False
    if url_to_download and ("instagram.com/" in url_to_download or "tiktok.com/" in url_to_download or "vm.tiktok.com/" in url_to_download or "youtube.com/" in url_to_download or "youtu.be/" in url_to_download or "m.youtube.com/" in url_to_download):
        is_video_link = True

    if is_video_link:
        await bot.send_chat_action(cid, "upload_video")

        is_youtube = "youtube.com/" in url_to_download or "youtu.be/" in url_to_download or "m.youtube.com/" in url_to_download
        video_info = None

        if is_youtube:
            try:
                import yt_dlp
                video_info = await download_youtube_video(url_to_download)
            except ImportError:
                print("yt-dlp not installed")

            if not video_info:
                vid = extract_youtube_id(url_to_download)
                if vid:
                    print(f"Trying Invidious for video {vid}")
                    video_info = await download_youtube_invidious(vid)

        if not video_info:
            video_info = await download_video_rapid(url_to_download)
        if video_info:
            v_url = video_info['url']
            width = video_info.get('width')
            height = video_info.get('height')
            
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36", "Referer": url_to_download}
                async with aiohttp.ClientSession() as s:
                    async with s.get(v_url, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as r:
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
        return

    history.append({'role': 'user', 'name': message.from_user.first_name, 'content': text})
    try: 
        await scores_col.update_one({"user_id": message.from_user.id}, {"$set": {"name": message.from_user.first_name}}, upsert=False)
    except: pass

    bot_obj = await bot.get_me()
    is_named = bot_obj.username.lower() in text.lower()
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_obj.id
    
    if not (message.chat.type == ChatType.PRIVATE or is_named or is_reply): return

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
    now_moscow = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
    
    hour1 = random.randint(9, 12)
    minute1 = random.randint(0, 59)
    t1 = now_moscow.replace(hour=hour1, minute=minute1, second=0, microsecond=0)
    if t1 <= now_moscow:
        t1 += datetime.timedelta(days=1)
    bot_spin_time_1 = t1

    hour2 = random.randint(18, 21)
    minute2 = random.randint(0, 59)
    t2 = now_moscow.replace(hour=hour2, minute=minute2, second=0, microsecond=0)
    if t2 <= now_moscow:
        t2 += datetime.timedelta(days=1)
    bot_spin_time_2 = t2

    print(f"[{datetime.datetime.now()}] Bot spins scheduled. Spin 1: {bot_spin_time_1}, Spin 2: {bot_spin_time_2} MSK")

async def execute_bot_spin():
    bot_user = await bot.get_me()
    bot_id = bot_user.id
    
    spin_count_doc = await spin_counts_col.find_one({'user_id': bot_id})
    spin_count = spin_count_doc.get('count', 0) if spin_count_doc else 0
    if spin_count >= 2:
        print(f"[{datetime.datetime.now()}] Bot has already spun twice today.")
        return

    all_chat_ids = await get_all_chat_ids()
    if not all_chat_ids:
        print(f"[{datetime.datetime.now()}] No active chats for bot spin.")
        return

    dice_value = random.randint(1, 64)
    change = calculate_win(dice_value)

    bot_doc = await scores_col.find_one({'user_id': bot_id})
    if not bot_doc:
        await scores_col.update_one({"user_id": bot_id}, {"$set": {"name": "Гемблинг Башмак", "balance": 100}}, upsert=True)
        bot_doc = await scores_col.find_one({'user_id': bot_id})

    final_change = change
    active_effects = bot_doc.get('active_effects', [])
    effects_to_remove = []
    effect_message = None

    if "double_down" in active_effects:
        final_change *= 2
        effect_message = f"⏫ Двойная Ставка удваивает результат!"
        effects_to_remove.append("double_down")

    if "madness_coin" in active_effects:
        is_shield = random.random() < 0.5
        original_change = final_change
        
        if is_shield:
            if final_change < 0: final_change = 0
            effect_message = f"🌓 Сработал ЩИТ Монеты Безумия! Проигрыш {original_change} был отменен."
        else:
            if final_change > 0: final_change = 0
            effect_message = f"🌓 Сработала ПУСТОТА Монеты Безумия! Выигрыш {original_change} был отменен."
        effects_to_remove.append("madness_coin")

    update_query = {"$inc": {"balance": final_change}}
    if effects_to_remove:
        update_query["$pull"] = {"active_effects": {"$in": effects_to_remove}}
    
    await scores_col.update_one({'user_id': bot_id}, update_query)
    await spin_counts_col.update_one({'user_id': bot_id}, {'$inc': {'count': 1}}, upsert=True)
    
    bot_doc_after = await scores_col.find_one({'user_id': bot_id})
    new_balance = bot_doc_after.get("balance", "N/A")
    stolen_amount = 0

    if change > 0:
        amulet = await amulets_col.find_one({"victim_id": bot_id, "expires_at": {"$gt": datetime.datetime.now(pytz.utc)}})
        if amulet:
            if "shield_of_justice_active" in bot_doc_after.get("active_effects", []):
                await scores_col.update_one({"user_id": bot_id}, {"$pull": {"active_effects": "shield_of_justice_active"}})
                owner_doc = await scores_col.find_one({"user_id": amulet['owner_id']})
                owner_name = owner_doc.get('name', 'Таинственный вампир')
                effect_message = (effect_message + " " if effect_message else "") + f"🛡️ Щит Справедливости заблокировал Вампирский Амулет игрока {owner_name}!"
            else:
                owner_id = amulet['owner_id']
                stolen_amount = int(change * 0.5)
                await scores_col.update_one({"user_id": bot_id}, {"$inc": {"balance": -stolen_amount}})
                await scores_col.update_one({"user_id": owner_id}, {"$inc": {"balance": stolen_amount}}, upsert=True)
                new_balance -= stolen_amount
                owner_doc = await scores_col.find_one({"user_id": owner_id})
                owner_name = owner_doc.get('name', 'Таинственный вампир')
                effect_message = (effect_message + " " if effect_message else "") + f"🩸 Вампирский Амулет игрока {owner_name} забирает {stolen_amount} фишек."
                try:
                    await bot.send_message(owner_id, f"🩸 Ваш Вампирский Амулет на Гемблинг Башмаке принес вам {stolen_amount} фишек!")
                except:
                    pass

    if effect_message:
         message_text = (f"🎲 Гемблинг Башмак делает свой ход! 🎲\n\n"
                        f"{effect_message}\n"
                        f"Итог: {final_change}. Баланс: {new_balance} фишек. 😼")
    else:
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
    print(f"[{datetime.datetime.now()}] Attempting to execute bot item use.")
    bot_user = await bot.get_me()
    bot_id = bot_user.id

    inv_doc = await inventories_col.find_one({"user_id": bot_id})
    if not inv_doc or not inv_doc.get("items"):
        print(f"[{datetime.datetime.now()}] Bot has no items to use.")
        return

    usable = ["chaos_cube", "money_pouch", "stone_rain", "golden_boot", "madness_coin", "double_down"]
    available = [k for k in inv_doc["items"] if k in usable]
    if not available:
        print(f"[{datetime.datetime.now()}] Bot has no usable items.")
        return

    item_key = random.choice(available)
    inv_doc["items"].remove(item_key)
    await inventories_col.update_one({"user_id": bot_id}, {"$set": {"items": inv_doc["items"]}})
    await execute_bot_single_item(item_key)

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

    all_chat_ids = await get_all_chat_ids()
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

async def run_chaos_event():
    print(f"[{datetime.datetime.now()}] Checking for Chaos Cube event.")
    
    event_key = "chaos_cube_event_done"
    game_state = await game_state_col.find_one()
    if game_state.get(event_key):
        print("Chaos Cube event has already been executed.")
        return

    all_players_cursor = scores_col.find({}, {"user_id": 1})
    all_players = await all_players_cursor.to_list(length=None)
    if not all_players:
        print("No players to give chaos cubes to.")
        return

    for player in all_players:
        await inventories_col.update_one(
            {"user_id": player['user_id']},
            {"$push": {"items": {"$each": ["chaos_cube"] * 5}}},
            upsert=True
        )
    
    print(f"Gave 5 chaos cubes to {len(all_players)} players.")

    all_chat_ids = await get_all_chat_ids()
    announcement = (
        f"🎲 Ивент «Парад Хаоса»! 🎲\n\n"
        f"В честь четвёртого дня сезона каждый игрок в казино получает по 5 Кубиков Хаоса!\n\n"
        f"Пусть начнется безумие! Проверьте свой /inventory. 🎰"
    )
    for cid in all_chat_ids:
        try:
            await bot.send_message(cid, announcement)
        except Exception as e:
            print(f"Failed to send chaos event announcement to chat {cid}: {e}")

    await game_state_col.update_one({}, {"$set": {event_key: True}})
    print("Chaos Cube event has been marked as executed.")


# --- ПЛАНИРОВЩИК ---
async def cleanup_expired_amulets():
    now = datetime.datetime.now(pytz.utc)
    result = await amulets_col.delete_many({"expires_at": {"$lt": now}})
    if result.deleted_count > 0:
        print(f"[{datetime.datetime.now()}] Cleaned up {result.deleted_count} expired vampiric amulets.")

async def reset_daily_state():
    await spin_counts_col.delete_many({})
    schedule_bot_spins()
    print(f"[{datetime.datetime.now()}] Daily spin counts have been reset.")

async def end_game_action():
    print(f"[{datetime.datetime.now()}] Game season of 14 days has ended.")
    top_text = await get_leaderboard_text()
    announcement = (
        f"🎉 Игровой сезон окончен! 🎉\n\n"
        f"14 дней пролетели как один миг! Казино «Гемблинг Башмак» закрывает свои двери... до следующего раза.\n\n"
        f"А вот и наши легенды, сорвавшие куш:\n{top_text}\n\n"
        f"Игра остановлена — больше нельзя делать ставки и использовать предметы.\n"
        f"Админ может сбросить всё командой /admin_wipe_scores_777, чтобы начать новый сезон. 🎰"
    )
    
    all_chat_ids = await get_all_chat_ids()
    for cid in all_chat_ids:
        try:
            await bot.send_message(cid, announcement)
        except Exception as e:
            print(f"Failed to send end game message to {cid}: {e}")

    await game_state_col.update_one({}, {"$set": {"game_ended": True}}, upsert=True)
    print(f"[{datetime.datetime.now()}] Game marked as ended. Data preserved for admin wipe.")


async def scheduler():
    print("Scheduler starting...")
    await game_state_col.update_one({}, {"$setOnInsert": {"last_daily_reset_date": None}}, upsert=True)

    while True:
        try:
            now_moscow = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
            today_str = now_moscow.date().isoformat()
            game_state = await game_state_col.find_one({})

            if game_state and game_state.get("game_ended"):
                await asyncio.sleep(3600)
                continue

            start_date = game_state.get('start_date')
            if not start_date:
                await asyncio.sleep(30)
                continue
                
            current_day = (now_moscow.replace(tzinfo=None) - start_date).days + 1

            if current_day > 14:
                if not game_state.get("game_ended"):
                    await end_game_action()
                await asyncio.sleep(3600)
                continue

            if current_day >= 4 and now_moscow.hour == 12 and not game_state.get("chaos_cube_event_done"):
                await run_chaos_event()

            last_reset_date = game_state.get("last_daily_reset_date")
            if last_reset_date is None or last_reset_date != today_str:
                print(f"[{datetime.datetime.now()}] New day detected ({today_str}). Previous reset: {last_reset_date}. Running daily tasks.")
                
                all_chat_ids_summary = await get_all_chat_ids()
                for cid in all_chat_ids_summary:
                    try:
                        await send_gambling_summary(cid)
                    except Exception as e:
                        print(f"Failed to send summary to {cid}: {e}")

                await reset_daily_state()
                await distribute_daily_items_and_announce()

                for cid in user_history: user_history[cid].clear()

                await game_state_col.update_one({}, {"$set": {"last_daily_reset_date": today_str}})
                print(f"[{datetime.datetime.now()}] All daily tasks completed for {today_str}.")

            if now_moscow.minute % 10 == 0:
                await cleanup_expired_amulets()

            noon_task_key = f"noon_task_done_{today_str}"
            if now_moscow.hour == 12 and not game_state.get(noon_task_key):
                print(f"[{datetime.datetime.now()}] Triggering bot item use.")
                await execute_bot_item_use()
                await game_state_col.update_one({}, {"$set": {noon_task_key: True}})

            global bot_spin_time_1, bot_spin_time_2

            if bot_spin_time_1 and now_moscow >= bot_spin_time_1:
                print(f"[{datetime.datetime.now()}] Triggering bot spin 1 (scheduled for {bot_spin_time_1}).")
                await execute_bot_spin()
                bot_spin_time_1 = None

            if bot_spin_time_2 and now_moscow >= bot_spin_time_2:
                print(f"[{datetime.datetime.now()}] Triggering bot spin 2 (scheduled for {bot_spin_time_2}).")
                await execute_bot_spin()
                bot_spin_time_2 = None
            
            await asyncio.sleep(30)
        except Exception as e:
            print(f"!!!FATAL SCHEDULER ERROR: {e}!!!")
            await asyncio.sleep(60)


async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bashmak is alive"))
    runner = web.AppRunner(app)
    await runner.setup()
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
        BotCommand(command="get_item", description="🎲 Купить случайный предмет (10 фишек)"),
        BotCommand(command="day", description="🗓️ Узнать текущий день сезона")
    ]
    await bot.set_my_commands(main_commands)

    print("Waiting 10s for old instance to shut down...")
    await asyncio.sleep(10)
    print("Bot started polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
