"""Dev tool: inspect the raw LM Studio response structure for one call."""

import json

import httpx

schema = {
    "name": "t",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
        "additionalProperties": False,
    },
}
r = httpx.post(
    "http://localhost:1234/v1/chat/completions",
    json={
        "model": "qwen/qwen3.6-35b-a3b",
        "messages": [{"role": "user", "content": 'Reply with JSON {"x": 1}'}],
        "response_format": {"type": "json_schema", "json_schema": schema},
        "temperature": 0.7,
    },
    timeout=180,
)
choice = r.json()["choices"][0]
print("finish_reason:", choice["finish_reason"])
print("message keys:", sorted(choice["message"].keys()))
print("content:", repr(choice["message"].get("content"))[:300])
print("reasoning_content:", repr(choice["message"].get("reasoning_content"))[:300])
print("reasoning:", repr(choice["message"].get("reasoning"))[:300])
