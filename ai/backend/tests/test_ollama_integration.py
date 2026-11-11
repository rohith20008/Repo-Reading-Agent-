"""Opt-in real Ollama checks: set CODEMIND_RUN_OLLAMA_INTEGRATION=1 to run."""
from __future__ import annotations

import os
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai.providers import OllamaProvider
from app.config import AISettings, Settings
from app.main import create_app
from .ai_helpers import prepare
from .conftest import write


pytestmark = pytest.mark.skipif(
    os.environ.get("CODEMIND_RUN_OLLAMA_INTEGRATION") != "1",
    reason="set CODEMIND_RUN_OLLAMA_INTEGRATION=1 to call the local Ollama servers",
)


def integration_ai() -> AISettings:
    return AISettings(
        provider="ollama",
        model="qwen2.5-coder:3b",
        embedding_model="nomic-embed-text:latest",
        endpoint="http://127.0.0.1:11435",
        timeout=120,
        max_tokens=96,
        context_chars=4000,
    )


def test_both_ollama_servers_are_reachable_and_models_exist_on_codemind():
    settings = integration_ai()
    assert settings.endpoint == "http://127.0.0.1:11435"

    other_server = httpx.get("http://127.0.0.1:11434/api/version", timeout=5)
    dedicated_server = httpx.get("http://127.0.0.1:11435/api/version", timeout=5)
    assert other_server.status_code == dedicated_server.status_code == 200
    assert other_server.json().get("version")
    assert dedicated_server.json().get("version")

    provider = OllamaProvider(settings)
    assert "chat model 'qwen2.5-coder:3b'" in provider.check()
    models = httpx.get("http://127.0.0.1:11435/api/tags", timeout=5).json()["models"]
    names = {model["name"] for model in models}
    assert "qwen2.5-coder:3b" in names
    assert "nomic-embed-text:latest" in names


def test_chat_stream_and_embeddings_use_the_dedicated_server():
    provider = OllamaProvider(integration_ai())
    reply = provider.complete(
        "Reply with one short word.",
        [{"role": "user", "content": "Say hello."}],
        max_tokens=8,
        temperature=0,
    )
    assert reply.text
    assert reply.model == "qwen2.5-coder:3b"

    chunks = list(provider.stream(
        "Reply with one short word.",
        [{"role": "user", "content": "Say hello."}],
        max_tokens=8,
        temperature=0,
    ))
    assert "".join(chunks).strip()

    vectors = provider.embed(["CODEMIND dedicated Ollama integration check"])
    assert len(vectors) == 1 and vectors[0]
    assert all(isinstance(value, (int, float)) for value in vectors[0])


def test_backend_health_and_ai_status_use_the_dedicated_server(tmp_path):
    settings = Settings(
        db_path=tmp_path / "integration.db",
        ai=integration_ai(),
    )
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/health")
        status = client.get("/api/ai/status?refresh=true")

    assert health.status_code == 200
    assert status.status_code == 200
    data = status.json()
    assert data["endpoint"] == "http://127.0.0.1:11435"
    assert data["state"] == "ready"
    assert data["reachable"] is True and data["modelAvailable"] is True


def test_real_backend_chat_and_stream_routes_use_the_dedicated_provider(tmp_path):
    settings = Settings(
        db_path=tmp_path / "chat-integration.db",
        ai=integration_ai(),
    )
    repository = tmp_path / "chat-repository"
    write(repository, "app/models.py", "class User:\n    def __init__(self, name):\n        self.name = name\n\n")
    with TestClient(create_app(settings)) as client:
        repo_id = prepare(client, repository)
        url = f"/api/repositories/{repo_id}/chat"
        body = {"message": "What does the User class in app/models.py do?", "agent": "code-intelligence"}
        response = client.post(url, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["assistantMessage"]["content"].strip()
        assert response.json()["provider"] == "ollama"

        streamed = client.post(f"{url}/stream", json=body)
        assert streamed.status_code == 200, streamed.text
        events = [
            json.loads(line.removeprefix("data: "))
            for line in streamed.text.splitlines()
            if line.startswith("data: ")
        ]
        assert any(event["type"] == "delta" and event["text"] for event in events)
        complete = next(event["data"] for event in events if event["type"] == "complete")
        assert complete["assistantMessage"]["content"].strip()
