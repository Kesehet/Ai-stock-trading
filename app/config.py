from enum import StrEnum
from pathlib import Path
from tempfile import gettempdir

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppMode(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


LIVE_CONFIRMATION_PHRASE = "I_UNDERSTAND_THIS_CAN_PLACE_REAL_ORDERS"


def _heartbeat_path() -> str:
    return str(Path(gettempdir()) / "ai-stock-trading-heartbeat")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_mode: AppMode = AppMode.PAPER
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gpt-oss:120b"
    starting_cash: float = Field(default=500_000, gt=0)
    max_position_pct: float = Field(default=0.05, gt=0, le=1)
    max_daily_loss_pct: float = Field(default=0.01, gt=0, le=1)
    max_open_positions: int = Field(default=10, gt=0)

    paper_universe: tuple[str, ...] = (
        "RELIANCE",
        "TCS",
        "INFY",
        "HDFCBANK",
        "ICICIBANK",
    )
    paper_cycle_seconds: float = Field(default=900.0, ge=60.0, le=14_400.0)
    paper_history_days: int = Field(default=90, ge=30, le=730)
    paper_fallback_momentum: bool = True
    paper_fallback_target_pct: float = Field(default=0.03, gt=0, le=0.10)

    live_trading_armed: bool = False
    live_trading_confirmation: str = ""

    zerodha_api_key: str = ""
    zerodha_api_secret: SecretStr = SecretStr("")
    zerodha_access_token: SecretStr = SecretStr("")

    data_dir: str = "/var/lib/ai-stock-trading"
    heartbeat_path: str = Field(default_factory=_heartbeat_path)
    runtime_poll_seconds: float = Field(default=10.0, ge=1.0, le=300.0)
    dashboard_bind_host: str = "127.0.0.1"
    dashboard_port: int = Field(default=8080, ge=1024, le=65535)

    @field_validator("paper_universe", mode="before")
    @classmethod
    def parse_paper_universe(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip().upper() for item in value.split(",") if item.strip())
        return value

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if not self.paper_universe:
            raise ValueError("PAPER_UNIVERSE cannot be empty")
        if self.app_mode != AppMode.LIVE:
            return self
        if not self.live_trading_armed:
            raise ValueError("LIVE mode requires LIVE_TRADING_ARMED=true")
        if self.live_trading_confirmation != LIVE_CONFIRMATION_PHRASE:
            raise ValueError("LIVE mode requires the exact confirmation phrase")
        if not self.zerodha_api_key or not self.zerodha_api_secret.get_secret_value():
            raise ValueError("LIVE mode requires Zerodha API credentials")
        return self
