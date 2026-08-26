from enum import StrEnum
from pathlib import Path
from tempfile import gettempdir

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppMode(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


def _heartbeat_path() -> str:
    return str(Path(gettempdir()) / "ai-stock-trading-heartbeat")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_mode: AppMode = AppMode.PAPER
    ollama_base_url: str = "https://ollama.com"
    ollama_model: str = "gpt-oss:120b"
    ollama_api_key: SecretStr = SecretStr("")

    starting_cash: float = Field(default=500_000, gt=0)
    max_position_pct: float = Field(default=0.05, gt=0, le=1)
    max_daily_loss_pct: float = Field(default=0.01, gt=0, le=1)
    max_open_positions: int = Field(default=10, gt=0)
    min_buy_confidence: float = Field(default=0.60, ge=0, le=1)
    paper_slippage_bps: float = Field(default=5.0, ge=0, le=100)
    live_order_timeout_seconds: int = Field(default=120, ge=30, le=900)

    zerodha_api_key: str = ""
    zerodha_api_secret: SecretStr = SecretStr("")
    zerodha_access_token: SecretStr = SecretStr("")
    dashboard_admin_token: SecretStr = SecretStr("")

    trading_watchlist: str = "TCS,INFY,RELIANCE,HDFCBANK,ICICIBANK,SBIN,LT,ITC,BHARTIARTL,AXISBANK"
    decision_interval_seconds: int = Field(default=900, ge=60, le=86_400)
    quote_poll_seconds: int = Field(default=10, ge=2, le=300)
    max_ai_candidates: int = Field(default=3, ge=1, le=10)

    data_dir: str = "/var/lib/ai-stock-trading"
    heartbeat_path: str = Field(default_factory=_heartbeat_path)
    runtime_poll_seconds: float = Field(default=10.0, ge=1.0, le=300.0)
    dashboard_bind_host: str = "127.0.0.1"
    dashboard_port: int = Field(default=8080, ge=1024, le=65535)

    @property
    def watchlist(self) -> tuple[str, ...]:
        symbols = tuple(
            dict.fromkeys(
                symbol.strip().upper()
                for symbol in self.trading_watchlist.split(",")
                if symbol.strip()
            )
        )
        if not symbols:
            raise ValueError("TRADING_WATCHLIST must contain at least one symbol")
        return symbols
