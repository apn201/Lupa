"""The main scenario against the real PayPal sandbox. Skipped unless LUPA_LIVE=1.

Needs .env with sandbox credentials and a test card. Creates real sandbox orders.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("LUPA_LIVE") != "1", reason="set LUPA_LIVE=1 to run against the sandbox")


def test_allow_captures_and_hold_voids(tmp_path):
    from lupa.config import settings_from_env
    from lupa.ledger.db import Database
    from lupa.service import Lupa

    from .conftest import KNOWN, SAMPLE

    s = settings_from_env()
    assert s.paypal_enabled and s.card_number, "sandbox credentials and LUPA_TEST_CARD_NUMBER needed"
    from lupa.ai.llm import LLM
    # No model here: this tests PayPal execution, not the assessment.
    lp = Lupa(s, db=Database(tmp_path / "live.db"), llm=LLM(s, backend=None))
    lp.import_csv(str(SAMPLE), str(KNOWN))
    c = lp.repo.permission_by_alias("Merchant C")[0]

    ok = lp.request_payment(c.id, 1890, "EUR", None, True, execute=True)
    assert ok.data["request"]["state"] == "captured", ok.data
    assert any(call.path.endswith("/capture") and call.paypal_id for call in ok.calls)

    held = lp.request_payment(c.id, 8990, "EUR", None, True, execute=True)
    assert held.data["request"]["state"] == "held" and held.data["request"]["paypal_authorization_id"]
    rejected = lp.resolve(held.data["request"]["id"], "reject")
    assert rejected.data["request"]["state"] == "voided"
