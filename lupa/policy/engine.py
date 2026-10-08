"""The policy engine (■). Pure. No IO, no clock, no network.

The only thing in Lupa that can say ALLOW. The time used for expiry checks is
the request's own `requested_at`, so the same inputs always give the same
decision.

Two passes:
  1. deterministic rules R01-R21 give the policy verdict, blind to the AI;
  2. AI rules R30-R32 can only add HOLD on top of it.

So `final` is never less strict than `policy_verdict`. That is the authority
invariant, and tests/test_policy_engine.py checks it on random inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import config
from ..ledger.models import AiVerdict, Delegation, PaymentRequest, Permission, Policy, Profile, RuleHit
from .rules import AI_UNAVAILABLE_WITHIN_HARD_LIMITS, RULES, stricter


@dataclass
class Evaluation:
    policy_verdict: str
    final: str
    rule_hits: list[RuleHit] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    @property
    def rule_ids(self) -> list[str]:
        return [h.rule for h in self.rule_hits]


def _hit(hits: list[RuleHit], rule: str, **values) -> None:
    hits.append(RuleHit(rule=rule, verdict=RULES[rule][0], values=values))


def _combine(hits: list[RuleHit]) -> str:
    verdict = "ALLOW"
    for h in hits:
        verdict = stricter(verdict, h.verdict)
    return verdict


def deterministic(req: PaymentRequest, perm: Permission, prof: Profile | None, pol: Policy,
                  dlg: Delegation | None, month_total: int = 0) -> list[RuleHit]:
    """R01-R21. Never looks at the AI."""
    hits: list[RuleHit] = []
    now = req.requested_at
    amount = req.amount
    new_merchant = req.merchant_alias != perm.merchant_alias

    if perm.status in ("revoked", "expired", "suspended"):
        _hit(hits, "R01", status=perm.status)
    if pol.expires_at is not None and pol.expires_at <= now:
        _hit(hits, "R02", expires_at=pol.expires_at.isoformat())
    if req.currency != pol.currency:
        _hit(hits, "R03", request_currency=req.currency, policy_currency=pol.currency)
    if req.is_recurring and pol.recurring == "block":
        _hit(hits, "R04", is_recurring=True, recurring=pol.recurring, amount=amount, max_amount=pol.max_amount)
    elif new_merchant and pol.new_merchant == "block":
        _hit(hits, "R04", merchant=req.merchant_alias, expected=perm.merchant_alias, new_merchant=pol.new_merchant)

    if amount > pol.max_amount:
        _hit(hits, "R10", amount=amount, max_amount=pol.max_amount)
    if req.is_recurring and pol.recurring == "require_approval":
        _hit(hits, "R11", is_recurring=True)

    if prof is not None and prof.n_payments > 0 and prof.amount_median:
        ceiling = prof.amount_median * (1 + pol.increase_tolerance_pct / 100)
        if amount > ceiling:
            if pol.amount_increase == "require_approval":
                _hit(hits, "R12", amount=amount, median=prof.amount_median, tolerance_pct=pol.increase_tolerance_pct)
            elif pol.amount_increase == "block":
                _hit(hits, "R13", amount=amount, median=prof.amount_median, tolerance_pct=pol.increase_tolerance_pct)

    if new_merchant and pol.new_merchant == "require_approval":
        _hit(hits, "R14", merchant=req.merchant_alias, expected=perm.merchant_alias)
    if pol.max_per_month is not None and month_total + amount > pol.max_per_month:
        _hit(hits, "R15", month_total=month_total, amount=amount, max_per_month=pol.max_per_month)
    if {"DORMANT_12M", "NO_HISTORY"} & set(perm.attention):
        _hit(hits, "R16", attention=sorted({"DORMANT_12M", "NO_HISTORY"} & set(perm.attention)))

    if dlg is not None:
        if dlg.authority == "propose":
            _hit(hits, "R20", agent_id=dlg.agent_id, authority=dlg.authority)
        why = []
        if amount > dlg.max_amount:
            why.append("amount")
        if req.is_recurring and not dlg.recurring_allowed:
            why.append("recurring")
        if prof is not None and prof.amount_median and prof.n_payments > 0:
            change = (amount - prof.amount_median) / prof.amount_median * 100
            if change > dlg.amount_change_pct:
                why.append("change")
        if dlg.expires_at <= now or (dlg.revoked_at is not None and dlg.revoked_at <= now):
            why.append("expired")
        if why:
            _hit(hits, "R21", why=why, amount=amount, delegation_max=dlg.max_amount,
                 recurring_allowed=dlg.recurring_allowed, amount_change_pct=dlg.amount_change_pct)
    elif req.agent_id:
        # An agent with no delegation on this permission has no authority at all.
        _hit(hits, "R21", why=["no_delegation"], agent_id=req.agent_id)
    return hits


def evaluate(req: PaymentRequest, perm: Permission, prof: Profile | None, pol: Policy,
             dlg: Delegation | None, ai: AiVerdict | None, *, month_total: int = 0) -> Evaluation:
    hits = deterministic(req, perm, prof, pol, dlg, month_total)
    policy_verdict = _combine(hits)
    reason_codes: list[str] = []

    min_conf = dlg.min_confidence if dlg is not None else config.DEFAULT_MIN_CONFIDENCE
    if ai is None:
        within_hard_limits = (
            not hits and req.amount <= pol.max_amount and pol.recurring == "allow"
        )
        if within_hard_limits:
            reason_codes.append(AI_UNAVAILABLE_WITHIN_HARD_LIMITS)
        else:
            _hit(hits, "R32", ai="unavailable")
    elif ai.verdict == "reject":
        _hit(hits, "R30", verdict=ai.verdict, confidence=ai.confidence)
    elif ai.verdict == "escalate" or ai.confidence < min_conf:
        _hit(hits, "R31", verdict=ai.verdict, confidence=ai.confidence, min_confidence=min_conf)

    final = stricter(policy_verdict, _combine(hits))
    return Evaluation(policy_verdict=policy_verdict, final=final, rule_hits=hits, reason_codes=reason_codes)


def combine_ai(*verdicts: AiVerdict | None) -> AiVerdict | None:
    """Stricter of several assessments (Lupa's model and an agent's own).

    Worst verdict, lowest confidence, union of reason codes. None if none given.
    """
    present = [v for v in verdicts if v is not None]
    if not present:
        return None
    order = {"approve": 0, "escalate": 1, "reject": 2}
    worst = max(present, key=lambda v: order[v.verdict])
    codes: list[str] = []
    for v in present:
        codes += [c for c in v.reason_codes if c not in codes]
    return AiVerdict(
        verdict=worst.verdict,
        confidence=min(v.confidence for v in present),
        reason_codes=codes,
        source="+".join(v.source for v in present),
        model=worst.model,
        prompt_version=worst.prompt_version,
    )
