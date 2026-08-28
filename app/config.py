from enum import StrEnum

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppMode(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


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

    # Empty means discover/rank NSE cash equities dynamically. A non-empty value
    # deliberately constrains the mandate for debugging or an operator override.
    trading_watchlist: str = ""
    decision_interval_seconds: int = Field(default=900, ge=60, le=86_400)
    quote_poll_seconds: int = Field(default=10, ge=2, le=300)
    max_ai_candidates: int = Field(default=5, ge=1, le=25)
    universe_history_days: int = Field(default=90, ge=30, le=365)
    universe_min_price: float = Field(default=20.0, ge=0)
    universe_min_history_bars: int = Field(default=20, ge=5, le=252)
    universe_min_avg_traded_value: float = Field(default=50_000_000.0, ge=0)
    universe_scan_limit: int = Field(default=100, ge=10, le=500)

    # Live intraday scanner. It is intentionally broader than the normal AI
    # shortlist: cheap deterministic market-data scoring scans a large liquid
    # pool, while only the hottest names are promoted to expensive AI research.
    intraday_scanner_enabled: bool = True
    intraday_scan_interval_seconds: int = Field(default=60, ge=15, le=900)
    intraday_scan_pool_limit: int = Field(default=500, ge=25, le=2000)
    intraday_scan_batch_size: int = Field(default=125, ge=25, le=250)
    intraday_hot_candidates: int = Field(default=8, ge=1, le=25)
    intraday_hot_score_min: float = Field(default=0.035, ge=0, le=2)
    intraday_interrupt_cooldown_seconds: int = Field(default=300, ge=60, le=3600)

    data_dir: str = "/var/lib/ai-stock-trading"
    # This must live on the shared trader-data volume so the dashboard container
    # can observe the trader process. /tmp is private to each container.
    heartbeat_path: str = "/var/lib/ai-stock-trading/runtime-heartbeat"
    runtime_poll_seconds: float = Field(default=10.0, ge=1.0, le=300.0)
    dashboard_bind_host: str = "127.0.0.1"
    dashboard_port: int = Field(default=8080, ge=1024, le=65535)

    @property
    def watchlist(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                symbol.strip().upper()
                for symbol in self.trading_watchlist.split(",")
                if symbol.strip()
            )
        )

    @property
    def dynamic_universe(self) -> bool:
        return not self.watchlist
