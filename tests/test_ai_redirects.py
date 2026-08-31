from pydantic import BaseModel

from app.ai import OllamaClient


class ExampleResponse(BaseModel):
    ok: bool


class FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"response": {"ok": True}}


class FakeHttpClient:
    created_kwargs: dict[str, object] = {}

    def __init__(self, **kwargs: object) -> None:
        type(self).created_kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, *args: object, **kwargs: object) -> FakeResponse:
        return FakeResponse()


def test_ollama_client_follows_https_proxy_redirects(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.httpx.Client", FakeHttpClient)
    client = OllamaClient(
        base_url="https://example.test/ollama-proxy",
        model="test-model",
        api_key="test-key",
    )

    result = client.generate_structured("return json", ExampleResponse)

    assert result.ok is True
    assert FakeHttpClient.created_kwargs["follow_redirects"] is True
