"""OpenAI-compatible chat client plus cost control. Ported from Virta.

Handles the reasoning-model case where `message.content` is empty and the
answer sits in `reasoning_content`. No tools, no response_format: structured
output comes from prompting for JSON and parsing it.

Cost control fails closed: kill switch, per-hour and per-day call caps and a
daily spend ceiling are checked before every call, the call is recorded when
it is sent (a crash mid-call still counts), and caps survive restarts.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from ..config import Settings

log = logging.getLogger("lupa.ai")


@dataclass(frozen=True)
class ChatResult:
    text: str
    source: str  # content | reasoning_content | empty
    content: str
    reasoning_content: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    finish_reason: str = ""


class ChatBackend(Protocol):
    def __call__(self, system: str, user: str, max_tokens: int) -> ChatResult: ...


def _extract_text(message: Any) -> tuple[str, str, str, str]:
    content = (getattr(message, "content", None) or "").strip()
    reasoning = getattr(message, "reasoning_content", None)
    if reasoning is None:
        extra = getattr(message, "model_extra", None) or {}
        reasoning = extra.get("reasoning_content")
    reasoning = (reasoning or "").strip()
    text = content or reasoning
    source = "content" if content else ("reasoning_content" if reasoning else "empty")
    return text, source, content, reasoning


def openai_backend(settings: Settings) -> ChatBackend:
    from openai import OpenAI

    client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key or "none", timeout=30.0)

    def call(system: str, user: str, max_tokens: int) -> ChatResult:
        resp = client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=0,
        )
        if not resp.choices:
            raise RuntimeError("no choices returned")
        text, source, content, reasoning = _extract_text(resp.choices[0].message)
        usage = resp.usage.model_dump() if getattr(resp, "usage", None) else {}
        return ChatResult(text, source, content, reasoning, getattr(resp, "model", settings.llm_model),
                          usage, str(getattr(resp.choices[0], "finish_reason", "") or ""))

    return call


def extract_json(result: ChatResult) -> Any:
    """Find the JSON answer. `content` first, then `reasoning_content`.

    Scans left to right and keeps the last complete top-level object, so a
    reasoning model's prose before the answer is skipped.
    """
    decoder = json.JSONDecoder()
    for text in (result.content, result.reasoning_content):
        if not text:
            continue
        cleaned = text.replace("```json", "```").replace("```", "")
        last, i = None, 0
        while True:
            i = cleaned.find("{", i)
            if i < 0:
                break
            try:
                value, end = decoder.raw_decode(cleaned[i:])
            except json.JSONDecodeError:
                i += 1
                continue
            if isinstance(value, dict) and value:
                last = value
            i += end
        if last is not None:
            return last
    return None


class CostGate:
    def __init__(self, settings: Settings, clock=lambda: datetime.now(timezone.utc)) -> None:
        self.s = settings
        self.clock = clock
        self.path = Path(settings.llm_usage_path)
        self.kill = Path(settings.llm_kill_switch_path)
        self.lock = threading.Lock()
        self.calls: list[str] = []
        self.spend: dict[str, float] = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.calls = [str(c) for c in data.get("calls", [])]
            self.spend = {k: float(v) for k, v in data.get("spend_by_day", {}).items()}
        except FileNotFoundError:
            pass
        except (ValueError, OSError):
            # A corrupt ledger must not hand out a fresh budget.
            self.calls = [self.clock().isoformat()] * settings.llm_max_calls_per_day

    def allow(self) -> tuple[bool, str]:
        if self.kill.exists():
            return False, "kill_switch"
        now = self.clock()
        stamps = [datetime.fromisoformat(c) for c in self.calls]
        if sum(1 for t in stamps if t >= now - timedelta(hours=1)) >= self.s.llm_max_calls_per_hour:
            return False, "hourly_cap"
        if sum(1 for t in stamps if t.date() == now.date()) >= self.s.llm_max_calls_per_day:
            return False, "daily_cap"
        ceiling = self.s.llm_daily_spend_ceiling
        if ceiling and self.spend.get(now.date().isoformat(), 0.0) >= ceiling:
            return False, "spend_ceiling"
        return True, ""

    def record(self) -> None:
        """Count a call. Done when it is sent, so a crash mid-call still counts."""
        with self.lock:
            now = self.clock()
            self.calls.append(now.isoformat())
            cutoff = now - timedelta(days=2)
            self.calls = [c for c in self.calls if datetime.fromisoformat(c) >= cutoff]
            self._save()

    def add_usage(self, usage: dict | None) -> None:
        with self.lock:
            now = self.clock()
            usage = usage or {}
            cost = (float(usage.get("prompt_tokens", 0) or 0) * self.s.llm_cost_per_1m_input
                    + float(usage.get("completion_tokens", 0) or 0) * self.s.llm_cost_per_1m_output) / 1e6
            if cost:
                day = now.date().isoformat()
                self.spend[day] = self.spend.get(day, 0.0) + cost
                self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"calls": self.calls, "spend_by_day": self.spend}), encoding="utf-8")
        tmp.replace(self.path)


class LLM:
    """One gate, one backend. Every task goes through `complete`; None means no answer."""

    def __init__(self, settings: Settings, backend: ChatBackend | None = None,
                 gate: CostGate | None = None) -> None:
        self.settings = settings
        self.backend = backend if backend is not None else (openai_backend(settings) if settings.llm_enabled else None)
        self.gate = gate or CostGate(settings)
        self.model = settings.llm_model or "none"

    @property
    def available(self) -> bool:
        return self.backend is not None

    def complete_json(self, task: str, system: str, user: str, max_tokens: int = 600) -> dict | None:
        if self.backend is None:
            return None
        ok, why = self.gate.allow()
        if not ok:
            log.warning("ai %s skipped: %s", task, why)
            return None
        self.gate.record()  # counted when sent
        try:
            result = self.backend(system, user, max_tokens)
        except Exception as exc:  # any backend failure is "no answer"
            log.warning("ai %s failed: %s", task, exc)
            return None
        self.gate.add_usage(result.usage)
        data = extract_json(result)
        if not isinstance(data, dict):
            log.warning("ai %s returned no JSON", task)
            return None
        self.model = result.model or self.model
        return data
