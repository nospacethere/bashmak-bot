import asyncio, datetime, re, aiohttp
from aiogram import types
from aiogram.enums import ChatType
from aiogram.types import BufferedInputFile
from config import bot, dp, scores_col, chats_col, game_state_col, user_history
from utils import get_history, ask_model, download_video_rapid

@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.is_bot or not message.text or message.text.startswith('/') or (message.dice and message.dice.emoji in ['🎰', '⚽']):
        return

    cid = message.chat.id
    await chats_col.update_one({'chat_id': cid}, {'$set': {'last_seen': datetime.datetime.now(pytz.utc)}}, upsert=True)
    text = message.text

    url_pattern = r'https?://[^\s]+'
    found_urls = re.findall(url_pattern, text)
    url_to_download = found_urls[0] if found_urls else None

    if url_to_download and ("instagram.com/" in url_to_download or "tiktok.com/" in url_to_download or "vm.tiktok.com/" in url_to_download):
        await bot.send_chat_action(cid, "upload_video")
        video_info = await download_video_rapid(url_to_download)
        if video_info:
            v_url = video_info['url']
            width = video_info.get('width')
            height = video_info.get('height')
            for retry in range(3):
                try:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Referer": url_to_download,
                    }
                    async with aiohttp.ClientSession() as s:
                        async with s.get(v_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as r:
                            if r.status != 200:
                                print(f"CDN download attempt {retry + 1} status {r.status}")
                                await asyncio.sleep(2)
                                continue
                            video_content = await r.read()
                            if len(video_content) < 50 * 1024 * 1024:
                                await message.reply_video(
                                    BufferedInputFile(video_content, filename="v.mp4"),
                                    caption="😼 Стырил",
                                    width=width,
                                    height=height,
                                )
                            else:
                                await message.reply("Видео слишком большое для отправки. 😼")
                            return
                except Exception as e:
                    print(f"CDN download attempt {retry + 1} error: {e}")
                    await asyncio.sleep(2)
            await message.reply("Не удалось загрузить видео, которое вернул API. 😼")
        else:
            await message.reply("Не удалось скачать это видео. Либо ссылка битая, либо оно защищено. 😼")
        return

    gs = await game_state_col.find_one()
    if gs and gs.get("game_ended"):
        return

    history = get_history(cid)
    history.append({'role': 'user', 'name': message.from_user.first_name, 'content': text})
    try:
        await scores_col.update_one(
            {"user_id": message.from_user.id},
            {"$set": {"name": message.from_user.first_name}},
            upsert=False,
        )
    except:
        pass

    bot_obj = await bot.get_me()
    is_named = bot_obj.username.lower() in text.lower()
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == bot_obj.id
    if not (message.chat.type == ChatType.PRIVATE or is_named or is_reply):
        return

    from config import ROLES
    selected_role = ROLES[0]
    limited_history = list(history)[-6:]
    messages_for_ai = [{"role": "system", "content": selected_role['prompt']}] + limited_history
    reply = await ask_model(messages_for_ai)
    history.append({'role': 'assistant', 'content': reply})
    await message.reply(reply)
