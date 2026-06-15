import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    binance_testnet: bool = field(
        default_factory=lambda: os.getenv("BINANCE_TESTNET", "true").lower() == "true"
    )
    # Network-specific credentials — testnet and mainnet keys are DIFFERENT and not
    # interchangeable, so both pairs can be stored at once and the active one is picked
    # by `binance_testnet`. The legacy single-pair BINANCE_API_KEY / BINANCE_API_SECRET
    # is still honored as a fallback so older .env files keep working.
    binance_testnet_api_key: str = field(
        default_factory=lambda: os.getenv("BINANCE_TESTNET_API_KEY", "")
    )
    binance_testnet_api_secret: str = field(
        default_factory=lambda: os.getenv("BINANCE_TESTNET_API_SECRET", "")
    )
    binance_mainnet_api_key: str = field(
        default_factory=lambda: os.getenv("BINANCE_MAINNET_API_KEY", "")
    )
    binance_mainnet_api_secret: str = field(
        default_factory=lambda: os.getenv("BINANCE_MAINNET_API_SECRET", "")
    )
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    db_url: str = field(default_factory=lambda: os.getenv("DB_URL", "sqlite:///db/trades.db"))

    @property
    def binance_api_key(self) -> str:
        """Active API key for the selected network (testnet/mainnet), with legacy fallback."""
        specific = self.binance_testnet_api_key if self.binance_testnet else self.binance_mainnet_api_key
        return specific or os.getenv("BINANCE_API_KEY", "")

    @property
    def binance_api_secret(self) -> str:
        """Active API secret for the selected network (testnet/mainnet), with legacy fallback."""
        specific = self.binance_testnet_api_secret if self.binance_testnet else self.binance_mainnet_api_secret
        return specific or os.getenv("BINANCE_API_SECRET", "")

    def validate(self, paper_mode: bool, strategy_mode: str = "rule_based",
                 arbiter_mode: str = "rule") -> None:
        """Fail fast at startup if required secrets are missing, instead of crashing
        opaquely on the first signed API call. Paper mode needs no Binance keys."""
        errors: list[str] = []
        if not paper_mode:
            network = "testnet" if self.binance_testnet else "mainnet"
            if not self.binance_api_key or not self.binance_api_secret:
                errors.append(
                    f"Live trading on {network} requires Binance {network} API key + secret "
                    f"(set BINANCE_{network.upper()}_API_KEY / _SECRET in .env)"
                )
        if strategy_mode in ("hybrid", "claude_ai") or arbiter_mode == "claude":
            if not os.getenv("ANTHROPIC_API_KEY"):
                errors.append(
                    f"ANTHROPIC_API_KEY is required for STRATEGY_MODE={strategy_mode!r}"
                    f" / ARBITER_MODE={arbiter_mode!r}"
                )
        if errors:
            raise ValueError("Configuration error(s):\n  - " + "\n  - ".join(errors))
