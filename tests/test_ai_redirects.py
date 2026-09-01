import pytest
from pydantic import BaseModel

from app.ai import OllamaClient, OllamaHTTPError


class ExampleResponse(BaseModel):
    ok: bool


class FakeResponse:
    status_code = 200
    headers: dict[str, str] = {}
    text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"response": {"ok": True}}


class FakeHttpClient:
    created_kwargs: dict[str, object] = {}
    response: FakeResponse = FakeResponse()

    def __init__(self, **kwargs: object) -> None:
        type(self).created_kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, *args: object, **kwargs: object) -> FakeResponse:
        return type(self).response


def test_ollama_client_follows_https_proxy_redirects(monkeypatch) -> None:
    FakeHttpClient.response = FakeResponse()
    monkeypatch.setattr("app.ai.httpx.Client", FakeHttpClient)
    client = OllamaClient(
        base_url="https://example.test/ollama-proxy",
        model="test-model",
        api_key="test-key",
    )

    result = client.generate_structured("return json", ExampleResponse)

    assert result.ok is True
    assert FakeHttpClient.created_kwargs["follow_redirects"] is True


def test_ollama_client_surfaces_proxy_failover_diagnostics(monkeypatch) -> None:
    response = FakeResponse()
    response.status_code = 502
    response.headers = {
        "X-Ollama-Proxy-Attempts": "7",
        "X-Ollama-Proxy-Upstreams": "7",
    }
    response.text = '{"error":"upstream capacity unavailable"}'
    FakeHttpClient.response = response
    monkeypatch.setattr("app.ai.httpx.Client", FakeHttpClient)
    client = OllamaClient(
        base_url="https://example.test/ollama-proxy",
        model="test-model",
        api_key="test-key",
    )

    with pytest.raises(OllamaHTTPError) as exc_info:
        client.generate_structured("return json", ExampleResponse)

    message = str(exc_info.value)
    assert "Ollama HTTP 502" in message
    assert "proxy attempts 7/7" in message
    assert "upstream capacity unavailable" in message
    assert "test-key" not in message
