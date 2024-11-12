
# config.py - 配置文件
from dataclasses import dataclass
import os

@dataclass
class Config:
    # Telegram配置
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "123")
    API_ID: str = os.getenv("API_ID", "123")
    API_HASH: str = os.getenv("API_HASH", "123")
    PHONE_NUMBER: str = os.getenv("PHONE_NUMBER", "123")
    SESSION_NAME: str = os.getenv("SESSION_NAME", "forwarder_session")
    OWNER_ID: int = int(os.getenv("OWNER_ID", "123"))
    DATABASE_NAME: str = "forward_bot.db"
