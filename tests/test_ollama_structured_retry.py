from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from app.ai import OllamaClient


class ExampleResponse(BaseModel):
    score: float
    summary: str


class FakeResponse:
    def __init__(self, raw: str) -> None:
        self.raw = raw

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return {"response": self.raw}


class FakeClient:
    responses: list[str] = []
    prompts: list[str] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *args: Any) -> None:
        del args

    def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        del url, headers
        self.prompts.append(str(json["prompt"]))
        return FakeResponse(self.responses.pop(0))


def test_structured_output_retries_scalar_then_accepts_object(monkeypatch) -> None:
    FakeClient.responses = ["-0.6", '{"score":0.7,"summary":"valid"}']
    FakeClient.prompts = []
    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = OllamaClient("https://ollama.example", "model", "secret", structured_retries=3)

    result = client.generate_structured("analyze", ExampleResponse)

    assert result.score == pytest.approx(0.7)
    assert result.summary == "valid"
    assert len(FakeClient.prompts) == 2
    assert "CORRECTION" in FakeClient.prompts[1]


def test_structured_output_extracts_json_object_from_commentary(monkeypatch) -> None:
    FakeClient.responses = ['Result: {"score":0.2,"summary":"usable"} trailing']
    FakeClient.prompts = []
    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = OllamaClient("https://ollama.example", "model", "secret")

    result = client.generate_structured("analyze", ExampleResponse)

    assert result.summary == "usable"


def test_structured_output_fails_closed_after_retries(monkeypatch) -> None:
    FakeClient.responses = ["0.1", "", "not-json"]
    FakeClient.prompts = []
    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = OllamaClient("https://ollama.example", "model", "secret", structured_retries=3)

    with pytest.raises(ValueError, match="after 3 attempts"):
        client.generate_structured("analyze", ExampleResponse)
