"""◆ For kind `unknown` only: a suggested kind and one reason code, stored as a suggestion."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel

from ..ledger.models import Payment, Permission, Profile
from ..money import fmt
from . import guard, prompts
from .llm import LLM

VOCAB = {"EXPLAIN_IRREGULAR_RECURRING", "EXPLAIN_USAGE_BASED", "EXPLAIN_ONE_OFF", "EXPLAIN_INSUFFICIENT_DATA"}


class _Out(BaseModel):
    kind: Literal["fixed_recurring", "variable_recurring", "one_time_authority", "unknown"]
    reason_code: str


def run(llm: LLM, perm: Permission, prof: Profile, payments: list[Payment]) -> dict | None:
    if perm.kind != "unknown":
        return None
    version, system = prompts.load("explain_permission")
    data = {
        "payments": [{"date": p.at.date().isoformat(), "amount": fmt(p.amount)} for p in payments[-24:]],
        "interval_days_median": prof.interval_days_median, "interval_days_mad": prof.interval_days_mad,
    }
    out = guard.check("explain_permission", llm.complete_json("explain_permission", system, json.dumps(data)),
                      _Out, vocab=VOCAB, code_fields=("reason_code",))
    if out is None:
        return None
    return {"kind": out.kind, "reason_code": out.reason_code, "marker": "◆",
            "model": llm.model, "prompt_version": version}
