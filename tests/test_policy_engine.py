"""The policy engine, rule by rule, and the authority invariant.

The invariant (build spec 0.2): an AI verdict can turn ALLOW into HOLD; it can
never turn HOLD or BLOCK into ALLOW. Never skip these tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings as hsettings, strategies as st

from lupa.ledger.models import AiVerdict, Delegation, PaymentRequest, Permission, Policy, Profile
from lupa.policy import engine, sentences
from lupa.policy.rules import RULES, STRICTNESS

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def perm(**kw):
    base = dict(source="paypal_sub", external_ref="I-1", merchant_alias="Merchant C", kind="variable_recurring")
    base.update(kw)
    return Permission(**base)


def prof(**kw):
    base = dict(permission_id="pp_1", n_payments=6, amount_min=1750, amount_max=2130, amount_median=1890,
                amount_p95=2130, interval_days_median=30.6)
    base.update(kw)
    return Profile(**base)


def pol(**kw):
    base = dict(max_amount=2500, recurring="allow", amount_increase="require_approval",
                new_merchant="require_approval")
    base.update(kw)
    return Policy(**base)


def req(**kw):
    base = dict(permission_id="pp_1", amount=1890, merchant_alias="Merchant C", is_recurring=True, requested_at=NOW)
    base.update(kw)
    return PaymentRequest(**base)


def dlg(**kw):
    base = dict(permission_id="pp_1", agent_id="shopping-agent", authority="approve", max_amount=8000,
                recurring_allowed=True, amount_change_pct=500, expires_at=NOW + timedelta(days=7))
    base.update(kw)
    return Delegation(**base)


APPROVE = AiVerdict(verdict="approve", confidence=0.99)


def ev(r=None, p=None, pr="default", po=None, d=None, ai=APPROVE, month_total=0):
    return engine.evaluate(r or req(), p or perm(), prof() if pr == "default" else pr, po or pol(), d, ai,
                           month_total=month_total)


# ---------------------------------------------------------------- rule by rule
def test_allow_when_nothing_fires():
    e = ev()
    assert e.final == "ALLOW" and e.policy_verdict == "ALLOW" and e.rule_hits == []


@pytest.mark.parametrize("status", ["revoked", "expired", "suspended"])
def test_r01_status(status):
    assert ev(p=perm(status=status)).final == "BLOCK"
    assert "R01" in ev(p=perm(status=status)).rule_ids


def test_r02_policy_expired():
    e = ev(po=pol(expires_at=NOW - timedelta(seconds=1)))
    assert e.final == "BLOCK" and "R02" in e.rule_ids


def test_r03_currency():
    e = ev(r=req(currency="USD"))
    assert e.final == "BLOCK" and "R03" in e.rule_ids


def test_r04_recurring_blocked():
    e = ev(po=pol(recurring="block"))
    assert e.final == "BLOCK" and "R04" in e.rule_ids


def test_r04_new_merchant_blocked():
    e = ev(r=req(merchant_alias="Merchant X", is_recurring=False), po=pol(new_merchant="block"))
    assert e.final == "BLOCK" and "R04" in e.rule_ids


def test_r10_over_limit():
    e = ev(r=req(amount=8990), pr=None)
    assert e.final == "HOLD" and e.rule_ids == ["R10"]


def test_r11_recurring_needs_approval():
    e = ev(po=pol(recurring="require_approval"))
    assert e.final == "HOLD" and e.rule_ids == ["R11"]


def test_r12_increase_needs_approval():
    e = ev(r=req(amount=2400))
    assert e.final == "HOLD" and e.rule_ids == ["R12"]


def test_r13_increase_blocked():
    e = ev(r=req(amount=2400), po=pol(amount_increase="block"))
    assert e.final == "BLOCK" and e.rule_ids == ["R13"]


def test_increase_allowed_when_policy_allows():
    assert ev(r=req(amount=2400), po=pol(amount_increase="allow")).final == "ALLOW"


def test_r14_new_merchant():
    e = ev(r=req(merchant_alias="Merchant X", amount=1200, is_recurring=False))
    assert e.final == "HOLD" and e.rule_ids == ["R14"]


def test_new_merchant_allowed():
    assert ev(r=req(merchant_alias="Merchant X"), po=pol(new_merchant="allow")).final == "ALLOW"


def test_r15_monthly_cap():
    e = ev(po=pol(max_per_month=3000), month_total=1500)
    assert e.final == "HOLD" and e.rule_ids == ["R15"]
    assert ev(po=pol(max_per_month=3000), month_total=1000).final == "ALLOW"


@pytest.mark.parametrize("flag", ["DORMANT_12M", "NO_HISTORY"])
def test_r16_silent_permission(flag):
    e = ev(p=perm(attention=[flag]))
    assert e.final == "HOLD" and e.rule_ids == ["R16"]


def test_r20_propose_only():
    e = ev(r=req(agent_id="shopping-agent"), d=dlg(authority="propose"))
    assert e.final == "HOLD" and e.rule_ids == ["R20"]


@pytest.mark.parametrize("kw,dkw,why", [
    ({"amount": 12000}, {"max_amount": 8000}, "amount"),
    ({}, {"recurring_allowed": False}, "recurring"),
    ({"amount": 2400}, {"amount_change_pct": 10}, "change"),
    ({}, {"expires_at": NOW - timedelta(hours=1)}, "expired"),
    ({}, {"revoked_at": NOW - timedelta(hours=1)}, "expired"),
])
def test_r21_outside_delegation(kw, dkw, why):
    e = ev(r=req(agent_id="shopping-agent", **kw), po=pol(max_amount=99999, amount_increase="allow"), d=dlg(**dkw))
    assert e.final == "HOLD"
    hit = next(h for h in e.rule_hits if h.rule == "R21")
    assert why in hit.values["why"]


def test_r21_agent_without_delegation():
    e = ev(r=req(agent_id="stranger"))
    assert e.final == "HOLD" and "R21" in e.rule_ids


def test_r30_reject_is_hold_not_block():
    e = ev(ai=AiVerdict(verdict="reject", confidence=0.99))
    assert e.final == "HOLD" and e.rule_ids == ["R30"]


def test_r31_escalate_and_low_confidence():
    assert ev(ai=AiVerdict(verdict="escalate", confidence=0.99)).rule_ids == ["R31"]
    assert ev(ai=AiVerdict(verdict="approve", confidence=0.90)).rule_ids == ["R31"]


def test_r31_uses_delegation_threshold():
    r = req(agent_id="shopping-agent")
    assert ev(r=r, d=dlg(min_confidence=0.8), ai=AiVerdict(verdict="approve", confidence=0.85)).final == "ALLOW"
    assert ev(r=r, d=dlg(min_confidence=0.9), ai=AiVerdict(verdict="approve", confidence=0.85)).final == "HOLD"


def test_r32_ai_unavailable_within_hard_limits_allows():
    e = ev(ai=None)
    assert e.final == "ALLOW" and e.reason_codes == ["AI_UNAVAILABLE_WITHIN_HARD_LIMITS"]


def test_r32_ai_unavailable_otherwise_holds():
    assert ev(ai=None, po=pol(recurring="require_approval"), r=req(is_recurring=False)).rule_ids == ["R32"]
    assert "R32" in ev(ai=None, r=req(amount=9000), pr=None).rule_ids


def test_block_beats_hold():
    e = ev(p=perm(status="revoked"), r=req(amount=9000))
    assert e.final == "BLOCK" and {"R01", "R10"} <= set(e.rule_ids)


def test_combine_ai_takes_the_stricter():
    a = AiVerdict(verdict="approve", confidence=0.99, reason_codes=["AMOUNT_IN_RANGE"])
    b = AiVerdict(verdict="escalate", confidence=0.97, reason_codes=["MERCHANT_UNKNOWN"])
    c = engine.combine_ai(a, None, b)
    assert c.verdict == "escalate" and c.confidence == 0.97
    assert c.reason_codes == ["AMOUNT_IN_RANGE", "MERCHANT_UNKNOWN"]
    assert engine.combine_ai(None, None) is None


def test_every_rule_has_a_sentence():
    for rule in RULES:
        assert rule in sentences.RULE_SENTENCES


def test_sentence_numbers_come_from_values():
    e = ev(r=req(amount=8990), pr=None)
    text = sentences.for_rule("R10", e.rule_hits[0].values)
    assert text == "Above your limit of 25.00 EUR."


# ---------------------------------------------------------- the invariant
ai_strategy = st.one_of(
    st.none(),
    st.builds(AiVerdict, verdict=st.sampled_from(["approve", "escalate", "reject"]),
              confidence=st.floats(0, 1, allow_nan=False)),
)
rule3 = st.sampled_from(["allow", "require_approval", "block"])


@st.composite
def scenario(draw):
    p = perm(status=draw(st.sampled_from(["active", "active", "active", "revoked", "suspended", "expired"])),
             attention=draw(st.lists(st.sampled_from(["DORMANT_12M", "NO_HISTORY", "AMOUNT_JUMP"]), max_size=2)))
    n = draw(st.integers(0, 12))
    median = draw(st.integers(100, 20000))
    pr = draw(st.one_of(st.none(), st.just(prof(n_payments=n, amount_median=median if n else None,
                                                 amount_min=median // 2, amount_max=median * 2))))
    po = pol(
        max_amount=draw(st.integers(100, 30000)),
        currency=draw(st.sampled_from(["EUR", "EUR", "USD"])),
        recurring=draw(rule3), amount_increase=draw(rule3), new_merchant=draw(rule3),
        increase_tolerance_pct=draw(st.integers(0, 100)),
        max_per_month=draw(st.one_of(st.none(), st.integers(100, 50000))),
        expires_at=draw(st.one_of(st.none(), st.just(NOW - timedelta(days=1)), st.just(NOW + timedelta(days=1)))),
    )
    agent = draw(st.one_of(st.none(), st.just("shopping-agent")))
    r = req(amount=draw(st.integers(1, 40000)), currency=draw(st.sampled_from(["EUR", "EUR", "USD"])),
            merchant_alias=draw(st.sampled_from(["Merchant C", "Merchant C", "Merchant X"])),
            is_recurring=draw(st.booleans()), agent_id=agent)
    d = None
    if agent and draw(st.booleans()):
        d = dlg(authority=draw(st.sampled_from(["propose", "approve"])), max_amount=draw(st.integers(100, 30000)),
                recurring_allowed=draw(st.booleans()), amount_change_pct=draw(st.integers(0, 200)),
                min_confidence=draw(st.floats(0, 1, allow_nan=False)),
                expires_at=draw(st.sampled_from([NOW - timedelta(days=1), NOW + timedelta(days=1)])))
    return r, p, pr, po, d, draw(st.integers(0, 50000))


@hsettings(max_examples=1000, deadline=None)
@given(scenario(), ai_strategy, ai_strategy)
def test_authority_invariant(sc, ai_a, ai_b):
    """AI can never turn HOLD or BLOCK into ALLOW."""
    r, p, pr, po, d, month_total = sc
    blind = engine.evaluate(r, p, pr, po, d, None, month_total=month_total)
    a = engine.evaluate(r, p, pr, po, d, ai_a, month_total=month_total)
    b = engine.evaluate(r, p, pr, po, d, ai_b, month_total=month_total)

    for e in (blind, a, b):
        # final is never less strict than the deterministic, AI-blind policy verdict
        assert STRICTNESS[e.final] >= STRICTNESS[e.policy_verdict]
        # the policy verdict does not depend on the AI at all
        assert e.policy_verdict == blind.policy_verdict
    # when the deterministic rules hold or block, no AI verdict produces ALLOW
    if blind.policy_verdict != "ALLOW":
        assert a.final != "ALLOW" and b.final != "ALLOW"
    # a BLOCK is a BLOCK whatever the AI says
    if blind.final == "BLOCK":
        assert a.final == "BLOCK" and b.final == "BLOCK"
    # AI rules only ever add HOLD
    for e in (a, b):
        assert all(h.verdict == "HOLD" for h in e.rule_hits if h.rule in ("R30", "R31", "R32"))
