from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.diagnostic_export import build_diagnostic_export
from app.models import OrderPlan, Product, Side
from app.ollama_credentials import OllamaCredentials, OllamaCredentialStore
from app.persistent_paper import PersistentPaperBroker
from app.zerodha_credentials import ZerodhaCredentials, ZerodhaCredentialStore


def test_zerodha_credentials_are_persisted_with_restricted_permissions(tmp_path: Path) -> None:
    path = tmp_path / "zerodha-credentials.json"
    store = ZerodhaCredentialStore(path)
    credentials = ZerodhaCredentials(api_key="test-key", api_secret="test-secret")

    store.save(credentials)

    assert store.load() == credentials
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_ollama_cloud_credentials_are_restricted_and_require_https(tmp_path: Path) -> None:
    path = tmp_path / "ollama-credentials.json"
    store = OllamaCredentialStore(path)
    credentials = OllamaCredentials(
        base_url="https://ollama.com",
        model="gpt-oss:120b",
        api_key="cloud-secret",
    )

    store.save(credentials)

    assert store.load() == credentials
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600

    with pytest.raises(ValueError, match="HTTPS"):
        OllamaCredentials(
            base_url="http://localhost:11434",
            model="gpt-oss:120b",
            api_key="cloud-secret",
        )


def test_diagnostic_export_includes_realized_losses_but_not_credentials(tmp_path: Path) -> None:
    broker = PersistentPaperBroker(tmp_path / "paper.sqlite3", starting_cash=100_000)
    broker.place_order(
        OrderPlan(
            intent_id="thesis:test:buy",
            symbol="TCS",
            side=Side.BUY,
            product=Product.DELIVERY,
            quantity=10,
            limit_price=100,
        )
    )
    broker.place_order(
        OrderPlan(
            intent_id="thesis:test:sell",
            symbol="TCS",
            side=Side.SELL,
            product=Product.DELIVERY,
            quantity=10,
            limit_price=90,
        )
    )
    ZerodhaCredentialStore(tmp_path / "zerodha-credentials.json").save(
        ZerodhaCredentials(api_key="sensitive-key", api_secret="sensitive-secret")
    )
    OllamaCredentialStore(tmp_path / "ollama-credentials.json").save(
        OllamaCredentials(
            base_url="https://ollama.com",
            model="gpt-oss:120b",
            api_key="sensitive-ollama-key",
        )
    )

    payload = json.loads(build_diagnostic_export(tmp_path, 100_000))

    assert len(payload["realized_losses"]) == 1
    assert payload["realized_losses"][0]["order"]["realized_pnl"] == -100.0
    serialized = json.dumps(payload)
    assert "sensitive-key" not in serialized
    assert "sensitive-secret" not in serialized
    assert "sensitive-ollama-key" not in serialized
    assert payload["security"]["credentials_included"] is False
