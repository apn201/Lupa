"""Behaviour statistics per permission. Pure functions over payments."""

from __future__ import annotations

import math
from datetime import datetime
from statistics import median

from ..ledger.models import Profile

DAYS_PER_MONTH = 30.44


def p95(values: list[int]) -> int:
    """Nearest-rank 95th percentile."""
    s = sorted(values)
    rank = max(1, math.ceil(0.95 * len(s)))
    return s[rank - 1]


def compute(permission_id: str, payments: list[tuple[datetime, int]], now: datetime,
            last_known: datetime | None = None) -> Profile:
    """payments: (at, amount) with refunds already excluded."""
    pays = sorted(payments)
    amounts = [a for _, a in pays]
    prof = Profile(permission_id=permission_id, n_payments=len(pays), computed_at=now)
    last_at = pays[-1][0] if pays else last_known
    if last_at is not None:
        prof.months_since_last = round((now - last_at).total_seconds() / 86400 / DAYS_PER_MONTH, 2)
    if not amounts:
        return prof
    med = median(amounts)
    prof.amount_min = min(amounts)
    prof.amount_max = max(amounts)
    prof.amount_median = int(round(med))
    prof.amount_p95 = p95(amounts)
    if med:
        prof.amount_trend = round((amounts[-1] - med) / med * 100, 1)
    if len(pays) >= 2:
        gaps = [(b[0] - a[0]).total_seconds() / 86400 for a, b in zip(pays, pays[1:])]
        gmed = median(gaps)
        prof.interval_days_median = round(gmed, 2)
        prof.interval_days_mad = round(median(abs(g - gmed) for g in gaps), 2)
    return prof


def intervals(payments: list[tuple[datetime, int]]) -> list[float]:
    pays = sorted(payments)
    return [(b[0] - a[0]).total_seconds() / 86400 for a, b in zip(pays, pays[1:])]
