"""Local Ollama inference over HTTP; application code depends only on this provider interface."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterator, Protocol
from urllib.parse import urlparse

import httpx

from ..config import AISettings


class ProviderError(Exception):
    """Ollama could not answer (unreachable, rejected the request, or returned malformed data)."""


class ProviderNotConfigured(ProviderError):
    """No usable local AI configuration."""


class ProviderUnavailable(ProviderError):
    """The configured Ollama server could not be reached."""


class ProviderTimeout(ProviderError):
    """The configured Ollama server did not respond before the request timeout."""


class ModelUnavailable(ProviderError):
    """Ollama is reachable, but the configured model is not installed."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(self, system: str, messages: list[dict], max_tokens: int, temperature: float) -> LLMResponse: ...

    def stream(self, system: str, messages: list[dict], max_tokens: int, temperature: float) -> Iterator[str]: ...

    def check(self) -> str: ...


def config_message(ai: AISettings) -> str:
    problems = "; ".join(ai.problems())
    return (
        f"No local AI model is configured ({problems}). Set CODEMIND_AI_PROVIDER=ollama and "
        "CODEMIND_AI_MODEL=qwen2.5-coder:3b in backend/.env or the environment. "
        "Repository scanning, code parsing and dependency analysis work without it."
    )


def host_only(endpoint: str) -> str:
    """Return only scheme and host, never credentials or URL paths."""
    try:
        parsed = urlparse(endpoint)
        if not parsed.hostname:
            return ""
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        return ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


class OllamaProvider:
    name = "ollama"
    label = "Ollama"

    def __init__(self, ai: AISettings, transport: httpx.BaseTransport | None = None):
        self.model = ai.model
        self.embedding_model = ai.embedding_model
        self.endpoint = ai.endpoint.rstrip("/")
        self._timeout = ai.timeout
        self._transport = transport

    def _request(self, method: str, url: str, timeout: float | None = None, **kwargs) -> dict:
        request_timeout = timeout if timeout is not None else self._timeout
        try:
            with httpx.Client(timeout=request_timeout, transport=self._transport) as client:
                response = client.request(method, url, **kwargs)
        except httpx.ConnectError:
            raise ProviderUnavailable(self._unreachable()) from None
        except httpx.TimeoutException:
            raise ProviderTimeout(
                f"Ollama did not answer within {request_timeout:g} seconds. "
                "Try a smaller model or raise CODEMIND_AI_TIMEOUT."
            ) from None
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not talk to Ollama: {type(exc).__name__}.") from None
        if response.status_code >= 400:
            if response.status_code == 404:
                model = (kwargs.get("json") or {}).get("model")
                if model:
                    raise ModelUnavailable(self._missing_model(model))
                raise ProviderError("Ollama returned HTTP 404 for its tags API.")
            raise ProviderError(f"Ollama returned HTTP {response.status_code}.")
        try:
            data = response.json()
        except ValueError:
            raise ProviderError("Ollama returned a response that is not valid JSON.") from None
        if not isinstance(data, dict):
            raise ProviderError("Ollama returned an unexpected response.")
        return data

    def _unreachable(self) -> str:
        return (
            f"Cannot reach Ollama at {host_only(self.endpoint)}. "
            "Start CODEMIND's dedicated server with backend/scripts/start_ollama.ps1."
        )

    def _missing_model(self, model: str) -> str:
        parsed = urlparse(self.endpoint)
        ollama_host = parsed.netloc
        if parsed.username or parsed.password:
            ollama_host = parsed.hostname or ""
            if parsed.port:
                ollama_host = f"{ollama_host}:{parsed.port}"
        return (
            f"Ollama does not have model '{model}'. To install it on this instance, "
            f"set OLLAMA_HOST={ollama_host} in the Ollama client process and run `ollama pull {model}`."
        )

    def complete(self, system: str, messages: list[dict], max_tokens: int, temperature: float) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        data = self._request("POST", f"{self.endpoint}/api/chat", json=payload)
        message = data.get("message")
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("Ollama returned an empty answer.")
        return LLMResponse(text.strip(), data.get("model") or self.model)

    def stream(self, system: str, messages: list[dict], max_tokens: int, temperature: float) -> Iterator[str]:
        payload = {
            "model": self.model,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                with client.stream("POST", f"{self.endpoint}/api/chat", json=payload) as response:
                    if response.status_code >= 400:
                        response.read()
                        if response.status_code == 404:
                            raise ModelUnavailable(self._missing_model(self.model))
                        raise ProviderError(f"Ollama returned HTTP {response.status_code}.")
                    for line in response.iter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except ValueError:
                            raise ProviderError("Ollama returned a malformed streaming response.") from None
                        if not isinstance(data, dict):
                            raise ProviderError("Ollama returned an unexpected streaming response.")
                        if data.get("error"):
                            raise ProviderError(str(data["error"]))
                        message = data.get("message")
                        content = message.get("content") if isinstance(message, dict) else None
                        if content:
                            if not isinstance(content, str):
                                raise ProviderError("Ollama returned invalid streaming content.")
                            yield content
        except httpx.ConnectError:
            raise ProviderUnavailable(self._unreachable()) from None
        except httpx.TimeoutException:
            raise ProviderTimeout(
                f"Ollama did not answer within {int(self._timeout)} seconds. "
                "Try a smaller model or raise CODEMIND_AI_TIMEOUT."
            ) from None
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not talk to Ollama: {type(exc).__name__}.") from None

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Create local vectors with the configured embedding model."""
        if not texts:
            return []
        data = self._request("POST", f"{self.endpoint}/api/embed",
                             json={"model": self.embedding_model, "input": texts})
        vectors = data.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ProviderError("Ollama returned an unexpected embeddings response.")
        if any(not isinstance(vector, list) or not vector or any(not isinstance(value, (int, float)) for value in vector)
               for vector in vectors):
            raise ProviderError("Ollama returned invalid embedding vectors.")
        return vectors

    def check(self) -> str:
        data = self._request("GET", f"{self.endpoint}/api/tags", timeout=min(5.0, self._timeout))
        models = data.get("models")
        if not isinstance(models, list):
            raise ProviderError("Ollama returned model data in an unexpected format.")
        names = [model.get("name", "") for model in models if isinstance(model, dict)]
        for model in (self.model, self.embedding_model):
            if model and not any(
                name == model or name == f"{model}:latest" or name.split(":")[0] == model
                for name in names
            ):
                raise ModelUnavailable(f"Ollama is running but {self._missing_model(model)}")
        return (
            f"Ollama is running and chat model '{self.model}' and embedding model "
            f"'{self.embedding_model}' are installed."
        )


PROVIDERS = {"ollama": OllamaProvider}


def build_provider(ai: AISettings, transport: httpx.BaseTransport | None = None) -> LLMProvider:
    if not ai.configured:
        raise ProviderNotConfigured(config_message(ai))
    return PROVIDERS[ai.provider](ai, transport=transport)
