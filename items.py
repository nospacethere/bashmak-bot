import asyncio, datetime, random, pytz
from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from config import bot, scores_col, inventories_col, amulets_col, game_state_col, ITEMS, ADMIN_ID
from utils import get_all_chat_ids, broadcast_message, handle_vampire_amulet, format_effects_text

async def execute_bot_single_item(item_key: str):
    bot_user = await bot.get_me()
    bot_id = bot_user.id
    item_info = ITEMS[item_key]
    announcement = None

    if item_key == "chaos_cube":
        roll = random.randint(1, 6)
        all_ids = await get_all_chat_ids()
        victims = [uid for uid in all_ids if uid != bot_id]
        if not victims:
            return
        victim_id = random.choice(victims)
        victim_doc = await scores_col.find_one({"user_id": victim_id})
        if not victim_doc:
            return
        actual_roll = min(roll, victim_doc.get("balance", 0))
        if actual_roll <= 0:
            return
        if "shield_of_justice_active" in victim_doc.get("active_effects", []):
            await scores_col.update_one(
                {"user_id": victim_id},
                {"$pull": {"active_effects": "shield_of_justice_active"}},
            )
            announcement = (
                f"😼 Башмак использовал {item_info['name']}!\n\n"
                f"Жертва: {victim_doc['name']}, но его Щит Справедливости заблокировал атаку! Щит разрушен."
            )
        else:
            await scores_col.update_one({"user_id": bot_id}, {"$inc": {"balance": actual_roll}})
            await scores_col.update_one({"user_id": victim_id}, {"$inc": {"balance": -actual_roll}})
            bd = await scores_col.find_one({"user_id": bot_id})
            vd = await scores_col.find_one({"user_id": victim_id})
            announcement = (
                f"😼 Башмак использовал {item_info['name']}!\n\n"
                f"Жертва: {victim_doc['name']}, украдено {actual_roll} фишек.\n"
                f"Баланс Башмака: {bd.get('balance', 'N/A')}\n"
                f"Баланс {victim_doc['name']}: {vd.get('balance', 'N/A')}"
            )

    elif item_key == "golden_boot":
        dv = random.randint(1, 5)
        change = 10 if dv in (1, 4, 5) else -10
        await scores_col.update_one({"user_id": bot_id}, {"$inc": {"balance": change}})
        bd = await scores_col.find_one({"user_id": bot_id})
        result = "забивает гол и получает +10" if change > 0 else "промахивается и теряет 10"
        announcement = (
            f"😼 Башмак использовал {item_info['name']}!\n\n"
            f"Кот {result} фишек.\n"
            f"Баланс: {bd.get('balance', 'N/A')} ⚽️"
        )

    elif item_key == "madness_coin":
        await scores_col.update_one(
            {"user_id": bot_id},
            {"$addToSet": {"active_effects": "madness_coin"}},
            upsert=True,
        )
        announcement = (
            f"😼 Башмак использовал {item_info['name']}!\n\n"
            f"Следующий спин будет безумным. 🌓"
        )

    elif item_key == "double_down":
        await scores_col.update_one(
            {"user_id": bot_id},
            {"$addToSet": {"active_effects": "double_down"}},
            upsert=True,
        )
        announcement = (
            f"😼 Башмак использовал {item_info['name']}!\n\n"
            f"Следующий спин удвоен. ⏫"
        )

    elif item_key == "money_pouch":
        await scores_col.update_one({"user_id": bot_id}, {"$inc": {"balance": 10}})
        bd = await scores_col.find_one({"user_id": bot_id})
        announcement = (
            f"😼 Башмак использовал {item_info['name']}!\n\n"
            f"Кот нашёл 10 фишек! Баланс: {bd.get('balance', 'N/A')} 💰"
        )

    elif item_key == "stone_rain":
        all_ids = await get_all_chat_ids()
        for uid in all_ids:
            if uid == bot_id:
                continue
            change = random.randint(-5, 5)
            if change > 0:
                await scores_col.update_one({"user_id": uid}, {"$inc": {"balance": change}})
            elif change < 0:
                doc = await scores_col.find_one({"user_id": uid})
                actual = min(abs(change), doc.get("balance", 0)) if doc else 0
                if actual > 0:
                    await scores_col.update_one({"user_id": uid}, {"$inc": {"balance": -actual}})
        bd = await scores_col.find_one({"user_id": bot_id})
        announcement = (
            f"😼 Башмак использовал {item_info['name']}!\n\n"
            f"Дождь из камней прошёлся по всем!\n"
            f"Баланс кота: {bd.get('balance', 'N/A')} 🌧️"
        )

    if announcement:
        await broadcast_message(announcement, delay=0.5)

async def use_item_logic(user: types.User, item_key: str, context_message: types.Message):
    user_id = user.id
    user_name = user.first_name

    gs = await game_state_col.find_one()
    if gs and gs.get("game_ended"):
        await context_message.answer("🏁 Сезон окончен, предметы больше не работают. Ждите новый сезон! 🎰")
        return
    if item_key not in ITEMS:
        await context_message.answer(f"Неверный предмет. Доступные: {', '.join(ITEMS.keys())}")
        return

    inv_doc = await inventories_col.find_one({"user_id": user_id})
    if not inv_doc or item_key not in inv_doc.get("items", []):
        await context_message.answer("У вас нет такого предмета. 😕")
        return

    inv_doc["items"].remove(item_key)
    await inventories_col.update_one({"user_id": user_id}, {"$set": {"items": inv_doc["items"]}}, upsert=True)

    if item_key == "money_pouch":
        await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": 10}}, upsert=True)
        ud = await scores_col.find_one({"user_id": user_id})
        nb = ud.get('balance', 10) if ud else 10
        await context_message.answer(f"💰 Вы использовали Мешочек мелочи и получили +10 фишек! Ваш баланс: {nb}")

    elif item_key == "golden_boot":
        await scores_col.update_one(
            {"user_id": user_id},
            {"$addToSet": {"active_effects": "golden_boot_active"}},
            upsert=True,
        )
        await context_message.answer("⚽️ Вы использовали Золотой Бутс! Теперь кидайте эмодзи ⚽, чтобы ударить по воротам.")

    elif item_key == "chaos_cube":
        all_players = await scores_col.find({"user_id": {"$nin": [user_id]}}, {"user_id": 1, "name": 1}).to_list(length=None)
        players = [p for p in all_players if p.get('user_id') and p.get('user_id') != user_id]
        if not players:
            await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": item_key}}, upsert=True)
            await context_message.answer("В казино больше нет игроков, чтобы стать жертвой хаоса. 🎲")
            return
        victim = random.choice(players)
        victim_id = victim['user_id']
        roll = random.randint(1, 6)
        victim_doc = await scores_col.find_one({"user_id": victim_id})
        actual_roll = min(roll, victim_doc.get("balance", 0)) if victim_doc else 0
        if actual_roll <= 0:
            await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": item_key}}, upsert=True)
            await context_message.answer("У жертвы нет фишек для кражи. 🎲")
            return
        if victim_doc and "shield_of_justice_active" in victim_doc.get("active_effects", []):
            await scores_col.update_one(
                {"user_id": victim_id},
                {"$pull": {"active_effects": "shield_of_justice_active"}},
            )
            await context_message.answer(
                f"🎲 Кубик Хаоса попытался ударить по игроку {victim_doc['name']}, "
                f"но его {roll} фишек были заблокированы Щитом Справедливости! 🛡️"
            )
        else:
            await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": actual_roll}})
            await scores_col.update_one({"user_id": victim_id}, {"$inc": {"balance": -actual_roll}})
            user_doc_after = await scores_col.find_one({"user_id": user_id})
            victim_doc_after = await scores_col.find_one({"user_id": victim_id})
            await context_message.answer(
                f"🎲 Кубик Хаоса в действии!\n"
                f"Вы выбросили {roll}. {actual_roll} фишек переходят от игрока {victim_doc['name']} к вам.\n"
                f"Ваш баланс: {user_doc_after['balance'] if user_doc_after else 'N/A'}\n"
                f"Баланс {victim_doc['name']}: {victim_doc_after['balance'] if victim_doc_after else 'N/A'}"
            )

    elif item_key == "madness_coin":
        await scores_col.update_one(
            {"user_id": user_id},
            {"$addToSet": {"active_effects": "madness_coin"}},
            upsert=True,
        )
        await context_message.answer("🌓 Вы использовали Монету Безумия! Ваш следующий спин определит судьбу. Удачи... или нет. 😈")

    elif item_key == "double_down":
        await scores_col.update_one(
            {"user_id": user_id},
            {"$addToSet": {"active_effects": "double_down"}},
            upsert=True,
        )
        await context_message.answer(
            "⏫ Вы использовали Двойную Ставку! Ваш следующий спин будет стоить вдвое дороже... или принесет вдвое больше. Риск — благородное дело! 🎰"
        )

    elif item_key == "stone_rain":
        all_players = await scores_col.find({}, {"user_id": 1, "name": 1}).to_list(length=None)
        players = [p for p in all_players if p.get('user_id') and p.get('user_id') != user_id]
        if not players:
            await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": item_key}}, upsert=True)
            await context_message.answer("В казино нет игроков, чтобы устроить апокалипсис. 🌧️")
            return
        results = []
        for p in players:
            change = random.randint(-5, 5)
            pid = p['user_id']
            pdoc = await scores_col.find_one({"user_id": pid})
            if not pdoc:
                continue
            if change >= 0:
                await scores_col.update_one({"user_id": pid}, {"$inc": {"balance": change}})
                nb = (pdoc.get("balance", 0) or 0) + change
                results.append(f"{p['name']}: +{change} (итого: {nb})")
            else:
                actual = min(abs(change), pdoc.get("balance", 0) or 0)
                if actual > 0:
                    await scores_col.update_one({"user_id": pid}, {"$inc": {"balance": -actual}})
                    nb = (pdoc.get("balance", 0) or 0) - actual
                    results.append(f"{p['name']}: -{actual} (итого: {nb})")
                else:
                    results.append(f"{p['name']}: 0 (итого: {pdoc.get('balance', 0)})")

        summary_message = "🌧️ Дождь из камней прошёлся по казино!\n\n" + "\n".join(results)
        await context_message.answer(summary_message)

    elif item_key == "leaky_pocket":
        top_cursor = scores_col.find().sort("balance", -1).limit(1)
        top = await top_cursor.to_list(length=1)
        if not top:
            await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": item_key}}, upsert=True)
            await context_message.answer("В казино больше некого обчищать. 🤏")
            return
        top_player = top[0]
        top_player_id = top_player['user_id']
        top_player_name = top_player.get('name', 'Аноним')
        top_balance = top_player.get("balance", 0)
        if top_player_id == user_id:
            await context_message.answer("Вы и так самый богатый. Некого обворовывать. 🤏")
            return
        if random.random() < 0.3:
            user_doc = await scores_col.find_one({"user_id": user_id})
            if not user_doc:
                return
            lose_amount = int(user_doc.get('balance', 0) * 0.15)
            if lose_amount <= 0:
                await context_message.answer("Вы попытались обокрасть кого-то, но вас поймали! К счастью, у вас и красть нечего. 💨")
                return
            if "shield_of_justice_active" in user_doc.get("active_effects", []):
                await scores_col.update_one(
                    {"user_id": user_id},
                    {"$pull": {"active_effects": "shield_of_justice_active"}},
                )
                await context_message.answer(f"🤏 Вас поймали за руку, но Щит Справедливости защитил вас от потери фишек! Щит разрушен. 🛡️")
                return
            await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": -lose_amount}})
            await scores_col.update_one({"user_id": top_player_id}, {"$inc": {"balance": lose_amount}}, upsert=True)
            await context_message.answer(
                f"🤏 Вас поймали! Вы отдали {lose_amount} фишек игроку {top_player_name}.\n"
                f"Ваш баланс: {(await scores_col.find_one({'user_id': user_id})).get('balance', 'N/A')} 💨"
            )
        else:
            if top_balance <= 0:
                await context_message.answer(f"🤏 Вы попытались обокрасть {top_player_name}, но у него в карманах ветер свищет! Ничего не вышло. 💨")
                return
            if "shield_of_justice_active" in top_player.get("active_effects", []):
                await scores_col.update_one(
                    {"user_id": top_player_id},
                    {"$pull": {"active_effects": "shield_of_justice_active"}},
                )
                await context_message.answer(f"🤏 Вы попытались стащить фишки у {top_player_name}, но его Щит Справедливости заблокировал кражу! Щит цели разрушен. 🛡️")
                return
            steal_amount = int(top_balance * 0.15)
            if steal_amount <= 0:
                await context_message.answer(f"🤏 Вы попытались обокрасть {top_player_name}, но у него в карманах ветер свищет! Ничего не вышло. 💨")
                return
            await scores_col.update_one({"user_id": top_player_id}, {"$inc": {"balance": -steal_amount}})
            await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": steal_amount}})
            await context_message.answer(
                f"🤏 Вы обокрали {top_player_name} на {steal_amount} фишек!\n"
                f"Ваш баланс: {(await scores_col.find_one({'user_id': user_id})).get('balance', 'N/A')} 🏆"
            )

    elif item_key == "generous_jackpot":
        all_players = await scores_col.find({}, {"user_id": 1, "name": 1}).to_list(length=None)
        others = [p for p in all_players if p.get('user_id') and p.get('user_id') != user_id]
        await scores_col.update_one({"user_id": user_id}, {"$inc": {"balance": 10}}, upsert=True)
        update_summary = [f"Вы получили +10 фишек (итого: {(await scores_col.find_one({'user_id': user_id})).get('balance', 'N/A')})."]
        for p in others:
            pid = p['user_id']
            amount = random.randint(1, 5)
            await scores_col.update_one({"user_id": pid}, {"$inc": {"balance": amount}})
            pd = await scores_col.find_one({"user_id": pid})
            update_summary.append(f"{p['name']} получил +{amount} фишек (итого: {pd.get('balance', 'N/A') if pd else 'N/A'}).")
        summary_message = "🎉 Вы использовали Щедрый Джекпот! 🎉\n\n" + "\n".join(update_summary)
        await context_message.answer(summary_message)

    elif item_key == "vampiric_amulet":
        all_players = await scores_col.find(
            {"user_id": {"$nin": [user_id]}}, {"user_id": 1, "name": 1}
        ).to_list(length=None)
        players = [p for p in all_players if p.get('user_id')]
        if not players:
            await inventories_col.update_one({"user_id": user_id}, {"$push": {"items": item_key}}, upsert=True)
            await context_message.answer("🩸 В казино больше нет игроков, чтобы выпить их кровь... то есть, фишки. 🧛")
            return
        victim = random.choice(players)
        victim_id = victim['user_id']
        victim_name = victim.get('name', 'Аноним')
        victim_doc = await scores_col.find_one({"user_id": victim_id})
        if victim_doc and "shield_of_justice_active" in victim_doc.get("active_effects", []):
            await scores_col.update_one(
                {"user_id": victim_id},
                {"$pull": {"active_effects": "shield_of_justice_active"}},
            )
            await context_message.answer(
                f"🩸 Вы попытались повесить Вампирский Амулет на игрока {victim_name}, но его Щит Справедливости уничтожил амулет! Щит цели разрушен. 🛡️"
            )
            return
        expires_at = datetime.datetime.now(pytz.utc) + datetime.timedelta(hours=24)
        await amulets_col.insert_one({"owner_id": user_id, "victim_id": victim_id, "expires_at": expires_at})
        await context_message.answer(
            f"🩸 Вы повесили Вампирский Амулет на игрока {victim_name}! Следующие 24 часа вы будете получать 50% от всех его выигрышей. 🧛"
        )

    elif item_key == "shield_of_justice":
        await scores_col.update_one(
            {"user_id": user_id},
            {"$addToSet": {"active_effects": "shield_of_justice_active"}},
            upsert=True,
        )
        await context_message.answer("🛡️ Вы активировали Щит Справедливости! Он защитит вас от следующего негативного эффекта.")
