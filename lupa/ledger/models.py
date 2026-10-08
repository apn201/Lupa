"""Pydantic models for every ledger row (build spec 3).

Money is integer minor units plus `currency`. Times are timezone-aware UTC.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["ALLOW", "HOLD", "BLOCK"]
Kind = Literal["fixed_recurring", "variable_recurring", "one_time_authority", "agent_authority", "unknown"]
PermStatus = Literal["active", "dormant", "suspended", "revoked", "expired"]
PermSource = Literal["paypal_sub", "paypal_pap", "paypal_order", "import_csv", "lupa_delegation"]
Rule3 = Literal["allow", "require_approval", "block"]
ReqState = Literal["received", "allowed", "held", "blocked", "captured", "voided", "expired"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


class Permission(BaseModel):
    id: str = Field(default_factory=lambda: new_id("pp"))
    source: PermSource
    external_ref: str
    merchant_alias: str
    merchant_category: str = "digital service"
    kind: Kind = "unknown"
    status: PermStatus = "active"
    first_seen: datetime | None = None
    last_payment_at: datetime | None = None
    last_amount: int | None = None
    currency: str = "EUR"
    created_at: datetime = Field(default_factory=utcnow)
    policy_id: str | None = None
    delegation_id: str | None = None
    attention: list[str] = Field(default_factory=list)
    marker: str = "●"
    suggestion: dict | None = None  # ◆ explain_permission output, never the kind


class Profile(BaseModel):
    permission_id: str
    n_payments: int = 0
    amount_min: int | None = None
    amount_max: int | None = None
    amount_median: int | None = None
    amount_p95: int | None = None
    interval_days_median: float | None = None
    interval_days_mad: float | None = None
    months_since_last: float | None = None
    amount_trend: float | None = None  # percent, last vs median
    computed_at: datetime = Field(default_factory=utcnow)


class Payment(BaseModel):
    id: str = Field(default_factory=lambda: new_id("pay"))
    permission_id: str
    paypal_txn_id: str | None = None
    amount: int
    currency: str = "EUR"
    at: datetime
    event_code: str = ""
    status: str = "S"
    source: Literal["paypal_search", "paypal_sub_txn", "import_csv", "lupa_capture"] = "import_csv"


class Policy(BaseModel):
    id: str = Field(default_factory=lambda: new_id("pol"))
    permission_id: str | None = None  # None = account default
    max_amount: int
    currency: str = "EUR"
    recurring: Rule3 = "allow"
    amount_increase: Rule3 = "require_approval"
    increase_tolerance_pct: int = 20
    new_merchant: Rule3 = "require_approval"
    max_per_month: int | None = None
    expires_at: datetime | None = None
    created_by: Literal["human", "ai_draft_accepted"] = "human"
    intent_text: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Delegation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dlg"))
    permission_id: str
    agent_id: str
    authority: Literal["propose", "approve"] = "propose"
    max_amount: int
    recurring_allowed: bool = False
    amount_change_pct: int = 20
    min_confidence: float = 0.95
    expires_at: datetime
    revoked_at: datetime | None = None


class PaymentRequest(BaseModel):
    id: str = Field(default_factory=lambda: new_id("req"))
    permission_id: str
    amount: int
    currency: str = "EUR"
    merchant_alias: str
    is_recurring: bool = False
    requested_at: datetime = Field(default_factory=utcnow)
    source: Literal["webhook", "scenario", "agent", "api"] = "api"
    agent_id: str | None = None
    purpose: str | None = None
    paypal_order_id: str | None = None
    paypal_authorization_id: str | None = None
    state: ReqState = "received"
    hold_until: datetime | None = None


class AiVerdict(BaseModel):
    verdict: Literal["approve", "escalate", "reject"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason_codes: list[str] = Field(default_factory=list)
    source: str = "lupa_ai"  # lupa_ai | agent:<id>
    model: str | None = None
    prompt_version: str | None = None


class RuleHit(BaseModel):
    rule: str
    verdict: Verdict
    values: dict = Field(default_factory=dict)


class Decision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dec"))
    request_id: str
    ai_verdict: str | None = None
    ai_confidence: float | None = None
    ai_reason_codes: list[str] = Field(default_factory=list)
    ai_model: str | None = None
    ai_prompt_version: str | None = None
    policy_verdict: Verdict
    rule_hits: list[RuleHit] = Field(default_factory=list)
    final: Verdict
    resolved_by: Literal["policy", "human", "expiry"] = "policy"
    resolved_at: datetime = Field(default_factory=utcnow)
    paypal_action: Literal["captured", "authorized", "voided", "none"] = "none"
    sentences: list[str] = Field(default_factory=list)


class Event(BaseModel):
    id: str = Field(default_factory=lambda: new_id("evt"))
    at: datetime = Field(default_factory=utcnow)
    kind: str
    ref_id: str | None = None
    marker: str
    payload: dict = Field(default_factory=dict)
