"""◆ Pick a limit from candidates code computed. Code clamps the pick to [max, 2 x max]."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from ..ledger.models import Profile
from ..money import ceil5, fmt
from . import guard, prompts
from .llm import LLM

VOCAB = {"LIMIT_SEASONAL_ROOM", "LIMIT_TIGHT", "LIMIT_STABLE"}


class _Out(BaseModel):
    pick: int = Field(ge=0, le=2)
    reason_code: Literal["LIMIT_SEASONAL_ROOM", "LIMIT_TIGHT", "LIMIT_STABLE"]


class LimitSuggestion(BaseModel):
    candidates: list[int]
    pick: int
    limit: int
    reason_code: str | None
    by: Literal["ai", "policy"]
    model: str | None = None
    prompt_version: str | None = None


def candidates(prof: Profile) -> list[int]:
    return [
        ceil5(prof.amount_max * 1.15),
        ceil5(prof.amount_p95 * 1.25),
        ceil5(prof.amount_median * 1.5),
    ]


def clamp(value: int, prof: Profile) -> int:
    return max(prof.amount_max, min(value, 2 * prof.amount_max))


def run(llm: LLM, prof: Profile) -> LimitSuggestion | None:
    if not prof.n_payments or prof.amount_max is None:
        return None
    cands = candidates(prof)
    version, system = prompts.load("suggest_limit")
    table = {
        "payments": prof.n_payments, "min": fmt(prof.amount_min), "median": fmt(prof.amount_median),
        "p95": fmt(prof.amount_p95), "max": fmt(prof.amount_max),
        "interval_days_median": prof.interval_days_median, "amount_trend_pct": prof.amount_trend,
        "candidates": [fmt(c) for c in cands],
    }
    out = guard.check("suggest_limit", llm.complete_json("suggest_limit", system, json.dumps(table)),
                      _Out, vocab=VOCAB, code_fields=("reason_code",))
    if out is None:
        # Fallback is deterministic and labelled ■, not ◆.
        return LimitSuggestion(candidates=cands, pick=0, limit=clamp(cands[0], prof), reason_code=None, by="policy")
    return LimitSuggestion(candidates=cands, pick=out.pick, limit=clamp(cands[out.pick], prof),
                           reason_code=out.reason_code, by="ai", model=llm.model, prompt_version=version)
