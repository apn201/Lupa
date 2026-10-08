"""◆ Assess a payment request: verdict, confidence, reason codes. Nothing else.

The caller attaches the numbers (ratio, range) from the profile; the model
only picks codes and a confidence. The engine decides.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from ..ledger.models import AiVerdict, PaymentRequest, Permission, Profile
from ..money import fmt
from . import guard, prompts
from .llm import LLM

VOCAB = {"AMOUNT_IN_RANGE", "AMOUNT_ABOVE_RANGE", "AMOUNT_RATIO", "MERCHANT_MATCH", "MERCHANT_UNKNOWN",
         "INTERVAL_MATCH", "INTERVAL_EARLY", "FIRST_CHARGE", "DORMANT_REACTIVATED"}


class _Out(BaseModel):
    verdict: Literal["approve", "escalate", "reject"]
    confidence: float = Field(ge=0, le=1)
    reason_codes: list[str] = []


def facts(req: PaymentRequest, perm: Permission, prof: Profile | None) -> dict:
    """The small table the model sees. Also the source of numbers for the sentences."""
    days_since = None
    if perm.last_payment_at is not None:
        days_since = round((req.requested_at - perm.last_payment_at).total_seconds() / 86400, 1)
    return {
        "request": {"amount": fmt(req.amount), "currency": req.currency, "merchant": req.merchant_alias,
                    "is_recurring": req.is_recurring},
        "permission": {"merchant": perm.merchant_alias, "kind": perm.kind, "attention": perm.attention},
        "history": None if prof is None or not prof.n_payments else {
            "payments": prof.n_payments, "min": fmt(prof.amount_min), "median": fmt(prof.amount_median),
            "max": fmt(prof.amount_max), "interval_days_median": prof.interval_days_median,
            "days_since_last": days_since,
            "ratio_to_median": round(req.amount / prof.amount_median, 2) if prof.amount_median else None,
        },
    }


def run(llm: LLM, req: PaymentRequest, perm: Permission, prof: Profile | None) -> AiVerdict | None:
    version, system = prompts.load("assess_payment")
    out = guard.check("assess_payment",
                      llm.complete_json("assess_payment", system, json.dumps(facts(req, perm, prof))),
                      _Out, vocab=VOCAB)
    if out is None:
        return None
    return AiVerdict(verdict=out.verdict, confidence=out.confidence, reason_codes=out.reason_codes,
                     source="lupa_ai", model=llm.model, prompt_version=version)
