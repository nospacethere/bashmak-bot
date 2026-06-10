import asyncio, datetime, random, pytz
import config
from utils import get_all_chat_ids, get_leaderboard_text, broadcast_message, send_gambling_summary, handle_vampire_amulet
from items import execute_bot_single_item

def schedule_bot_spins():
    now_moscow = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
    h1, m1 = random.randint(9, 12), random.randint(0, 59)
    t1 = now_moscow.replace(hour=h1, minute=m1, second=0, microsecond=0)
    if t1 <= now_moscow:
        t1 += datetime.timedelta(days=1)
    config.bot_spin_time_1 = t1
    h2, m2 = random.randint(18, 21), random.randint(0, 59)
    t2 = now_moscow.replace(hour=h2, minute=m2, second=0, microsecond=0)
    if t2 <= now_moscow:
        t2 += datetime.timedelta(days=1)
    config.bot_spin_time_2 = t2
    print(f"[{datetime.datetime.now()}] Bot spins scheduled. Spin 1: {config.bot_spin_time_1}, Spin 2: {config.bot_spin_time_2} MSK")

async def execute_bot_spin():
    bot_user = await config.bot.get_me()
    bot_id = bot_user.id
    sc = await config.spin_counts_col.find_one({'user_id': bot_id})
    spin_count = sc.get('count', 0) if sc else 0
    if spin_count >= 2:
        print(f"[{datetime.datetime.now()}] Bot has already spun twice today.")
        return
    all_ids = await get_all_chat_ids()
    if not all_ids:
        print(f"[{datetime.datetime.now()}] No active chats for bot spin.")
        return

    dice_value = random.randint(1, 64)
    from utils import calculate_win
    change = calculate_win(dice_value)

    bot_doc = await config.scores_col.find_one({'user_id': bot_id})
    if not bot_doc:
        await config.scores_col.update_one({"user_id": bot_id}, {"$set": {"name": "Гемблинг Башмак", "balance": 100}}, upsert=True)
        bot_doc = await config.scores_col.find_one({'user_id': bot_id})

    final_change = change
    active_effects = bot_doc.get('active_effects', [])
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
    await config.scores_col.update_one({'user_id': bot_id}, update_query)
    await config.spin_counts_col.update_one({'user_id': bot_id}, {'$inc': {'count': 1}}, upsert=True)

    bot_doc_after = await config.scores_col.find_one({'user_id': bot_id})
    new_balance = bot_doc_after.get("balance", "N/A") if bot_doc_after else "N/A"

    if change > 0 and bot_doc_after:
        amulet_msg, new_balance = await handle_vampire_amulet(bot_id, change, new_balance, bot_doc_after, "спина Башмака")
        if amulet_msg:
            effect_msgs.append(amulet_msg)

    full_msg = " ".join(effect_msgs)
    if full_msg:
        message_text = (f"🎲 Гемблинг Башмак делает свой ход! 🎲\n\n"
                        f"{full_msg}\n"
                        f"Итог: {final_change}. Баланс: {new_balance} фишек. 😼")
    else:
        if change >= 10:
            result_text = f"сорвал крупный куш в {change} фишек!"
        elif change > 0:
            result_text = f"выиграл {change} фишки."
        else:
            result_text = f"проиграл {abs(change)} фишек."
        message_text = (f"🎲 Гемблинг Башмак делает свой ход! 🎲\n\n"
                        f"Кот-крупье {result_text}\n"
                        f"Теперь его баланс: {new_balance} фишек. 😼")

    for cid in all_ids:
        try:
            await config.bot.send_message(cid, message_text)
            await asyncio.sleep(0.3)
        except Exception as e:
            print(f"Failed to send bot spin to chat {cid}: {e}")

async def execute_bot_item_use():
    print(f"[{datetime.datetime.now()}] Attempting to execute bot item use.")
    bot_user = await config.bot.get_me()
    bot_id = bot_user.id
    inv_doc = await config.inventories_col.find_one({"user_id": bot_id})
    if not inv_doc or not inv_doc.get("items"):
        print(f"[{datetime.datetime.now()}] Bot has no items to use.")
        return
    usable = ["chaos_cube", "money_pouch", "stone_rain", "golden_boot", "madness_coin", "double_down"]
    inv_items = [k for k in inv_doc["items"] if k in usable]
    if not inv_items:
        print(f"[{datetime.datetime.now()}] Bot has no usable items.")
        return
    item_key = random.sample(inv_items, k=min(1, len(inv_items)))[0]
    inv_doc["items"].remove(item_key)
    await config.inventories_col.update_one({"user_id": bot_id}, {"$set": {"items": inv_doc["items"]}})
    await execute_bot_single_item(item_key)

async def distribute_daily_items_and_announce():
    print(f"[{datetime.datetime.now()}] Distributing daily items.")
    bot_user = await config.bot.get_me()
    bot_id = bot_user.id
    cursor = config.scores_col.find({}, {"user_id": 1, "name": 1})
    players = await cursor.to_list(length=None)
    for p in players:
        if p.get('user_id') and p['user_id'] != bot_id:
            item_key = random.choice(list(config.ITEMS.keys()))
            await config.inventories_col.update_one({"user_id": p['user_id']}, {"$push": {"items": item_key}}, upsert=True)
            await config.bot.send_message(
                p['user_id'],
                f"🎁 Ваш ежедневный бонус: {config.ITEMS[item_key]['name']}!\n"
                f"Проверьте свой /inventory, чтобы узнать, что вам досталось! 🎰",
            )
            await asyncio.sleep(0.3)
    await broadcast_message(
        f"🎁 Башмак раздал ежедневные предметы! Проверьте /inventory, чтобы узнать, что выпало вам! 🎰",
        delay=0.5,
    )

async def run_chaos_event():
    print(f"[{datetime.datetime.now()}] Running chaos event.")
    bot_user = await config.bot.get_me()
    bot_id = bot_user.id
    cursor = config.scores_col.find({"user_id": {"$ne": bot_id}}, {"user_id": 1, "name": 1, "balance": 1})
    players = await cursor.to_list(length=None)
    if not players:
        return
    chosen = random.sample(players, k=min(5, len(players)))
    results = []
    for p in chosen:
        roll = random.randint(1, 6)
        pid = p['user_id']
        doc = await config.scores_col.find_one({"user_id": pid})
        if not doc:
            continue
        if "shield_of_justice_active" in doc.get("active_effects", []):
            await config.scores_col.update_one({"user_id": pid}, {"$pull": {"active_effects": "shield_of_justice_active"}})
            results.append(f"{p['name']}: Щит Справедливости заблокировал атаку! 🛡️")
        else:
            actual = min(roll, doc.get("balance", 0))
            if actual > 0:
                await config.scores_col.update_one({"user_id": pid}, {"$inc": {"balance": -actual}})
                results.append(f"{p['name']}: -{actual} фишек (осталось: {(await config.scores_col.find_one({'user_id': pid})).get('balance', 0)})")
            else:
                results.append(f"{p['name']}: 0 фишек (и так пусто)")
    msg = "🌪️ Парад Хаоса начался!\n\n" + "\n".join(results) + "\n\nПусть начнется безумие! Проверьте свой /inventory. 🎰"
    await broadcast_message(msg, delay=0.5)
    await config.game_state_col.update_one({}, {"$set": {"chaos_cube_event_done": True}})

async def reset_daily_state():
    print(f"[{datetime.datetime.now()}] Resetting daily spin counts.")
    await config.spin_counts_col.delete_many({})
    schedule_bot_spins()
    print(f"[{datetime.datetime.now()}] Daily spin counts have been reset.")

async def cleanup_expired_amulets():
    now = datetime.datetime.now(pytz.utc)
    result = await config.amulets_col.delete_many({"expires_at": {"$lt": now}})
    if result.deleted_count:
        print(f"[{datetime.datetime.now()}] Cleaned up {result.deleted_count} expired amulets.")

async def end_game_action():
    print(f"[{datetime.datetime.now()}] Game season of 14 days has ended.")
    gs = await config.game_state_col.find_one()
    season_number = gs.get("season_number", "?") if gs else "?"
    top_text = await get_leaderboard_text()
    cursor = config.scores_col.find().sort("balance", -1).limit(10)
    top_players = [{"name": p.get("name", "Anon"), "balance": p.get("balance", 0)} async for p in cursor]
    await config.hof_col.insert_one({
        "season_number": season_number,
        "ended_at": datetime.datetime.now(pytz.utc),
        "top_players": top_players,
    })
    print(f"Saved Hall of Fame for season {season_number}")
    announcement = (
        f"🎉 Гемблинг Лига Башмака №{season_number} завершена! 🎉\n\n"
        f"14 дней пролетели как один миг!\n\n"
        f"А вот и наши легенды, сорвавшие куш:\n{top_text}\n\n"
        f"Игра остановлена — больше нельзя делать ставки и использовать предметы.\n"
        f"Админ может сбросить всё командой /admin_wipe_scores_777, чтобы начать новый сезон. 🎰"
    )
    await broadcast_message(announcement, delay=0.5)
    await config.game_state_col.update_one({}, {"$set": {"game_ended": True}}, upsert=True)
    print(f"[{datetime.datetime.now()}] Game marked as ended. Data preserved for admin wipe.")

async def scheduler():
    print("Scheduler starting...")
    try:
        await config.game_state_col.update_one({}, {"$setOnInsert": {"last_daily_reset_date": None}}, upsert=True)
    except Exception as e:
        print(f"Scheduler init DB error: {e}")

    while True:
        try:
            now_moscow = datetime.datetime.now(pytz.timezone('Europe/Moscow'))
            today_str = now_moscow.date().isoformat()
            gs = await config.game_state_col.find_one()

            if gs and gs.get("game_ended"):
                await asyncio.sleep(3600)
                continue
            if not gs or 'start_date' not in gs:
                await asyncio.sleep(30)
                continue

            start_date = gs.get('start_date')
            if not start_date:
                await asyncio.sleep(30)
                continue

            current_day = (now_moscow.replace(tzinfo=None) - start_date).days + 1
            if current_day > 14:
                if not gs.get("game_ended"):
                    await end_game_action()
                await asyncio.sleep(3600)
                continue

            if current_day >= 4 and now_moscow.hour == 12 and not gs.get("chaos_cube_event_done"):
                await run_chaos_event()

            last_reset = gs.get("last_daily_reset_date")
            if last_reset is None or last_reset != today_str:
                print(f"[{datetime.datetime.now()}] New day detected ({today_str}). Previous reset: {last_reset}.")
                all_cids = await get_all_chat_ids()
                for cid in all_cids:
                    try:
                        await send_gambling_summary(cid)
                    except Exception as e:
                        print(f"Failed to send summary to {cid}: {e}")
                await reset_daily_state()
                await distribute_daily_items_and_announce()
                for cid in list(config.user_history.keys()):
                    config.user_history[cid].clear()
                await config.game_state_col.update_one({}, {"$set": {"last_daily_reset_date": today_str}})
                print(f"[{datetime.datetime.now()}] All daily tasks completed for {today_str}.")

            if now_moscow.minute % 10 == 0 and config._amulet_cleanup_run_minute != now_moscow.minute:
                await cleanup_expired_amulets()
                config._amulet_cleanup_run_minute = now_moscow.minute

            noon_key = f"noon_task_done_{today_str}"
            if now_moscow.hour == 12 and not gs.get(noon_key):
                print(f"[{datetime.datetime.now()}] Triggering bot item use.")
                await execute_bot_item_use()
                await config.game_state_col.update_one({}, {"$set": {noon_key: True}})

            if config.bot_spin_time_1 and now_moscow >= config.bot_spin_time_1:
                print(f"[{datetime.datetime.now()}] Triggering bot spin 1.")
                await execute_bot_spin()
                config.bot_spin_time_1 = None
            if config.bot_spin_time_2 and now_moscow >= config.bot_spin_time_2:
                print(f"[{datetime.datetime.now()}] Triggering bot spin 2.")
                await execute_bot_spin()
                config.bot_spin_time_2 = None

            await asyncio.sleep(30)
        except Exception as e:
            print(f"!!!FATAL SCHEDULER ERROR: {e}!!!")
            await asyncio.sleep(60)
