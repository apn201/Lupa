"""The AI layer: recorded answers per task, the guard, cost control, the ai=None path."""

from __future__ import annotations

import json

from lupa.ai import assess_payment, explain_permission, guard, intent_to_policy, suggest_limit
from lupa.ai.llm import LLM, ChatResult, CostGate, extract_json
from lupa.ledger.models import PaymentRequest, Permission, Policy, Profile

from .conftest import NOW, FakeBackend, make_llm

DEFAULT = Policy(max_amount=5000)
PROF = Profile(permission_id="pp_1", n_payments=6, amount_min=1750, amount_max=2130, amount_median=1890,
               amount_p95=2130, interval_days_median=30.6)
PERM = Permission(source="paypal_sub", external_ref="I-1", merchant_alias="Merchant C", kind="variable_recurring")


def llm_with(settings, **answers):
    return make_llm(settings, FakeBackend({k: v for k, v in answers.items()}))


# ------------------------------------------------------------ intent_to_policy
def test_intent_threshold(settings):
    ans = json.dumps({"max_amount": 20, "recurring": "allow", "amount_increase": "require_approval",
                      "increase_tolerance_pct": 20, "new_merchant": "require_approval", "max_per_month": None,
                      "reason_codes": ["INTENT_THRESHOLD"]})
    d = intent_to_policy.run(llm_with(settings, intent_to_policy=ans),
                             "Anything recurring over 20 euros needs me.", DEFAULT)
    assert d.policy.max_amount == 2000 and d.reason_codes == ["INTENT_THRESHOLD"]
    assert d.prompt_version == "intent_to_policy/2"


def test_intent_never_recurring(settings):
    ans = '{"max_amount": null, "recurring": "block", "amount_increase": "require_approval", ' \
          '"new_merchant": "require_approval", "reason_codes": ["INTENT_RECURRING_BLOCK"]}'
    d = intent_to_policy.run(llm_with(settings, intent_to_policy=ans),
                             "Let this shopping agent buy things but never start anything recurring.", DEFAULT)
    assert d.policy.recurring == "block" and d.policy.max_amount == DEFAULT.max_amount


def test_intent_invented_number_is_dropped(settings):
    ans = '{"max_amount": 250, "recurring": "allow", "reason_codes": ["INTENT_THRESHOLD"]}'
    assert intent_to_policy.run(llm_with(settings, intent_to_policy=ans),
                                "Anything recurring over 20 euros needs me.", DEFAULT) is None


def test_intent_unknown_code_is_dropped(settings):
    ans = '{"max_amount": 20, "recurring": "allow", "reason_codes": ["INTENT_YOLO"]}'
    assert intent_to_policy.run(llm_with(settings, intent_to_policy=ans), "over 20 euros", DEFAULT) is None


def test_intent_ambiguous_reads_strictly(settings):
    ans = '{"recurring": "allow", "amount_increase": "allow", "new_merchant": "allow", ' \
          '"reason_codes": ["INTENT_AMBIGUOUS"]}'
    d = intent_to_policy.run(llm_with(settings, intent_to_policy=ans), "do the thing", DEFAULT)
    assert (d.policy.recurring, d.policy.amount_increase, d.policy.new_merchant) == ("require_approval",) * 3


# --------------------------------------------------------------- suggest_limit
def test_suggest_limit_candidates_and_clamp(settings):
    s = suggest_limit.run(llm_with(settings, suggest_limit='{"pick": 1, "reason_code": "LIMIT_SEASONAL_ROOM"}'), PROF)
    assert s.candidates == [2500, 3000, 3000]
    assert s.limit == 3000 and s.by == "ai"
    assert PROF.amount_max <= s.limit <= 2 * PROF.amount_max


def test_suggest_limit_fallback_is_policy(settings):
    s = suggest_limit.run(llm_with(settings, suggest_limit="no json here"), PROF)
    assert s.by == "policy" and s.limit == 2500


# -------------------------------------------------------------- assess_payment
def test_assess_ok(settings):
    req = PaymentRequest(permission_id="pp_1", amount=1890, merchant_alias="Merchant C", requested_at=NOW)
    v = assess_payment.run(llm_with(settings, assess_payment=
                                    '{"verdict":"approve","confidence":0.97,"reason_codes":["AMOUNT_IN_RANGE"]}'),
                           req, PERM, PROF)
    assert v.verdict == "approve" and v.confidence == 0.97 and v.model == "fake-model"


def test_assess_reasoning_field_and_prose(settings):
    text = 'Let me think. The amount 18.90 fits. {"verdict":"escalate","confidence":0.6,"reason_codes":[]}'
    r = ChatResult(text=text, source="reasoning_content", content="", reasoning_content=text, model="m")
    assert extract_json(r)["verdict"] == "escalate"


def test_assess_bad_confidence_dropped(settings):
    req = PaymentRequest(permission_id="pp_1", amount=1890, merchant_alias="Merchant C", requested_at=NOW)
    assert assess_payment.run(llm_with(settings, assess_payment='{"verdict":"approve","confidence":1.7}'),
                              req, PERM, PROF) is None


def test_backend_failure_is_none(settings):
    req = PaymentRequest(permission_id="pp_1", amount=1890, merchant_alias="Merchant C", requested_at=NOW)
    assert assess_payment.run(make_llm(settings, FakeBackend()), req, PERM, PROF) is None
    assert assess_payment.run(LLM(settings, backend=None), req, PERM, PROF) is None


# ---------------------------------------------------------- explain_permission
def test_explain_only_unknown(settings):
    llm = llm_with(settings, explain_permission='{"kind":"variable_recurring","reason_code":"EXPLAIN_USAGE_BASED"}')
    assert explain_permission.run(llm, PERM, PROF, []) is None
    unknown = PERM.model_copy(update={"kind": "unknown"})
    assert explain_permission.run(llm, unknown, PROF, [])["kind"] == "variable_recurring"


# -------------------------------------------------------------------- guard
def test_guard_drops_planted_number():
    grounded = guard.known_numbers({"median": "18.90", "max": 2130})
    assert guard.ungrounded("18.90 is fine", grounded) == []
    assert guard.ungrounded("it was 47.10 last month", grounded) == ["47.10"]
    assert guard.ungrounded("3 payments", grounded) == []  # small counts allowed


# ------------------------------------------------------------- cost control
def test_hourly_cap_fails_closed(tmp_path):
    from .conftest import make_settings
    s = make_settings(tmp_path, llm_max_calls_per_hour=2)
    backend = FakeBackend(default='{"verdict":"approve","confidence":0.99}')
    llm = make_llm(s, backend)
    for _ in range(3):
        llm.complete_json("t", "sys", "user")
    assert len(backend.calls) == 2


def test_kill_switch(tmp_path):
    from .conftest import make_settings
    s = make_settings(tmp_path)
    (tmp_path / "OFF").write_text("")
    backend = FakeBackend(default="{}")
    assert make_llm(s, backend).complete_json("t", "s", "u") is None and backend.calls == []


def test_caps_survive_restart(tmp_path):
    from .conftest import make_settings
    s = make_settings(tmp_path, llm_max_calls_per_hour=1)
    CostGate(s).record()
    assert CostGate(s).allow() == (False, "hourly_cap")


def test_dotenv_last_line_wins_and_real_env_wins(tmp_path, monkeypatch):
    from lupa.config import load_dotenv
    env = tmp_path / ".env"
    env.write_text("LUPA_T_A=
LUPA_T_A=filled
LUPA_T_B=file
", encoding="utf-8")
    monkeypatch.delenv("LUPA_T_A", raising=False)
    monkeypatch.setenv("LUPA_T_B", "real")
    load_dotenv(env)
    import os
    assert os.environ["LUPA_T_A"] == "filled" and os.environ["LUPA_T_B"] == "real"
