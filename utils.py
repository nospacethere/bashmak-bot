import asyncio, datetime, aiohttp
from collections import deque
from config import bot, scores_col, chats_col, amulets_col, game_state_col, user_history, RAPID_KEY, RAPID_APIS, client, SKIP_DELETE_PREFIXES, GAMBLING_SHOE_PROMPT

def get_history(chat_id: int):
    if chat_id not in user_history:
        user_history[chat_id] = deque(maxlen=100)
    return user_history[chat_id]

async def get_casino_chat_id():
    gs = await game_state_col.find_one()
    return gs.get("casino_chat_id") if gs else None

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
