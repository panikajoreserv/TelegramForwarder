# config.py
from dataclasses import dataclass
import os
from dotenv import load_dotenv

# 加载.env文件
load_dotenv()

@dataclass
class Config:
    # Telegram配置
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN")
    API_ID: str = os.getenv("API_ID")
    API_HASH: str = os.getenv("API_HASH") 
    PHONE_NUMBER: str = os.getenv("PHONE_NUMBER")
    SESSION_NAME: str = os.getenv("SESSION_NAME", "forwarder_session")
    OWNER_ID: int = int(os.getenv("OWNER_ID", "0"))
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "forward_bot.db")
    # 默认语言设置
    DEFAULT_LANGUAGE: str = os.getenv("DEFAULT_LANGUAGE", "en")

    def __post_init__(self):
        """验证必要的配置是否存在"""
        required_fields = [
            "TELEGRAM_TOKEN",
            "API_ID", 
            "API_HASH",
            "PHONE_NUMBER",
            "OWNER_ID"
        ]
        
        missing_fields = [
            field for field in required_fields 
            if not getattr(self, field)
        ]
        
        if missing_fields:
            raise ValueError(
                f"Missing required configuration: {', '.join(missing_fields)}\n"
                "Please check your .env file."
            )

        # 确保OWNER_ID是有效的数字
        try:
            self.OWNER_ID = int(self.OWNER_ID)
        except ValueError:
            raise ValueError("OWNER_ID must be a valid integer")