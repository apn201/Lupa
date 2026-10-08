"""Deterministic kind and attention flags (build spec 4). No model in this module.

Only `unknown` is ever handed to the AI, and its opinion is stored as a
suggestion next to the kind, never as the kind.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .. import config
from ..ledger.models import Profile
from .profile import intervals

ATTENTION_CODES = (
    "DORMANT_6M", "DORMANT_12M", "AMOUNT_JUMP", "INTERVAL_BREAK",
    "ONE_OFF_STILL_ACTIVE", "NO_HISTORY", "NEW_LAST_30D",
)


def regular_interval(days: float | None) -> bool:
    if days is None:
        return False
    d = round(days)
    return d in config.MONTHLY_DAYS or d in config.WEEKLY_DAYS or d in config.YEARLY_DAYS


def kind_of(prof: Profile, has_agreement: bool) -> str:
    n = prof.n_payments
    if n >= 3 and regular_interval(prof.interval_days_median) and prof.amount_median:
        spread = (prof.amount_max - prof.amount_min) / prof.amount_median
        return "fixed_recurring" if spread < config.FIXED_SPREAD_MAX else "variable_recurring"
    if n <= 2 and has_agreement:
        return "one_time_authority"
    return "unknown"


def attention(prof: Profile, kind: str, status: str, payments: list[tuple[datetime, int]],
              first_seen: datetime | None, now: datetime) -> list[str]:
    flags: list[str] = []
    active = status == "active"
    msl = prof.months_since_last
    if active and msl is not None:
        if msl >= 12:
            flags.append("DORMANT_12M")
        elif msl >= 6:
            flags.append("DORMANT_6M")
    if prof.n_payments >= 3 and prof.amount_median:
        last = sorted(payments)[-1][1]
        if last > config.AMOUNT_JUMP_RATIO * prof.amount_median:
            flags.append("AMOUNT_JUMP")
    if prof.n_payments >= 3 and prof.interval_days_median:
        gaps = intervals(payments)
        if any(g > 2 * prof.interval_days_median for g in gaps):
            flags.append("INTERVAL_BREAK")
    if kind == "one_time_authority" and active:
        flags.append("ONE_OFF_STILL_ACTIVE")
    if active and prof.n_payments == 0:
        flags.append("NO_HISTORY")
    if first_seen is not None and now - first_seen <= timedelta(days=30):
        flags.append("NEW_LAST_30D")
    return flags
