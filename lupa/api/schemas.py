"""Request and response bodies. All amounts are integer minor units (EUR cents)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Rule3 = Literal["allow", "require_approval", "block"]


class Envelope(BaseModel):
    marker: str = "◇"
    proposed: bool = True
    data: Any = None
    paypal: dict | None = None


class PolicyIn(BaseModel):
    max_amount: int = Field(gt=0, description="minor units")
    currency: str = "EUR"
    recurring: Rule3 = "allow"
    amount_increase: Rule3 = "require_approval"
    increase_tolerance_pct: int = 20
    new_merchant: Rule3 = "require_approval"
    max_per_month: int | None = None
    expires_at: datetime | None = None
    created_by: Literal["human", "ai_draft_accepted"] = "human"
    intent_text: str | None = None


class IntentIn(BaseModel):
    text: str = Field(min_length=3, max_length=300)


class DelegateIn(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)
    authority: Literal["propose", "approve"] = "propose"
    max_amount: int = Field(gt=0)
    recurring_allowed: bool = False
    amount_change_pct: int = 20
    min_confidence: float = Field(default=0.95, ge=0, le=1)
    expires_at: datetime


class Assessment(BaseModel):
    decision: Literal["approve", "escalate", "reject"]
    confidence: float = Field(ge=0, le=1)
    reason: str | None = Field(default=None, max_length=300)


class PaymentRequestIn(BaseModel):
    amount: int = Field(gt=0, description="minor units")
    currency: str = "EUR"
    merchant_alias: str | None = None
    is_recurring: bool = False
    purpose: str | None = Field(default=None, max_length=200)
    execute: bool | None = Field(default=None, description="call PayPal; default: when credentials exist")
    source: Literal["webhook", "scenario", "agent", "api"] = "api"
    assessment: Assessment | None = Field(default=None, description="an agent's own view, stored as an AI verdict")


class ResolveIn(BaseModel):
    action: Literal["approve", "reject"]


class AgentPermissionIn(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=64, description="what the agent buys, e.g. 'Shopping'")
    category: str = "marketplace"
