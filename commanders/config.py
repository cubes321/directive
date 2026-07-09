"""LLM backend configuration.

Loaded from ``config.toml`` at the repo root (see ``config.example.toml``),
with ``DIRECTIVE_LLM_*`` environment variables overriding individual values.
Any OpenAI-compatible chat-completions endpoint works: LM Studio, Ollama,
llama.cpp server, vLLM, LiteLLM, OpenRouter, ...

``[llm.models]`` maps a role (a commander id, or "staff" for the chief of
staff report) to a model, overriding the default ``model`` per role.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.toml"


@dataclass(frozen=True)
class LLMConfig:
    base_url: str = "http://localhost:1234/v1"
    api_key: str = ""
    model: str = "qwen/qwen3.6-35b-a3b"
    temperature: float = 0.7
    timeout_seconds: float = 300.0
    # Max requests in flight to the server at once. Match your server's
    # parallelism (LM Studio defaults to 3). Higher only helps if the backend
    # can truly serve more at once; on a single GPU it just adds latency.
    max_concurrency: int = 3
    models: dict[str, str] = field(default_factory=dict)  # role -> model override
    # Extra request-body fields merged verbatim into every chat-completions
    # call. For backend-specific knobs the OpenAI-compatible shape has no field
    # for - e.g. Kimi's {"thinking": {"type": "disabled"}} or a provider's
    # {"reasoning_effort": "low"}. Empty by default, so the body is untouched.
    params: dict = field(default_factory=dict)

    def model_for(self, role: str) -> str:
        return self.models.get(role, self.model)


def load_config(path: Path | None = None) -> LLMConfig:
    path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    values: dict = {}
    if path.exists():
        llm = tomllib.loads(path.read_text(encoding="utf-8")).get("llm", {})
        values = {
            key: llm[key]
            for key in ("base_url", "api_key", "model", "temperature",
                        "timeout_seconds", "max_concurrency")
            if key in llm
        }
        if isinstance(llm.get("models"), dict):
            values["models"] = {str(k): str(v) for k, v in llm["models"].items()}
        if isinstance(llm.get("params"), dict):
            values["params"] = dict(llm["params"])

    env = {
        "base_url": os.environ.get("DIRECTIVE_LLM_BASE_URL"),
        "api_key": os.environ.get("DIRECTIVE_LLM_API_KEY"),
        "model": os.environ.get("DIRECTIVE_LLM_MODEL"),
        "temperature": os.environ.get("DIRECTIVE_LLM_TEMPERATURE"),
        "timeout_seconds": os.environ.get("DIRECTIVE_LLM_TIMEOUT"),
        "max_concurrency": os.environ.get("DIRECTIVE_LLM_MAX_CONCURRENCY"),
    }
    for key, raw in env.items():
        if raw is None:
            continue
        if key in ("temperature", "timeout_seconds"):
            values[key] = float(raw)
        elif key == "max_concurrency":
            values[key] = int(raw)
        else:
            values[key] = raw

    return LLMConfig(**values)
