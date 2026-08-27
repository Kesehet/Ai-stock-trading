from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

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
        structured_retries: int = 3,
    ) -> None:
        if not base_url.lower().startswith("https://"):
            raise ValueError("Ollama remote URL must use HTTPS")
        if not model.strip():
            raise ValueError("Ollama model is required")
        if not api_key.strip():
            raise ValueError("Ollama API key is required")
        if structured_retries < 1 or structured_retries > 5:
            raise ValueError("structured_retries must be between 1 and 5")
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds
        self.structured_retries = structured_retries

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

    @staticmethod
    def _decode_json_object(raw: str) -> object:
        text = raw.strip()
        if text.startswith("```json") and text.endswith("```"):
            text = text[7:-3].strip()
        elif text.startswith("```") and text.endswith("```"):
            text = text[3:-3].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            if start < 0:
                raise
            decoder = json.JSONDecoder()
            decoded, _ = decoder.raw_decode(text[start:])
            return decoded

    def generate_structured(self, prompt: str, response_model: type[T]) -> T:
        schema = response_model.model_json_schema()
        retry_prompt = prompt
        last_error: Exception | None = None

        with httpx.Client(timeout=self.timeout_seconds) as client:
            for attempt in range(1, self.structured_retries + 1):
                payload = {
                    "model": self.model,
                    "prompt": retry_prompt,
                    "stream": False,
                    "format": schema,
                    "options": {"temperature": 0},
                }
                response = client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                response.raise_for_status()
                body = response.json()
                raw = body.get("response")
                if not isinstance(raw, str):
                    last_error = ValueError(
                        "Ollama response did not contain a string response field"
                    )
                else:
                    try:
                        decoded = self._decode_json_object(raw)
                        if not isinstance(decoded, dict):
                            raise ValueError("Ollama structured response must be a JSON object")
                        return response_model.model_validate(decoded)
                    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                        last_error = exc

                if attempt < self.structured_retries:
                    retry_prompt = "\n".join(
                        [
                            prompt,
                            "CORRECTION: The previous response did not match the required schema.",
                            "Return ONLY one JSON object matching the provided schema exactly.",
                            "Do not return a scalar, markdown, commentary, or explanatory text.",
                        ]
                    )

        raise ValueError(
            f"Ollama failed to return schema-valid JSON after {self.structured_retries} attempts"
        ) from last_error
