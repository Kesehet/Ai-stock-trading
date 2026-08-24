import pytest
from pydantic import ValidationError

from app.config import LIVE_CONFIRMATION_PHRASE, AppMode, Settings


def test_paper_mode_does_not_require_live_credentials() -> None:
    settings = Settings(
        app_mode=AppMode.PAPER,
        _env_file=None,
    )
    assert settings.live_trading_armed is False


def test_live_mode_rejects_unarmed_startup() -> None:
    with pytest.raises(ValidationError, match="LIVE_TRADING_ARMED"):
        Settings(
            app_mode=AppMode.LIVE,
            zerodha_api_key="key",
            zerodha_api_secret="secret",
            _env_file=None,
        )


def test_live_mode_requires_exact_confirmation_phrase() -> None:
    with pytest.raises(ValidationError, match="confirmation phrase"):
        Settings(
            app_mode=AppMode.LIVE,
            live_trading_armed=True,
            live_trading_confirmation="yes",
            zerodha_api_key="key",
            zerodha_api_secret="secret",
            _env_file=None,
        )


def test_live_mode_can_only_arm_with_all_required_controls() -> None:
    settings = Settings(
        app_mode=AppMode.LIVE,
        live_trading_armed=True,
        live_trading_confirmation=LIVE_CONFIRMATION_PHRASE,
        zerodha_api_key="key",
        zerodha_api_secret="secret",
        _env_file=None,
    )
    assert settings.app_mode == AppMode.LIVE
