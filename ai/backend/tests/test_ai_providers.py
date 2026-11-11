import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai.providers import (
    ModelUnavailable,
    PROVIDERS,
    OllamaProvider,
    ProviderError,
    ProviderNotConfigured,
    ProviderTimeout,
    ProviderUnavailable,
    build_provider,
    config_message,
    host_only,
)
from app.config import AI_PROVIDERS, AISettings, ai_settings_from_env, load_dotenv, load_settings
from app.main import create_app

from .ai_helpers import ai_client, fake  # noqa: F401


def ai(model="qwen2.5-coder:3b", **kw):
    values = {
        "provider": "ollama", "model": model, "embedding_model": "nomic-embed-text:latest",
        "endpoint": "http://127.0.0.1:11435",
    }
    values.update(kw)
    return AISettings(**values)


def mock(handler):
    seen = []

    def wrapper(request):
        seen.append(request)
        return handler(request)

    return httpx.MockTransport(wrapper), seen


@pytest.mark.parametrize(
    "env,configured",
    [
        ({}, False),
        ({"CODEMIND_AI_PROVIDER": "none"}, False),
        ({"CODEMIND_AI_PROVIDER": "ollama"}, False),
        ({"CODEMIND_AI_PROVIDER": "ollama", "CODEMIND_AI_MODEL": "qwen2.5-coder:3b"}, True),
        ({"CODEMIND_AI_PROVIDER": "openai", "CODEMIND_AI_MODEL": "gpt"}, False),
        ({"CODEMIND_AI_PROVIDER": "anthropic", "CODEMIND_AI_MODEL": "claude"}, False),
        ({"CODEMIND_AI_PROVIDER": "openai_compatible", "CODEMIND_AI_MODEL": "model"}, False),
    ],
)
def test_only_ollama_is_configurable(env, configured):
    assert ai_settings_from_env(env).configured is configured


def test_local_defaults_and_overrides():
    settings = ai_settings_from_env({
        "CODEMIND_AI_PROVIDER": "ollama", "CODEMIND_AI_MODEL": "qwen2.5-coder:3b",
        "CODEMIND_AI_EMBEDDING_MODEL": "nomic-embed-text:latest", "CODEMIND_AI_TIMEOUT": "30",
        "CODEMIND_AI_MAX_TOKENS": "bad", "CODEMIND_AI_TEMPERATURE": "0.7",
        "CODEMIND_AI_CONTEXT_CHARS": "9000",
    })
    assert settings.endpoint == "http://127.0.0.1:11435"
    assert settings.embedding_model == "nomic-embed-text:latest"
    assert settings.timeout == 30 and settings.max_tokens == 1500
    assert settings.temperature == 0.7 and settings.context_chars == 9000
    assert set(PROVIDERS) == set(AI_PROVIDERS) == {"ollama"}


def test_dotenv_parsing_and_precedence(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nCODEMIND_AI_PROVIDER=ollama\nCODEMIND_AI_MODEL = \"qwen2.5-coder:3b\"\n"
        "export CODEMIND_AI_ENDPOINT='http://h:1'\nCODEMIND_AI_TIMEOUT=45 # trailing note\n"
        "ALREADY=from_file\nEMPTY=\n", encoding="utf-8")
    environ = {"ALREADY": "from_environment"}
    applied = load_dotenv(env_file, environ)
    assert environ["CODEMIND_AI_MODEL"] == "qwen2.5-coder:3b"
    assert environ["CODEMIND_AI_ENDPOINT"] == "http://h:1" and environ["CODEMIND_AI_TIMEOUT"] == "45"
    assert environ["ALREADY"] == "from_environment" and "ALREADY" not in applied
    assert load_dotenv(tmp_path / "missing.env", {}) == {}


def test_load_settings_reads_local_models_from_env_file(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", {"PATH": os.environ.get("PATH", "")})
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CODEMIND_AI_PROVIDER=ollama\nCODEMIND_AI_MODEL=qwen2.5-coder:3b\n"
        "CODEMIND_AI_EMBEDDING_MODEL=nomic-embed-text:latest\nCODEMIND_DB=" + str(tmp_path / "x.db") + "\n")
    settings = load_settings(env_file)
    assert settings.ai.configured and settings.ai.model == "qwen2.5-coder:3b"
    assert settings.ai.embedding_model == "nomic-embed-text:latest" and settings.db_path == tmp_path / "x.db"


def test_ollama_chat_request_and_response():
    transport, seen = mock(lambda request: httpx.Response(
        200, json={"model": "qwen2.5-coder:3b", "message": {"role": "assistant", "content": " grounded answer "}}))
    provider = build_provider(ai(), transport)
    reply = provider.complete("use evidence", [{"role": "user", "content": "hello"}], 60, 0.1)
    assert reply.text == "grounded answer" and reply.model == "qwen2.5-coder:3b"
    request = seen[0]
    assert str(request.url) == "http://127.0.0.1:11435/api/chat"
    body = json.loads(request.content)
    assert body["model"] == "qwen2.5-coder:3b" and body["stream"] is False
    assert body["messages"] == [{"role": "system", "content": "use evidence"}, {"role": "user", "content": "hello"}]
    assert body["options"] == {"temperature": 0.1, "num_predict": 60}


def test_ollama_chat_stream_yields_real_response_deltas():
    transport, seen = mock(lambda request: httpx.Response(
        200, content=(
            b'{"message":{"content":"Local "},"done":false}\n'
            b'{"message":{"content":"stream"},"done":true}\n'
        ), headers={"content-type": "application/x-ndjson"}))
    provider = build_provider(ai(), transport)
    chunks = list(provider.stream("system", [{"role": "user", "content": "question"}], 60, 0.1))
    assert chunks == ["Local ", "stream"]
    body = json.loads(seen[0].content)
    assert body["stream"] is True and body["model"] == "qwen2.5-coder:3b"


def test_ollama_embedding_request_uses_centralized_local_model():
    transport, seen = mock(lambda request: httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.2, 0.3]]}))
    provider = build_provider(ai(), transport)
    assert provider.embed(["query", "source"]) == [[0.1, 0.2], [0.2, 0.3]]
    request = seen[0]
    assert str(request.url) == "http://127.0.0.1:11435/api/embed"
    assert json.loads(request.content) == {"model": "nomic-embed-text:latest", "input": ["query", "source"]}


def test_embedding_response_is_validated():
    transport, _ = mock(lambda request: httpx.Response(200, json={"embeddings": [[0.1]]}))
    with pytest.raises(ProviderError, match="unexpected embeddings"):
        build_provider(ai(), transport).embed(["one", "two"])


def test_check_verifies_the_local_chat_model():
    transport, seen = mock(lambda request: httpx.Response(
        200, json={"models": [{"name": "qwen2.5-coder:3b"}, {"name": "nomic-embed-text:latest"}]}))
    provider = build_provider(ai(), transport)
    assert "chat model 'qwen2.5-coder:3b' and embedding model 'nomic-embed-text:latest' are installed" in provider.check()
    assert str(seen[0].url) == "http://127.0.0.1:11435/api/tags"


def test_missing_ollama_model_reports_pull_command():
    transport, _ = mock(lambda request: httpx.Response(200, json={"models": []}))
    with pytest.raises(ModelUnavailable, match="ollama pull"):
        build_provider(ai(), transport).check()


def test_unavailable_ollama_and_malformed_responses_are_reported():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)
    transport, _ = mock(refuse)
    with pytest.raises(ProviderUnavailable, match="start_ollama.ps1"):
        build_provider(ai(), transport).check()

    transport, _ = mock(lambda request: httpx.Response(200, text="not json"))
    with pytest.raises(ProviderError, match="not valid JSON"):
        build_provider(ai(), transport).complete("", [{"role": "user", "content": "x"}], 1, 0)


def test_host_only_strips_credentials_and_paths():
    assert host_only("https://user:pw@example.com:8443/v1/secret?key=abc") == "https://example.com:8443"
    assert host_only("not a url") == ""


def test_unconfigured_and_nonlocal_providers_are_rejected():
    with pytest.raises(ProviderNotConfigured):
        build_provider(AISettings())
    with pytest.raises(ProviderNotConfigured):
        build_provider(AISettings(provider="openai", model="remote-model", endpoint="https://api.example.com"))
    with pytest.raises(ProviderNotConfigured, match="local Ollama"):
        build_provider(AISettings(provider="ollama", model="remote-model", endpoint="https://ollama.example.com"))
    assert "ollama" in config_message(AISettings())


def test_status_endpoint_reports_local_model_unavailable_without_leaking_endpoint(settings):
    from dataclasses import replace

    configured = replace(settings, ai=ai())
    with TestClient(create_app(configured)) as client:
        transport, _ = mock(lambda request: httpx.Response(200, json={"models": []}))
        client.app.state.ai._transport = transport
        response = client.get("/api/ai/status")
        data = response.json()
        assert data["provider"] == "ollama" and data["configured"] is True and data["reachable"] is True
        assert data["state"] == "model_missing" and data["modelAvailable"] is False
        assert data["endpoint"] == "http://127.0.0.1:11435" and "password" not in response.text


def test_status_unconfigured(client):
    data = client.get("/api/ai/status").json()
    assert data["configured"] is False and data["provider"] is None and data["reachable"] is None
    assert data["state"] == "invalid_configuration" and data["modelAvailable"] is None
    assert "CODEMIND_AI_PROVIDER" in data["message"]


def test_status_with_injected_provider(ai_client):
    data = ai_client.get("/api/ai/status").json()
    assert data["configured"] and data["provider"] == "fake" and data["reachable"] is True
    assert data["state"] == "ready" and data["modelAvailable"] is True


def test_status_distinguishes_unavailable_timeout_invalid_config_and_refresh(settings):
    from dataclasses import replace

    configured = replace(settings, ai=ai())
    with TestClient(create_app(configured)) as client:
        def refuse(request):
            raise httpx.ConnectError("refused", request=request)

        client.app.state.ai._transport = httpx.MockTransport(refuse)
        unavailable = client.get("/api/ai/status").json()
        assert unavailable["reachable"] is False and unavailable["state"] == "unavailable"
        assert unavailable["modelAvailable"] is None

        def timeout(request):
            raise httpx.ReadTimeout("slow", request=request)

        client.app.state.ai._transport = httpx.MockTransport(timeout)
        timed_out = client.get("/api/ai/status?refresh=true").json()
        assert timed_out["reachable"] is False and timed_out["state"] == "timeout"

        client.app.state.ai.settings = replace(configured, ai=ai(endpoint="http://localhost:not-a-port"))
        invalid = client.get("/api/ai/status").json()
        assert invalid["configured"] is False and invalid["state"] == "invalid_endpoint"
        assert invalid["reachable"] is None


def test_status_checks_are_cached_but_refresh_forces_a_new_probe(settings):
    from dataclasses import replace

    configured = replace(settings, ai=ai())
    count = 0

    def tags(request):
        nonlocal count
        count += 1
        return httpx.Response(200, json={"models": [
            {"name": "qwen2.5-coder:3b"},
            {"name": "nomic-embed-text:latest"},
        ]})

    with TestClient(create_app(configured)) as client:
        client.app.state.ai._transport = httpx.MockTransport(tags)
        first = client.get("/api/ai/status").json()
        second = client.get("/api/ai/status").json()
        assert first["reachable"] and second["reachable"] and count == 1
        client.get("/api/ai/status?refresh=true")
        assert count == 2


def test_invalid_ollama_endpoint_port_is_not_configured():
    settings = ai_settings_from_env({
        "CODEMIND_AI_PROVIDER": "ollama",
        "CODEMIND_AI_MODEL": "qwen2.5-coder:3b",
        "CODEMIND_AI_ENDPOINT": "http://localhost:not-a-port",
    })
    assert not settings.configured
    assert "CODEMIND_AI_ENDPOINT" in "; ".join(settings.problems())


def test_default_and_all_provider_requests_use_the_dedicated_endpoint():
    settings = ai_settings_from_env({
        "CODEMIND_AI_PROVIDER": "ollama",
        "CODEMIND_AI_MODEL": "qwen2.5-coder:3b",
    })
    assert settings.endpoint == "http://127.0.0.1:11435"

    transport, seen = mock(lambda request: httpx.Response(
        200,
        json={"models": [
            {"name": "qwen2.5-coder:3b"},
            {"name": "nomic-embed-text:latest"},
        ]} if request.method == "GET" else
        {"message": {"content": "answer"}} if request.url.path == "/api/chat" else
        {"embeddings": [[0.1]]},
    ))
    provider = build_provider(settings, transport)
    provider.check()
    provider.complete("", [{"role": "user", "content": "hello"}], 8, 0)
    list(provider.stream("", [{"role": "user", "content": "hello"}], 8, 0))
    provider.embed(["hello"])
    assert [str(request.url) for request in seen] == [
        "http://127.0.0.1:11435/api/tags",
        "http://127.0.0.1:11435/api/chat",
        "http://127.0.0.1:11435/api/chat",
        "http://127.0.0.1:11435/api/embed",
    ]


def test_status_is_ready_only_when_chat_and_embedding_models_exist(settings):
    from dataclasses import replace

    configured = replace(settings, ai=ai())
    with TestClient(create_app(configured)) as client:
        client.app.state.ai._transport = httpx.MockTransport(lambda request: httpx.Response(
            200, json={"models": [
                {"name": "qwen2.5-coder:3b"},
                {"name": "nomic-embed-text:latest"},
            ]},
        ))
        status = client.get("/api/ai/status?refresh=true").json()
        assert status["state"] == "ready"
        assert status["reachable"] is True and status["modelAvailable"] is True
        assert "embedding model 'nomic-embed-text:latest'" in status["detail"]


def test_status_reports_missing_embedding_model_as_model_missing(settings):
    from dataclasses import replace

    configured = replace(settings, ai=ai())
    with TestClient(create_app(configured)) as client:
        client.app.state.ai._transport = httpx.MockTransport(lambda request: httpx.Response(
            200, json={"models": [{"name": "qwen2.5-coder:3b"}]},
        ))
        status = client.get("/api/ai/status?refresh=true").json()
        assert status["state"] == "model_missing"
        assert status["reachable"] is True and status["modelAvailable"] is False
        assert "nomic-embed-text:latest" in status["detail"]


def test_backend_startup_does_not_manage_ollama_processes():
    from app.config import BACKEND_DIR

    startup = (BACKEND_DIR.parent / "scripts" / "start-backend.ps1").read_text(encoding="utf-8").lower()
    assert "start-process" not in startup and "stop-process" not in startup
    assert "ollama serve" not in startup
