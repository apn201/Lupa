from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lupa.ai.llm import LLM, ChatResult, CostGate  # noqa: E402
from lupa.config import Settings  # noqa: E402
from lupa.ledger.db import Database  # noqa: E402
from lupa.paypal.client import PayPalClient  # noqa: E402
from lupa.service import Lupa  # noqa: E402

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
SAMPLE = ROOT / "data" / "sample_activity_synthetic.csv"
KNOWN = ROOT / "data" / "merchants_synthetic.yml"


TASK_PHRASES = {
    "intent_to_policy": "draft payment policy",
    "suggest_limit": "spending limit",
    "assess_payment": "assess one incoming payment",
    "explain_permission": "could not be classified",
}


class FakeBackend:
    """Recorded model answers, keyed by task (taken from the system prompt's version line)."""

    def __init__(self, answers: dict[str, str] | None = None, default: str | None = None) -> None:
        self.answers = answers or {}
        self.default = default
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str, max_tokens: int) -> ChatResult:
        self.calls.append((system, user))
        task = next((t for t, phrase in TASK_PHRASES.items() if phrase in system and t in self.answers), None)
        text = self.answers.get(task) if task else self.default
        if text is None:
            raise RuntimeError("backend down")
        return ChatResult(text=text, source="content", content=text, reasoning_content="", model="fake-model")


def make_settings(tmp_path: Path, **kw) -> Settings:
    base = dict(db_path=":memory:", llm_usage_path=str(tmp_path / "usage.json"),
                llm_kill_switch_path=str(tmp_path / "OFF"), llm_base_url="http://fake", llm_model="fake-model")
    base.update(kw)
    return Settings(**base)


def make_llm(settings: Settings, backend) -> LLM:
    return LLM(settings, backend=backend, gate=CostGate(settings))


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
def clock():
    return lambda: NOW


@pytest.fixture
def lupa_no_ai(tmp_path, clock):
    s = make_settings(tmp_path, llm_base_url="", llm_model="")
    lp = Lupa(s, db=Database(":memory:"), paypal=PayPalClient(s), llm=LLM(s, backend=None), clock=clock)
    lp.import_csv(str(SAMPLE), str(KNOWN), now=NOW)
    return lp
