import asyncio, datetime, aiohttp, hashlib, random, re, pytz
from collections import deque
from config import (bot, scores_col, chats_col, amulets_col, game_state_col, user_history,
                    RAPID_KEY, RAPID_APIS, client, SKIP_DELETE_PREFIXES, GAMBLING_SHOE_PROMPT,
                    HOROSCOPE_API_URL, ZODIAC_RUS, ZODIAC_EMOJI, PLAYER_ZODIACS, DEADLOCK_PLAYERS,
                    MYSTIC_PREFIXES, MYSTIC_SIGNATURES, horoscope_cache)

def get_history(chat_id: int):
    if chat_id not in user_history:
        user_history[chat_id] = deque(maxlen=100)
    return user_history[chat_id]

async def get_casino_chat_id():
    gs = await game_state_col.find_one()
    return gs.get("casino_chat_id") if gs else None

async def get_horoscope_chat_id():
    gs = await game_state_col.find_one()
    if gs and gs.get("horoscope_chat_id"):
        return gs["horoscope_chat_id"]
    return await get_casino_chat_id()

def calculate_win(dice_value: int) -> int:
    if dice_value == 64: return 50
    v = dice_value - 1
    reels = [v % 4, (v // 4) % 4, v // 16]
    if reels[0] == reels[1] == reels[2]: return 20
    if reels[0] == reels[1] or reels[1] == reels[2]: return -1
    return -5

async def get_leaderboard_text() -> str:
    cursor = scores_col.find().sort("balance", -1).limit(10)
    players = await cursor.to_list(length=10)
    if not players:
        return "В казино пока нет хайроллеров..."
    text = "🏆 Зал славы казино:\n"
    for i, p in enumerate(players):
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i + 1}."
        text += f"{medal} {p.get('name', 'Anon')}: {p.get('balance', 0)} фишек\n"
    return text

async def get_all_chat_ids() -> list:
    cursor = chats_col.find({}, {'chat_id': 1})
    return [doc['chat_id'] for doc in await cursor.to_list(length=None)]

async def ask_model(messages: list, temp: float = 0.8) -> str:
    if not client:
        return "Башмак отдыхает."
    try:
        completion = await client.chat.completions.create(
            model="llama-3.3-70b-versatile", messages=messages, temperature=temp
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Башмак сломался: {e}"

async def call_rapid_api(host: str, path: str, url: str):
    headers = {
        "Content-Type": "application/json",
        "x-rapidapi-host": host,
        "x-rapidapi-key": RAPID_KEY,
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"https://{host}{path}",
                json={"url": url},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                print(f"RapidAPI {host} status {resp.status}")
    except Exception as e:
        print(f"RapidAPI {host} error: {e}")
    return None

def extract_video_from_response(data: dict):
    medias = data.get('medias', [])
    if not medias:
        direct_url = data.get('url') or data.get('video') or data.get('download')
        if direct_url:
            return {"url": direct_url, "width": None, "height": None}
        return None
    best, best_pixels = None, 0
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
    return None

async def download_video_rapid(url: str):
    if not RAPID_KEY:
        return None
    for attempt in range(3):
        for api in RAPID_APIS:
            data = await call_rapid_api(api["host"], api["path"], url)
            if not data:
                continue
            result = extract_video_from_response(data)
            if result:
                return result
        if attempt < 2:
            await asyncio.sleep(2)
    return None

async def handle_vampire_amulet(user_id: int, base_change: int, new_balance, updated_user_doc: dict = None, game_name: str = "спина") -> tuple:
    if base_change <= 0:
        return "", new_balance
    amulet = await amulets_col.find_one({
        "victim_id": user_id,
        "expires_at": {"$gt": datetime.datetime.now(pytz.utc)},
    })
    if not amulet:
        return "", new_balance
    victim_doc = updated_user_doc or await scores_col.find_one({"user_id": user_id})
    if victim_doc and "shield_of_justice_active" in victim_doc.get("active_effects", []):
        await scores_col.update_one(
            {"user_id": user_id},
            {"$pull": {"active_effects": "shield_of_justice_active"}},
        )
        owner_doc = await scores_col.find_one({"user_id": amulet['owner_id']})
        owner_name = owner_doc.get('name', 'Таинственный вампир') if owner_doc else 'Таинственный вампир'
        return f" 🛡️ Щит Справедливости заблокировал Вампирский Амулет игрока {owner_name}!", new_balance
    owner_id = amulet['owner_id']
    stolen = int(base_change * 0.5)
    await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": -stolen}})
    await scores_col.update_one({"user_id": owner_id}, {"$inc": {"balance": stolen}}, upsert=True)
    new_balance = (new_balance - stolen) if isinstance(new_balance, (int, float)) else new_balance
    owner_doc = await scores_col.find_one({"user_id": owner_id})
    owner_name = owner_doc.get('name', 'Таинственный вампир') if owner_doc else 'Таинственный вампир'
    try:
        await bot.send_message(
            owner_id,
            f"🩸 Ваш Вампирский Амулет на игроке {(await scores_col.find_one({'user_id': user_id}) or {}).get('name', 'Anon')} принес вам {stolen} фишек с {game_name}!",
        )
    except:
        pass
    return f" 🩸 Вампирский Амулет {owner_name} забирает {stolen}.", new_balance

def format_effects_text(effects: list) -> str:
    return " ".join(effects)

async def broadcast_message(text: str, delay: float = 0.5):
    chat_ids = await get_all_chat_ids()
    for cid in chat_ids:
        try:
            await bot.send_message(cid, text)
            await asyncio.sleep(delay)
        except Exception as e:
            print(f"Broadcast to {cid} failed: {e}")

async def send_gambling_summary(chat_id: int):
    history = get_history(chat_id)
    if not history:
        await bot.send_message(chat_id, "🎰 Ставки не делались, день прошел впустую.")
        return
    clean = [m for m in list(history) if not m['content'].startswith('/')]
    top_text = await get_leaderboard_text()
    if not clean:
        await bot.send_message(chat_id, f"🎰 Ставки не делались, день прошел впустую.\n\n{top_text}")
        return
    text_dump = "\n".join([f"{m['name']}: {m['content']}" for m in clean])
    prompt = (
        f"{GAMBLING_SHOE_PROMPT} "
        "Подведи краткие итоги дня в казино. "
        "Обязательно упомяни таблицу лидеров. "
        "ВАЖНО: Напиши 2-3 предложения. "
        f"Вот переписка:\n{text_dump}\n\nА вот зал славы казино:\n{top_text}"
    )
    res = await ask_model([{"role": "user", "content": prompt}], temp=1.0)
    await bot.send_message(chat_id, f"💰 Итоги игрового дня:\n{res} 🎰")

async def get_zodiac(user_id: int, name: str):
    doc = await scores_col.find_one({"user_id": user_id})
    if doc and doc.get("zodiac"):
        return doc["zodiac"]
    return PLAYER_ZODIACS.get(name)

async def fetch_horoscope(sign: str):
    key = f"{sign}:{datetime.datetime.now(pytz.timezone('Europe/Moscow')).date().isoformat()}"
    if key in horoscope_cache:
        return horoscope_cache[key]
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                HOROSCOPE_API_URL,
                data={"sign": sign, "day": "today"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    horoscope_cache[key] = data
                    return data
                print(f"aztro API status {resp.status}")
    except Exception as e:
        print(f"aztro API error: {e}")
    rus = ZODIAC_RUS.get(sign, sign)
    res = await ask_model([{"role": "user", "content": f"Сгенерируй короткий гороскоп на сегодня (2-3 предложения) для знака {rus}."}], temp=1.0)
    data = {"description": res, "lucky_number": None, "lucky_time": None, "color": None, "mood": None}
    horoscope_cache[key] = data
    return data

async def generate_detailed_horoscope(name: str, query: str, sign: str):
    rus = ZODIAC_RUS.get(sign, sign)
    data = await fetch_horoscope(sign)
    base = data.get("description", "")
    prompt = (
        f"Игрок {name} со знаком {rus} написал: «{query}». "
        f"Краткий гороскоп дня: «{base}». "
        "Ответь ЕМУ лично, по-русски, в стиле мистического оракула. "
        "Если он о чём-то спросил — дай совет на сегодня на основе его знака. "
        "Если просто ответил/просит подробнее — дай развёрнутый гороскоп: карьера, деньги, любовь и стоит ли рисковать в казино. "
        "4-7 предложений, будь образным, но конкретным."
    )
    return await ask_model([{"role": "user", "content": prompt}], temp=1.0)

async def get_short_horoscope(sign: str, rus: str):
    today = datetime.datetime.now(pytz.timezone('Europe/Moscow')).date().isoformat()
    key = f"short:{sign}:{today}"
    if key in horoscope_cache:
        return horoscope_cache[key]
    data = await fetch_horoscope(sign)
    desc = data.get("description", "")
    short = await ask_model([{"role": "user", "content":
        f"Сократи этот гороскоп до ДВУХ коротких предложений (макс 15 слов на предложение), сохрани суть и мистический тон. Гороскоп для {rus}: {desc}"}], temp=0.7)
    if not short or short.startswith("Башмак") or len(short) > 300:
        parts = re.split(r'(?<=[.!?])\s+', desc.strip())
        short = " ".join(parts[:2]) if len(parts) > 1 else (parts[0] if parts else desc)
    horoscope_cache[key] = short
    return short

def deadlock_fortune(user_id: int, date_str: str):
    seed = int(hashlib.md5(f"{user_id}:{date_str}".encode()).hexdigest(), 16) % 101
    if seed >= 70:
        return f"звёзды благоволят апу ({seed}) — смело в катку!"
    elif seed >= 40:
        return f"звёзды не против апа ({seed}) — иди, но без хайп-решений"
    else:
        return f"ап сегодня не судьба ({seed}) — лучше потренируйся"

async def build_horoscope_message():
    emoji, name, verb = random.choice(MYSTIC_PREFIXES)
    signature = random.choice(MYSTIC_SIGNATURES)
    today = datetime.datetime.now(pytz.timezone('Europe/Moscow')).date().isoformat()
    bot_user = await bot.get_me()
    bot_id = bot_user.id

    cursor = scores_col.find({}, {"name": 1, "user_id": 1})
    players = await cursor.to_list(length=None)
    groups = {}
    for p in players:
        nm = p.get("name")
        uid = p.get("user_id")
        if not nm or uid == bot_id:
            continue
        sign = (await get_zodiac(uid, nm))
        if not sign:
            continue
        groups.setdefault(sign, []).append((nm, uid))
    if not groups:
        return None

    blocks = []
    for sign in ["aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"]:
        if sign not in groups:
            continue
        members = groups[sign]
        emj = ZODIAC_EMOJI.get(sign, "")
        rus = ZODIAC_RUS.get(sign, sign)
        short = await get_short_horoscope(sign, rus)
        data = await fetch_horoscope(sign)
        lucky = data.get("lucky_number")
        names_str = " & ".join(nm for nm, _ in members)
        extra = f" Счастливое число: {lucky}." if lucky else ""
        block = f"**{names_str} {emj} ({rus}):**\n{short}{extra}"
        dl_lines = []
        for nm, uid in members:
            if nm in DEADLOCK_PLAYERS:
                dl_lines.append(f"**{nm}** — {deadlock_fortune(uid, today)}")
        if dl_lines:
            block += "\n🎮 Deadlock: " + "; ".join(dl_lines)
        blocks.append(block)

    header = f"🌠 {emoji} **{name} {verb}...**"
    return header + "\n\n" + "\n\n".join(blocks) + f"\n\n*«{signature}»*"
