import json
from pathlib import Path

import httpx

from commanders.config import LLMConfig, load_config
from commanders.dossier import load_dossiers
from commanders.llm import LMStudioClient
from engine.scenario import load_scenario

DATA_DIR = Path(__file__).parent.parent / "data"


def test_defaults_when_no_file(tmp_path):
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.base_url == "http://localhost:1234/v1"
    assert cfg.api_key == ""
    assert cfg.model
    assert cfg.timeout_seconds > 0


def test_loads_values_from_toml(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[llm]
base_url = "http://localhost:11434/v1"
api_key = "sk-test"
model = "llama3.1:8b"
temperature = 0.4
timeout_seconds = 60

[llm.models]
staff = "small-model"
guderian = "big-model"
""",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.base_url == "http://localhost:11434/v1"
    assert cfg.api_key == "sk-test"
    assert cfg.temperature == 0.4
    assert cfg.model_for("guderian") == "big-model"
    assert cfg.model_for("staff") == "small-model"
    assert cfg.model_for("hoth") == "llama3.1:8b"


def test_env_overrides_beat_file(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('[llm]\nmodel = "from-file"\n', encoding="utf-8")
    monkeypatch.setenv("DIRECTIVE_LLM_MODEL", "from-env")
    monkeypatch.setenv("DIRECTIVE_LLM_BASE_URL", "http://example:9999/v1")
    cfg = load_config(path)
    assert cfg.model == "from-env"
    assert cfg.base_url == "http://example:9999/v1"


def _capture_client(captured, **kwargs):
    def responder(request):
        captured.append(request)
        payload = {
            "orders": [
                {"corps_id": "xxiv_pz", "posture": "defend", "objective": None},
                {"corps_id": "xlvi_pz", "posture": "defend", "objective": None},
                {"corps_id": "xlvii_pz", "posture": "defend", "objective": None},
            ],
            "dispatch": "Holding.",
            "reasoning": "",
        }
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )

    return LMStudioClient(transport=httpx.MockTransport(responder), **kwargs)


async def test_api_key_sent_as_bearer_header():
    captured = []
    client = _capture_client(captured, model="m", api_key="sk-secret")
    state = load_scenario(DATA_DIR)
    await client.request_orders(state, load_dossiers(DATA_DIR)["guderian"])
    assert captured[0].headers["authorization"] == "Bearer sk-secret"


async def test_no_auth_header_without_key():
    captured = []
    client = _capture_client(captured, model="m")
    state = load_scenario(DATA_DIR)
    await client.request_orders(state, load_dossiers(DATA_DIR)["guderian"])
    assert "authorization" not in captured[0].headers


async def test_per_role_model_used_in_requests():
    captured = []
    client = _capture_client(
        captured, model="default-model", models={"guderian": "panzer-brain"}
    )
    state = load_scenario(DATA_DIR)
    dossiers = load_dossiers(DATA_DIR)
    await client.request_orders(state, dossiers["guderian"])
    await client.request_orders(state, dossiers["hoth"])
    assert json.loads(captured[0].content)["model"] == "panzer-brain"
    assert json.loads(captured[-1].content)["model"] == "default-model"


def test_client_built_from_config():
    cfg = LLMConfig(base_url="http://x/v1", api_key="k", model="m",
                    models={"staff": "s"}, temperature=0.2, timeout_seconds=30,
                    max_concurrency=2)
    client = LMStudioClient.from_config(cfg)
    assert client.base_url == "http://x/v1"
    assert client.api_key == "k"
    assert client.timeout == 30
    assert client.max_concurrency == 2
    assert client._model_for("staff") == "s"
    assert client._model_for("kluge") == "m"


def test_max_concurrency_from_toml_and_env(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text("[llm]\nmax_concurrency = 4\n", encoding="utf-8")
    assert load_config(path).max_concurrency == 4
    monkeypatch.setenv("DIRECTIVE_LLM_MAX_CONCURRENCY", "1")
    assert load_config(path).max_concurrency == 1
