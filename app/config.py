from enum import StrEnum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppMode(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_mode: AppMode = AppMode.PAPER
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gpt-oss:120b"
    starting_cash: float = Field(default=500_000, gt=0)
    max_position_pct: float = Field(default=0.05, gt=0, le=1)
    max_daily_loss_pct: float = Field(default=0.01, gt=0, le=1)
    max_open_positions: int = Field(default=10, gt=0)
