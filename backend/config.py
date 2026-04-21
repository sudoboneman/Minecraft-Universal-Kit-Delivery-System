import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DAILY_FREE_TOKENS = int(os.getenv('DAILY_FREE_TOKENS', 50))
    WHETHER_DAILY_FREE_TOKENS_EXPIRE = os.getenv('WHETHER_DAILY_FREE_TOKENS_EXPIRE', 'false').lower() == 'true'
    COOLDOWN_BETWEEN_ORDERS = int(os.getenv('COOLDOWN_BETWEEN_ORDERS', 60))
    MAX_ORDER_QTY = int(os.getenv('MAX_ORDER_QTY', 3))
    DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    ACTIVE_CHANNEL_ID = int(os.getenv('ACTIVE_CHANNEL_ID', 0))
    GUILD_ID = int(os.getenv('GUILD_ID', 0))
    OWNER_USER_ID = int(os.getenv('OWNER_USER_ID', 0))
    OWNER_IGN = os.getenv('OWNER_IGN', '')
    WORKER_URL = os.getenv('WORKER_URL', 'http://localhost:3003')
    INVITE_REWARD = int(os.getenv('INVITE_REWARD', 1))