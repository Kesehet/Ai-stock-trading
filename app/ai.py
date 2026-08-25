from __future__ import annotations

import json
from typing import TypeVar

import httpx
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class OllamaClient:
    """Thin Ollama client that requires schema-valid JSON output."""

    def __init__(self, base_url: str, model: str, timeout_seconds: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def generate_structured(self, prompt: str, response_model: type[T]) -> T:
        schema = response_model.model_json_schema()
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0.1},
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(f"{self.base_url}/api/generate", json=payload)
            response.raise_for_status()
            body = response.json()
        raw = body.get("response")
        if not isinstance(raw, str):
            raise ValueError("Ollama response did not contain a string response field")
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("Ollama returned invalid JSON") from exc
        return response_model.model_validate(decoded)
