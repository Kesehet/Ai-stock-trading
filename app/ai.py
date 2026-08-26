from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

import httpx
from pydantic import BaseModel

from app.config import Settings
from app.ollama_credentials import OllamaCredentialStore

T = TypeVar("T", bound=BaseModel)


class OllamaClient:
    """Remote Ollama cloud client that requires schema-valid JSON output."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 120.0,
    ) -> None:
        if not base_url.lower().startswith("https://"):
            raise ValueError("Ollama remote URL must use HTTPS")
        if not model.strip():
            raise ValueError("Ollama model is required")
        if not api_key.strip():
            raise ValueError("Ollama API key is required")
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> OllamaClient:
        env_key = settings.ollama_api_key.get_secret_value().strip()
        if env_key:
            return cls(
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
                api_key=env_key,
            )

        stored = OllamaCredentialStore(
            Path(settings.data_dir) / "ollama-credentials.json"
        ).load()
        if stored is None:
            raise RuntimeError(
                "Ollama cloud is not configured. Save the cloud URL, model and API key "
                "from the dashboard before starting AI research."
            )
        return cls(
            base_url=stored.base_url,
            model=stored.model,
            api_key=stored.api_key,
        )

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
            response = client.post(
                f"{self.base_url}/api/generate",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
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
