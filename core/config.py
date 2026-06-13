import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    binance_api_key: str = field(default_factory=lambda: os.environ["BINANCE_API_KEY"])
    binance_api_secret: str = field(default_factory=lambda: os.environ["BINANCE_API_SECRET"])
    binance_testnet: bool = field(
        default_factory=lambda: os.getenv("BINANCE_TESTNET", "true").lower() == "true"
    )
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    db_url: str = field(default_factory=lambda: os.getenv("DB_URL", "sqlite:///db/trades.db"))
