from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.ollama_credentials import OllamaCredentialStore

T = TypeVar("T", bound=BaseModel)


class OllamaRateLimitError(RuntimeError):
    """Ollama Cloud asked the fund to slow down globally."""

    def __init__(self, retry_after_seconds: float = 60.0) -> None:
        self.retry_after_seconds = max(10.0, min(float(retry_after_seconds), 300.0))
        super().__init__(
            f"Ollama Cloud rate limited research; retry after "
            f"{self.retry_after_seconds:.0f}s"
        )


class OllamaHTTPError(RuntimeError):
    """Ollama/proxy returned a non-success HTTP response with safe diagnostics."""


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
            decoded: object = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            if start < 0:
                raise
            decoder = json.JSONDecoder()
            decoded, _ = decoder.raw_decode(text[start:])

        if isinstance(decoded, str):
            return OllamaClient._decode_json_object(decoded)
        return decoded

    @staticmethod
    def _response_payload(body: Any) -> object:
        if not isinstance(body, dict):
            raise ValueError("Ollama response body must be a JSON object")

        raw = body.get("response")
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.strip():
            return OllamaClient._decode_json_object(raw)

        message = body.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, dict):
                return content
            if isinstance(content, str) and content.strip():
                return OllamaClient._decode_json_object(content)

        raise ValueError("Ollama response did not contain structured response content")

    @staticmethod
    def _error_summary(exc: Exception) -> str:
        text = str(exc).replace("\n", " ").strip()
        return text[:500] or type(exc).__name__

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float:
        raw = response.headers.get("Retry-After", "").strip()
        if raw:
            try:
                return float(raw)
            except ValueError:
                pass
        return 60.0

    @staticmethod
    def _http_error(response: httpx.Response) -> OllamaHTTPError:
        status = getattr(response, "status_code", 0)
        headers = getattr(response, "headers", {})
        attempts = str(headers.get("X-Ollama-Proxy-Attempts", "?")).strip() or "?"
        upstreams = str(headers.get("X-Ollama-Proxy-Upstreams", "?")).strip() or "?"
        try:
            body = response.text
        except Exception:
            body = ""
        body = " ".join(str(body).split())[:500]
        detail = f" | response={body}" if body else ""
        return OllamaHTTPError(
            f"Ollama HTTP {status} | proxy attempts {attempts}/{upstreams}{detail}"
        )

    def generate_structured(self, prompt: str, response_model: type[T]) -> T:
        schema = response_model.model_json_schema()
        schema_json = json.dumps(schema, separators=(",", ":"))
        last_error: Exception | None = None

        with httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            for attempt in range(1, self.structured_retries + 1):
                strict_schema = attempt == 1
                format_value: object = schema if strict_schema else "json"
                retry_prompt = prompt
                if attempt > 1:
                    previous_error = self._error_summary(
                        last_error or ValueError("unknown")
                    )
                    retry_prompt = "\n".join(
                        [
                            prompt,
                            "CORRECTION: The previous response was invalid.",
                            f"Validation problem: {previous_error}",
                            "Return ONLY one JSON object. No markdown or commentary.",
                            "The JSON must validate against this schema:",
                            schema_json,
                        ]
                    )

                payload = {
                    "model": self.model,
                    "prompt": retry_prompt,
                    "stream": False,
                    "format": format_value,
                    "options": {"temperature": 0},
                }
                response = client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                status = getattr(response, "status_code", 200)
                if status == 429:
                    raise OllamaRateLimitError(self._retry_after_seconds(response))
                if status >= 400:
                    raise self._http_error(response)
                response.raise_for_status()

                try:
                    decoded = self._response_payload(response.json())
                    if not isinstance(decoded, dict):
                        raise ValueError("Ollama structured response must be a JSON object")
                    return response_model.model_validate(decoded)
                except (
                    json.JSONDecodeError,
                    ValidationError,
                    ValueError,
                    TypeError,
                ) as exc:
                    last_error = exc

        detail = self._error_summary(
            last_error or ValueError("unknown structured-output failure")
        )
        raise ValueError(
            "Ollama failed to return schema-valid JSON after "
            f"{self.structured_retries} attempts: {detail}"
        ) from last_error
