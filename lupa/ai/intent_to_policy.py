"""◆ One sentence of intent -> a draft policy. Nothing is stored until the human applies it."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel

from ..ledger.models import Policy
from ..money import parse_amount
from . import guard, prompts
from .llm import LLM

VOCAB = {"INTENT_THRESHOLD", "INTENT_RECURRING_APPROVAL", "INTENT_RECURRING_BLOCK",
         "INTENT_INCREASE_APPROVAL", "INTENT_NO_NEW_MERCHANTS", "INTENT_MONTHLY_CAP", "INTENT_AMBIGUOUS"}
Rule3 = Literal["allow", "require_approval", "block"]


class _Out(BaseModel):
    max_amount: float | None = None
    recurring: Rule3 = "require_approval"
    amount_increase: Rule3 = "require_approval"
    increase_tolerance_pct: float | None = None
    new_merchant: Rule3 = "require_approval"
    max_per_month: float | None = None
    reason_codes: list[str] = []


class PolicyDraft(BaseModel):
    policy: Policy
    reason_codes: list[str]
    model: str
    prompt_version: str


def run(llm: LLM, text: str, default: Policy) -> PolicyDraft | None:
    version, system = prompts.load("intent_to_policy")
    context = {
        "currency": default.currency,
        "current_default": {
            "max_amount": default.max_amount / 100, "recurring": default.recurring,
            "amount_increase": default.amount_increase,
            "increase_tolerance_pct": default.increase_tolerance_pct,
            "new_merchant": default.new_merchant,
        },
    }
    user = f"Sentence: {text}\nContext: {json.dumps(context)}"
    out = guard.check(
        "intent_to_policy", llm.complete_json("intent_to_policy", system, user), _Out,
        vocab=VOCAB, number_fields=("max_amount", "increase_tolerance_pct", "max_per_month"),
        context={"text": text, **context},
    )
    if out is None:
        return None
    pol = Policy(
        permission_id=None,
        max_amount=parse_amount(out.max_amount) if out.max_amount is not None else default.max_amount,
        currency=default.currency,
        recurring=out.recurring,
        amount_increase=out.amount_increase,
        increase_tolerance_pct=int(out.increase_tolerance_pct) if out.increase_tolerance_pct is not None
        else default.increase_tolerance_pct,
        new_merchant=out.new_merchant,
        max_per_month=parse_amount(out.max_per_month) if out.max_per_month is not None else None,
        created_by="ai_draft_accepted",
        intent_text=text,
    )
    if "INTENT_AMBIGUOUS" in out.reason_codes:
        # The strictest reading: nothing is allowed that was not clearly allowed.
        pol.recurring = "require_approval" if pol.recurring == "allow" else pol.recurring
        pol.amount_increase = "require_approval" if pol.amount_increase == "allow" else pol.amount_increase
        pol.new_merchant = "require_approval" if pol.new_merchant == "allow" else pol.new_merchant
    return PolicyDraft(policy=pol, reason_codes=out.reason_codes, model=llm.model, prompt_version=version)
