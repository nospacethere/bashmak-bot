import os, datetime, pytz
from aiogram import Bot, Dispatcher
from groq import AsyncGroq
from motor.motor_asyncio import AsyncIOMotorClient

TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
RAPID_KEY = os.getenv("RAPIDAPI_KEY")
MONGO_URL = os.getenv("MONGO_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

bot = Bot(token=TOKEN)
dp = Dispatcher()

client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

mongo_client = AsyncIOMotorClient(MONGO_URL, tlsAllowInvalidCertificates=True)
db = mongo_client['bashmak_db']
scores_col = db['scores']
inventories_col = db['inventories']
spin_counts_col = db['spin_counts']
game_state_col = db['game_state']
amulets_col = db['amulets']
chats_col = db['chats']
hof_col = db['hall_of_fame']

ITEMS = {
    "chaos_cube": {"name": "🎲 Кубик Хаоса", "description": "Вычитает случайное число (1-6) у случайного игрока и добавляет вам.", "requires_target": False},
    "madness_coin": {"name": "🌓 Монета Безумия", "description": "Применяет к следующему спину один из двух эффектов (50/50): либо отменяет проигрыш, либо отменяет выигрыш.", "requires_target": False},
    "money_pouch": {"name": "💰 Мешочек мелочи", "description": "Мгновенно дает +10 фишек.", "requires_target": False},
    "golden_boot": {"name": "⚽ Золотой Бутс", "description": "Запускает мини-игру с ударом по воротам. Попадание +10, промах -10.", "requires_target": False},
    "stone_rain": {"name": "🌧️ Дождь из камней", "description": "Изменяет баланс фишек всех игроков на случайное значение от -5 до 5.", "requires_target": False},
    "leaky_pocket": {"name": "🤏 Дырявый карман", "description": "Попытка украсть 15% фишек у самого богатого игрока. С шансом 30% вы отдадите 15% своих фишек ему.", "requires_target": False},
    "generous_jackpot": {"name": "🎉 Щедрый Джекпот", "description": "Вы получаете +10 фишек, а все остальные игроки — от 1 до 5 фишек.", "requires_target": False},
    "double_down": {"name": "⏫ Двойная Ставка", "description": "Активируйте перед спином, чтобы удвоить и выигрыш, и проигрыш.", "requires_target": False},
    "vampiric_amulet": {"name": "🩸 Вампирский Амулет", "description": "Вешается на случайного игрока. 24 часа вы получаете 50% от его выигрышей.", "requires_target": False},
    "shield_of_justice": {"name": "🛡️ Щит Справедливости", "description": "Защищает от следующей атаки или негативного события. Срабатывает автоматически.", "requires_target": False}
}

RAPID_APIS = [
    {"host": "social-download-all-in-one.p.rapidapi.com", "path": "/v1/social/autolink"},
    {"host": "social-media-video-downloader.p.rapidapi.com", "path": "/v1/video/download"},
]

GAMBLING_SHOE_PROMPT = "Ты — Гемблинг Башмак, азартный и рисковый кот. Весь мир для тебя — казино. Говори об удаче, ставках, риске и джекпотах. Используй сленг казино (фишки, олл-ин, джекпот, ставка, спин) и всегда будь готов поставить всё на кон. Ты немного циничен и саркастичен."
ROLES = [{"name": "Гемблинг Башмак", "emoji": "🎰", "prompt": GAMBLING_SHOE_PROMPT}]

SKIP_DELETE_PREFIXES = ("🏆 Зал славы казино", "🎲 Гемблинг Башмак делает свой ход!", "😼")

user_history: dict = {}
bot_spin_time_1 = None
bot_spin_time_2 = None
_amulet_cleanup_run_minute = -1


