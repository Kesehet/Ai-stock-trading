from datetime import UTC, datetime

import httpx
import pytest
from pydantic import BaseModel

from app.ai import OllamaClient, OllamaRateLimitError
from app.runtime_state import RuntimeStateStore


class _ResponseModel(BaseModel):
    value: str


class _RateLimitedClient:
    def __enter__(self) -> "_RateLimitedClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, *_args: object, **_kwargs: object) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "75"})


def test_ollama_429_surfaces_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.ai.httpx.Client", lambda **_kwargs: _RateLimitedClient())
    client = OllamaClient(
        base_url="https://ollama.example",
        model="test-model",
        api_key="secret",
    )

    with pytest.raises(OllamaRateLimitError) as caught:
        client.generate_structured("test", _ResponseModel)

    assert caught.value.retry_after_seconds == 75.0


def test_transient_failure_can_clear_consumed_decision(tmp_path) -> None:
    store = RuntimeStateStore(tmp_path / "runtime-state.json")
    when = datetime(2026, 8, 28, 5, 0, tzinfo=UTC)

    store.record_decision("RIPPER", when)
    assert "RIPPER" in store.load().decisions

    store.clear_decision("RIPPER")
    assert "RIPPER" not in store.load().decisions
