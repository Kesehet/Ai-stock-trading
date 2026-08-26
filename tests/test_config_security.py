from pathlib import Path

from app.config import AppMode, Settings
from app.runtime_mode import RuntimeModeStore


def test_paper_mode_is_the_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_mode == AppMode.PAPER


def test_live_can_be_selected_by_persistent_runtime_mode_store(tmp_path: Path) -> None:
    store = RuntimeModeStore(tmp_path / "runtime-mode.json", default_mode=AppMode.PAPER)
    assert store.load().mode == AppMode.PAPER
    store.save(AppMode.LIVE)
    assert store.load().mode == AppMode.LIVE
    store.save(AppMode.PAPER)
    assert store.load().mode == AppMode.PAPER


def test_broker_and_ai_secrets_are_masked_in_settings_repr() -> None:
    settings = Settings(
        zerodha_api_secret="super-secret-value",
        zerodha_access_token="session-secret-value",
        ollama_api_key="ollama-secret-value",
        dashboard_admin_token="admin-secret-value",
        _env_file=None,
    )
    rendered = repr(settings)
    assert "super-secret-value" not in rendered
    assert "session-secret-value" not in rendered
    assert "ollama-secret-value" not in rendered
    assert "admin-secret-value" not in rendered


def test_watchlist_is_normalized_and_deduplicated() -> None:
    settings = Settings(trading_watchlist="tcs, INFY,TCS", _env_file=None)
    assert settings.watchlist == ("TCS", "INFY")
