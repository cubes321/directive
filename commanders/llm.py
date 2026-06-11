"""LM Studio client: turns a game state + dossier into validated orders.

Flow per commander per turn:
  briefing -> chat completion (json_schema structured output) -> parse ->
  validate -> [one repair round-trip quoting the errors] -> fallback orders.

A server that cannot be reached at all raises LMStudioUnavailable (the turn
cannot be ended); a slow or incoherent model degrades to fallback "hold"
orders instead. Full transcripts can be logged to disk for prompt debugging.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx

from commanders.briefing import build_briefing
from commanders.dossier import Dossier
from commanders.prompts import ORDER_SCHEMA, build_system_prompt
from engine.orders import CommanderOrders, fallback_orders, salvage_orders, validate_orders
from engine.state import GameState

DEFAULT_BASE_URL = "http://localhost:1234/v1"
DEFAULT_TIMEOUT = 120.0


class LMStudioUnavailable(RuntimeError):
    """The LM Studio server could not be reached at all."""


class LMStudioClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = "local-model",
        timeout: float = DEFAULT_TIMEOUT,
        temperature: float = 0.7,
        transport: httpx.BaseTransport | None = None,
        log_dir: Path | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.transport = transport
        self.log_dir = Path(log_dir) if log_dir else None

    async def request_orders(self, state: GameState, dossier: Dossier) -> CommanderOrders:
        messages = [
            {"role": "system", "content": build_system_prompt(dossier)},
            {"role": "user", "content": build_briefing(state, dossier.id)},
        ]
        corps_list = list(state.corps.values())
        transcript: dict = {"commander": dossier.id, "turn": state.turn, "attempts": []}

        result: CommanderOrders | None = None
        last_parsed: CommanderOrders | None = None
        outcome = "fallback"
        for attempt in (1, 2):
            request_payload = self._payload(messages)
            content = await self._chat(request_payload)
            transcript["attempts"].append({"response": content})
            transcript["request"] = request_payload  # last request sent

            orders, problems = self._parse(content, dossier.id)
            if orders is not None:
                last_parsed = orders
                problems = validate_orders(orders, state.game_map, corps_list, state.control)
            if orders is not None and not problems:
                result = orders
                outcome = "ok" if attempt == 1 else "repaired"
                break
            if attempt == 1:
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your orders were rejected by the operations staff:\n- "
                            + "\n- ".join(problems)
                            + "\nResend your full corrected orders as JSON matching the schema."
                        ),
                    }
                )

        if result is None and last_parsed is not None:
            result = salvage_orders(last_parsed, state.game_map, corps_list, state.control)
            outcome = "salvaged"
        if result is None:
            result = fallback_orders(dossier.id, corps_list)
        transcript["outcome"] = outcome
        transcript["orders"] = result.to_dict()
        self._log(transcript, dossier.id, state.turn)
        return result

    def _payload(self, messages: list[dict]) -> dict:
        return {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "response_format": {"type": "json_schema", "json_schema": ORDER_SCHEMA},
        }

    async def _chat(self, payload: dict) -> str:
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=self.timeout
            ) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions", json=payload
                )
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
                # Thinking models served by LM Studio sometimes leave "content"
                # empty and put everything in "reasoning_content".
                return message.get("content") or message.get("reasoning_content") or ""
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise LMStudioUnavailable(
                f"Cannot reach LM Studio at {self.base_url} - is the server running "
                f"with a model loaded? ({e})"
            ) from e
        except (httpx.ReadTimeout, httpx.HTTPStatusError):
            return ""  # treated as an unparseable response -> repair/fallback path

    @staticmethod
    def _extract_json(content: str) -> str:
        """Cut thinking preambles/epilogues down to the outermost JSON object."""
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            return content[start : end + 1]
        return content

    @classmethod
    def _parse(cls, content: str, commander: str) -> tuple[CommanderOrders | None, list[str]]:
        try:
            payload = json.loads(cls._extract_json(content))
            orders = CommanderOrders.from_dict(
                {
                    "commander": commander,
                    "orders": payload["orders"],
                    "dispatch": payload.get("dispatch", ""),
                    "reasoning": payload.get("reasoning", ""),
                }
            )
            return orders, []
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return None, [f"response was not valid JSON matching the schema ({e})"]

    def _log(self, transcript: dict, commander: str, turn: int) -> None:
        if self.log_dir is None:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / f"turn{turn:02d}_{commander}_{time.time_ns()}.json"
        path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
