"""LM Studio client: turns a game state + dossier into validated orders.

Flow per commander per turn:
  briefing -> chat completion (json_schema structured output) -> parse ->
  validate -> [one repair round-trip quoting the errors] -> fallback orders.

The schema is built per request from the same state as the briefing
(prompts.py::dynamic_order_schema), so it can name this commander's corps and
their reachable objectives; a backend that refuses it degrades to the static
ORDER_SCHEMA rather than stopping the turn. It narrows what a conforming
backend can emit - validate_orders remains the authority.

A server that cannot be reached at all raises LMStudioUnavailable (the turn
cannot be ended); a slow or incoherent model degrades to fallback "hold"
orders instead. Full transcripts can be logged to disk for prompt debugging.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path

import httpx

from commanders.briefing import build_briefing
from commanders.dossier import Dossier
from commanders.prompts import ORDER_SCHEMA, build_system_prompt, dynamic_order_schema
from engine.orders import CommanderOrders, fallback_orders, salvage_orders, validate_orders
from engine.state import GameState

DEFAULT_BASE_URL = "http://localhost:1234/v1"
DEFAULT_TIMEOUT = 300.0
DEFAULT_MAX_CONCURRENCY = 3

logger = logging.getLogger(__name__)


class LMStudioUnavailable(RuntimeError):
    """The LM Studio server could not be reached at all.

    ``status_code`` is the HTTP status when the server answered and rejected the
    request, and None when it could not be reached; the orders path uses that to
    tell "this backend refuses this request body" from "there is no backend".
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class LMStudioClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = "local-model",
        timeout: float = DEFAULT_TIMEOUT,
        temperature: float = 0.7,
        api_key: str = "",
        models: dict[str, str] | None = None,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        params: dict | None = None,
        transport: httpx.BaseTransport | None = None,
        log_dir: Path | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.models = dict(models or {})  # role (commander id / "staff") -> model
        self.timeout = timeout
        self.temperature = temperature
        self.api_key = api_key
        self.max_concurrency = max_concurrency
        # Backend-specific request-body fields, merged into every call. Empty by
        # default so the OpenAI-compatible body is unchanged (see _payload).
        self.params = dict(params or {})
        # Gate in-flight requests so queued ones wait here (no timeout running)
        # rather than in the server's queue (timeout burning) — see _chat.
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._warmed = False  # see warm_up()
        self.transport = transport
        self.log_dir = Path(log_dir) if log_dir else None

    @classmethod
    def from_config(cls, config, log_dir: Path | None = None,
                    transport: httpx.BaseTransport | None = None) -> LMStudioClient:
        return cls(
            base_url=config.base_url,
            model=config.model,
            models=config.models,
            timeout=config.timeout_seconds,
            temperature=config.temperature,
            api_key=config.api_key,
            max_concurrency=config.max_concurrency,
            params=config.params,
            transport=transport,
            log_dir=log_dir,
        )

    def _model_for(self, role: str | None) -> str:
        return self.models.get(role, self.model) if role else self.model

    async def warm_up(self) -> None:
        """Make every configured model resident before the turn fans out.

        LM Studio loads a model on first use, and a request that lands mid-load
        comes back with ``usage.completion_tokens`` > 0 but an EMPTY ``content``
        *and* empty ``reasoning_content`` - so ``_chat`` yields "" and the
        commander burns a repair round-trip. Measured on qwen/qwen3.5-9b: 8 of 9
        commanders failed that way on turn 1, and the same run scored 35/36 once
        the model was resident.

        Deliberately quiet: this never raises and never logs tokens. A wrong
        model name still surfaces loudly on the first real request, which is
        where a config error belongs.
        """
        if self._warmed:
            return
        self._warmed = True
        models = sorted({self.model, *self.models.values()})
        await asyncio.gather(*(self._warm_model(m) for m in models))

    async def _warm_model(self, model: str) -> None:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            **self.params,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=self.timeout, headers=headers
            ) as client:
                await client.post(f"{self.base_url}/chat/completions", json=payload)
        except Exception:  # noqa: BLE001 - a warm-up must never break a turn
            pass

    async def request_orders(self, state: GameState, dossier: Dossier) -> CommanderOrders:
        if not [c for c in state.corps_for(dossier.id) if not c.is_destroyed]:
            # Nothing to order, and no grammar to build: an empty oneOf is a
            # schema nothing can satisfy. No transcript either - analyze_logs
            # tallies model behavior, and a call that never happened is not a
            # data point.
            return CommanderOrders(
                commander=dossier.id,
                orders=[],
                dispatch="(No formations remain under this command.)",
            )
        messages = [
            {"role": "system", "content": build_system_prompt(dossier)},
            {"role": "user", "content": build_briefing(state, dossier.id)},
        ]
        # Built from the same state as the briefing, so the grammar and the
        # situation the commander is reasoning over can never disagree.
        schema = dynamic_order_schema(state, dossier.id)
        corps_list = list(state.corps.values())
        transcript: dict = {"commander": dossier.id, "turn": state.turn, "attempts": []}

        result: CommanderOrders | None = None
        last_parsed: CommanderOrders | None = None
        outcome = "fallback"
        for attempt in (1, 2):
            content, request_payload, schema = await self._orders_chat(
                messages, dossier.id, schema
            )
            transcript["attempts"].append({"response": content})
            transcript["request"] = request_payload  # last request sent

            orders, problems = self._parse(content, dossier.id)
            if orders is not None:
                last_parsed = orders
                problems = validate_orders(
                    orders, state.game_map, corps_list, state.control, state.weather
                )
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
            result = salvage_orders(
                last_parsed, state.game_map, corps_list, state.control, state.weather
            )
            outcome = "salvaged"
        if result is None:
            result = fallback_orders(dossier.id, corps_list)
        transcript["outcome"] = outcome
        # Which grammar actually produced this turn. A silent degrade to the
        # static schema would otherwise read, in the logs, as the model getting
        # worse. (dynamic_order_schema always returns a fresh dict, so identity
        # with ORDER_SCHEMA means the degrade in _orders_chat fired.)
        transcript["schema"] = "static-fallback" if schema is ORDER_SCHEMA else "dynamic"
        transcript["orders"] = result.to_dict()
        self._log(transcript, dossier.id, state.turn)
        return result

    async def request_text(self, messages: list[dict], role: str | None = None) -> str:
        """Plain conversational completion (no schema): used for commander
        conversations and staff reports. ``role`` selects a per-role model."""
        payload = {
            "model": self._model_for(role),
            "messages": messages,
            "temperature": self.temperature,
            **self.params,
        }
        content = await self._chat(payload, role=role)
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        return content

    async def request_structured(
        self, messages: list[dict], schema: dict, role: str | None = None
    ) -> str:
        """One completion constrained by ``schema``; returns the raw content for
        the caller to parse. A backend that refuses the schema raises
        LMStudioUnavailable with its status code - degrading is the caller's
        call, since only it knows what the unconstrained request should say."""
        payload = self._payload(messages, self._model_for(role), schema)
        content = await self._chat(payload, role=role)
        return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    async def _orders_chat(
        self, messages: list[dict], commander: str, schema: dict
    ) -> tuple[str, dict, dict]:
        """One orders request. Returns (content, the payload actually sent, the
        schema actually used).

        A backend that rejects the per-turn schema outright - a cloud provider
        that will not take oneOf/const, say - answers with a non-transient 4xx,
        which normally stops the turn. That would brick every campaign on such a
        backend, so degrade instead: retry the same call once with the static
        ORDER_SCHEMA, which every OpenAI-compatible server has accepted, and
        raise only if that fails too. Loudly, because the run's compliance
        numbers mean something different afterwards.
        """
        payload = self._payload(messages, self._model_for(commander), schema)
        try:
            return await self._chat(payload, role=commander), payload, schema
        except LMStudioUnavailable as e:
            # status_code None means the server was never reached; no schema
            # fixes that, and a second attempt only doubles the wait.
            if e.status_code is None or schema is ORDER_SCHEMA:
                raise
            logger.warning(
                "%s: the server rejected the per-turn order schema (HTTP %s: %s); "
                "retrying with the static ORDER_SCHEMA. Orders this turn are "
                "constrained only by the validator.",
                commander,
                e.status_code,
                e,
            )
            payload = self._payload(messages, self._model_for(commander), ORDER_SCHEMA)
            return await self._chat(payload, role=commander), payload, ORDER_SCHEMA

    def _payload(self, messages: list[dict], model: str, schema: dict) -> dict:
        return {
            "model": model,
            "messages": messages,
            "temperature": self.temperature,
            "response_format": {"type": "json_schema", "json_schema": schema},
            **self.params,
        }

    async def _chat(self, payload: dict, role: str | None = None) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            # The semaphore bounds in-flight requests to the server's real
            # parallelism. Crucially it is held OUTSIDE the AsyncClient, so a
            # request waiting for a slot is not yet counting against its own
            # read timeout — the timeout then measures generation, not queueing.
            async with self._semaphore:
                async with httpx.AsyncClient(
                    transport=self.transport, timeout=self.timeout, headers=headers
                ) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions", json=payload
                    )
                    response.raise_for_status()
                    data = response.json()
                    self._log_tokens(data.get("usage"), payload.get("model"), role)
                    message = data["choices"][0]["message"]
                    # Thinking models served by LM Studio sometimes leave
                    # "content" empty and put everything in "reasoning_content".
                    return message.get("content") or message.get("reasoning_content") or ""
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise LMStudioUnavailable(
                f"Cannot reach LM Studio at {self.base_url} - is the server running "
                f"with a model loaded? ({e})"
            ) from e
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            # A 4xx is usually a configuration error - wrong model name,
            # unsupported parameter, bad API key - that affects every request
            # identically. Surface it loudly instead of laundering it into an
            # empty "invalid JSON" response and hold-orders. The exceptions are
            # transient, per-request 4xx (rate limit, request timeout, too
            # early), which degrade to fallback like a 5xx and let the turn go on.
            TRANSIENT_4XX = {408, 425, 429}
            if 400 <= code < 500 and code not in TRANSIENT_4XX:
                raise LMStudioUnavailable(
                    f"The server at {self.base_url} rejected the request "
                    f"(HTTP {code}): {self._error_detail(e.response)}. Check the "
                    f"model name and parameters in config.toml.",
                    status_code=code,
                ) from e
            return ""
        except httpx.ReadTimeout:
            return ""  # treated as an unparseable response -> repair/fallback path

    def _log_tokens(self, usage: dict | None, model: str | None, role: str | None) -> None:
        """Append one line per call to tokens.jsonl: how many tokens went out and
        came back, tagged by commander/role and model. No-op without a log dir or
        a usage block (local servers may omit it)."""
        if self.log_dir is None or not usage:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "time": time.time(),
            "role": role,
            "model": model,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }
        with (self.log_dir / "tokens.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        """The server's own explanation for a rejected request, if it gave one.
        OpenAI-compatible servers return ``{"error": {"message": ...}}``."""
        try:
            body = response.json()
            if isinstance(body, dict):
                err = body.get("error")
                if isinstance(err, dict) and err.get("message"):
                    return str(err["message"])
                if isinstance(err, str) and err:
                    return err
        except ValueError:
            pass
        return (response.text or "").strip()[:300] or "no detail"

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
