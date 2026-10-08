"""The proposed API against a respx-mocked PayPal sandbox, following demo_main.json."""

from __future__ import annotations

import itertools
import json
from datetime import timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from lupa.api.app import create_app
from lupa.ledger.db import Database
from lupa.ledger.models import PaymentRequest, Permission
from lupa.paypal.client import PayPalClient
from lupa.service import Lupa

from .conftest import KNOWN, NOW, SAMPLE, FakeBackend, make_llm, make_settings

BASE = "https://api-m.sandbox.paypal.com"
P = "/proposed/v1/me"


class FakePayPal:
    """Just enough of the sandbox: orders, authorize, capture, void, subscription cancel."""

    def __init__(self, router: respx.Router) -> None:
        self.n = itertools.count(1)
        self.seen_request_ids: list[str] = []
        self.cancelled: list[str] = []
        self.fail_orders = False
        self.router = r = router
        r.post(f"{BASE}/v1/oauth2/token").mock(return_value=httpx.Response(
            200, json={"access_token": "A21-test", "token_type": "Bearer", "expires_in": 32000}))
        r.post(f"{BASE}/v2/checkout/orders").mock(side_effect=self.order)
        r.post(url__regex=rf"{BASE}/v2/checkout/orders/(?P<oid>[^/]+)/authorize").mock(side_effect=self.authorize)
        r.post(url__regex=rf"{BASE}/v2/payments/authorizations/(?P<aid>[^/]+)/capture").mock(side_effect=self.capture)
        r.post(url__regex=rf"{BASE}/v2/payments/authorizations/(?P<aid>[^/]+)/void").mock(side_effect=self.void)
        r.post(url__regex=rf"{BASE}/v1/billing/subscriptions/(?P<sid>[^/]+)/cancel").mock(side_effect=self.cancel)

    def _rid(self, request):
        self.seen_request_ids.append(request.headers.get("PayPal-Request-Id"))

    def order(self, request):
        self._rid(request)
        if self.fail_orders:
            return httpx.Response(500, json={"name": "INTERNAL_SERVER_ERROR", "debug_id": "dbg1"})
        body = json.loads(request.content)
        assert body["intent"] == "AUTHORIZE" and body["payment_source"]["card"]["number"]
        return httpx.Response(201, json={"id": f"ORDER{next(self.n)}", "status": "CREATED"})

    def authorize(self, request, oid):
        self._rid(request)
        return httpx.Response(201, json={"id": oid, "status": "COMPLETED", "purchase_units": [
            {"payments": {"authorizations": [{"id": f"AUTH-{oid}", "status": "CREATED"}]}}]})

    def capture(self, request, aid):
        self._rid(request)
        assert json.loads(request.content)["final_capture"] is True
        return httpx.Response(201, json={"id": f"CAP-{aid}", "status": "COMPLETED"})

    def void(self, request, aid):
        self._rid(request)
        return httpx.Response(204)

    def cancel(self, request, sid):
        self._rid(request)
        self.cancelled.append(sid)
        return httpx.Response(204)


ASSESS = '{"verdict":"approve","confidence":0.97,"reason_codes":["AMOUNT_IN_RANGE","MERCHANT_MATCH"]}'


@pytest.fixture
def world(tmp_path):
    s = make_settings(tmp_path, paypal_client_id="cid", paypal_client_secret="sec", card_number="4111111111111111")
    with respx.mock(assert_all_called=False) as router:
        pp = FakePayPal(router)
        backend = FakeBackend({"assess_payment": ASSESS})
        lp = Lupa(s, db=Database(":memory:"), paypal=PayPalClient(s, http=httpx.Client()),
                  llm=make_llm(s, backend), clock=lambda: NOW)
        lp.import_csv(str(SAMPLE), str(KNOWN), now=NOW)
        app = create_app(lp, workers=False)
        with TestClient(app) as client:
            yield client, lp, pp, backend


def pid_of(lp: Lupa, alias: str) -> str:
    return lp.repo.permission_by_alias(alias)[0].id


def test_every_proposed_response_is_marked(world):
    client, lp, *_ = world
    r = client.get(f"{P}/payment-permissions")
    body = r.json()
    assert body["marker"] == "◇" and body["proposed"] is True
    assert body["data"]["headline"]["text"] == "22 companies can take money from you. 7 have not in over a year."


def test_demo_main(world):
    client, lp, pp, backend = world
    c = pid_of(lp, "Merchant C")
    client.put(f"{P}/payment-permissions/{c}/policy", json={"max_amount": 2500, "recurring": "allow"})

    # 1. 18.90 recurring -> ALLOW -> captured
    r = client.post(f"{P}/payment-permissions/{c}/requests", json={"amount": 1890, "is_recurring": True}).json()
    assert r["data"]["decision"]["final"] == "ALLOW"
    assert r["data"]["request"]["state"] == "captured"
    assert r["paypal"]["marker"] == "●"
    assert [c_["path"] for c_ in r["paypal"]["calls"]][-1].endswith("/capture")

    # 2. 89.90 recurring -> HOLD (R10), authorized only
    r = client.post(f"{P}/payment-permissions/{c}/requests", json={"amount": 8990, "is_recurring": True}).json()
    held = r["data"]["request"]
    assert r["data"]["decision"]["final"] == "HOLD"
    assert "R10" in [h["rule"] for h in r["data"]["decision"]["rule_hits"]]
    assert held["state"] == "held" and held["paypal_authorization_id"]
    assert "Above your limit of 25.00 EUR." in r["data"]["decision"]["sentences"]

    # 3. human approves -> capture
    q = client.get(f"{P}/requests?state=held").json()["data"]
    assert [x["id"] for x in q] == [held["id"]]
    r = client.post(f"{P}/requests/{held['id']}/resolve", json={"action": "approve"}).json()
    assert r["data"]["request"]["state"] == "captured" and r["data"]["decision"]["resolved_by"] == "human"
    assert r["paypal"]["calls"][0]["paypal_id"].startswith("CAP-")

    # 4. unknown merchant -> HOLD (R14)
    r = client.post(f"{P}/payment-permissions/{c}/requests",
                    json={"amount": 1200, "merchant_alias": "Merchant X"}).json()
    assert r["data"]["decision"]["final"] == "HOLD"
    assert "R14" in [h["rule"] for h in r["data"]["decision"]["rule_hits"]]

    # 5. an agent with its own permission, delegation max 80, asks for 120 -> HOLD (R21)
    exp = (NOW + timedelta(days=7)).isoformat()
    a = client.post(f"{P}/payment-permissions", json={"agent_id": "shopping-agent", "label": "Shopping"}).json()
    assert a["marker"] == "◇" and a["data"]["kind"] == "agent_authority"
    a = a["data"]["id"]
    client.put(f"{P}/payment-permissions/{a}/policy",
               json={"max_amount": 10000, "recurring": "block", "new_merchant": "allow"})
    client.post(f"{P}/payment-permissions/{a}/delegate", json={
        "agent_id": "shopping-agent", "authority": "approve", "max_amount": 8000, "expires_at": exp})
    hdr = {"X-Lupa-Agent": "shopping-agent"}
    r = client.post(f"{P}/payment-permissions/{a}/requests", headers=hdr,
                    json={"amount": 12000, "merchant_alias": "Merchant Y"}).json()
    assert r["data"]["decision"]["final"] == "HOLD"
    assert "R21" in [h["rule"] for h in r["data"]["decision"]["rule_hits"]]

    # 6. agent asks for 45.00 with its own confidence 0.97 -> ALLOW -> capture
    r = client.post(f"{P}/payment-permissions/{a}/requests", headers=hdr, json={
        "amount": 4500, "merchant_alias": "Merchant Y",
        "assessment": {"decision": "approve", "confidence": 0.97}}).json()
    assert r["data"]["decision"]["final"] == "ALLOW", r["data"]["decision"]["rule_hits"]
    assert r["data"]["request"]["state"] == "captured"

    # the same agent cannot start anything recurring on it
    r = client.post(f"{P}/payment-permissions/{a}/requests", headers=hdr, json={
        "amount": 999, "merchant_alias": "Merchant Y", "is_recurring": True,
        "assessment": {"decision": "approve", "confidence": 0.99}}).json()
    assert r["data"]["decision"]["final"] == "BLOCK"

    # 7. revoke a paypal_sub permission -> ● cancel, then BLOCK (R01)
    f = lp.repo.save(Permission(source="paypal_sub", external_ref="I-SANDBOX123", merchant_alias="Merchant F",
                                kind="fixed_recurring"))
    r = client.post(f"{P}/payment-permissions/{f.id}/revoke").json()
    assert r["data"]["paypal_action"] == "cancelled" and pp.cancelled == ["I-SANDBOX123"]
    r = client.post(f"{P}/payment-permissions/{f.id}/requests", json={"amount": 1299, "is_recurring": True}).json()
    assert r["data"]["decision"]["final"] == "BLOCK" and r["paypal"] is None

    # idempotency: every PayPal write carried a request id
    assert all(pp.seen_request_ids)
    # Trace has all four markers
    marks = {e["marker"] for e in client.get(f"{P}/events").json()["data"]}
    assert marks == {"●", "◇", "◆", "■"}


def test_revoke_csv_permission_is_honest(world):
    client, lp, pp, _ = world
    n = pid_of(lp, "Merchant N")
    r = client.post(f"{P}/payment-permissions/{n}/revoke").json()
    assert r["data"]["paypal_action"] == "not_available_to_buyer"
    assert "settings_link" in r["data"] and r["paypal"] is None and pp.cancelled == []


def test_human_reject_voids(world):
    client, lp, pp, _ = world
    c = pid_of(lp, "Merchant C")
    r = client.post(f"{P}/payment-permissions/{c}/requests", json={"amount": 8990}).json()
    rid = r["data"]["request"]["id"]
    r = client.post(f"{P}/requests/{rid}/resolve", json={"action": "reject"}).json()
    assert r["data"]["request"]["state"] == "voided" and r["data"]["decision"]["paypal_action"] == "voided"


def test_paypal_down_holds_never_allows(world):
    client, lp, pp, _ = world
    pp.fail_orders = True
    c = pid_of(lp, "Merchant C")
    r = client.post(f"{P}/payment-permissions/{c}/requests", json={"amount": 1890, "is_recurring": True}).json()
    assert r["data"]["decision"]["final"] == "HOLD"
    assert r["data"]["request"]["state"] == "held"
    assert "PayPal could not be reached. Nothing was charged." in r["data"]["decision"]["sentences"]


def test_ai_down_outside_hard_limits_holds(world):
    client, lp, pp, backend = world
    backend.answers.clear()  # every call now fails
    c = pid_of(lp, "Merchant C")
    client.put(f"{P}/payment-permissions/{c}/policy", json={"max_amount": 2500, "recurring": "require_approval"})
    r = client.post(f"{P}/payment-permissions/{c}/requests", json={"amount": 1890}).json()
    assert r["data"]["decision"]["final"] == "HOLD"
    assert [h["rule"] for h in r["data"]["decision"]["rule_hits"]] == ["R32"]


def test_expiry_voids_old_holds(world):
    client, lp, pp, _ = world
    c = pid_of(lp, "Merchant C")
    r = client.post(f"{P}/payment-permissions/{c}/requests", json={"amount": 8990}).json()
    lp.clock = lambda: NOW + timedelta(hours=73)
    assert lp.expire_holds() == [r["data"]["request"]["id"]]
    assert lp.repo.get(PaymentRequest, r["data"]["request"]["id"]).state == "expired"


def test_error_shape(world):
    client, *_ = world
    r = client.get(f"{P}/payment-permissions/pp_nope")
    assert r.status_code == 404 and r.json() == {"error": {"code": "permission_not_found", "message": "No permission pp_nope"}}
    r = client.put(f"{P}/policies/default", json={"max_amount": -1})
    assert r.json()["error"]["code"] == "policy_invalid"


def test_intent_draft_not_stored(world):
    client, lp, _, backend = world
    backend.answers["intent_to_policy"] = ('{"max_amount": 20, "recurring": "allow", '
                                           '"reason_codes": ["INTENT_THRESHOLD"]}')
    before = lp.ensure_default_policy().id
    r = client.post(f"{P}/intent", json={"text": "Anything recurring over 20 euros needs me."}).json()
    assert r["data"]["draft"]["max_amount"] == 2000 and r["data"]["stored"] is False
    assert r["data"]["sentences"] == ["Payments over 20.00 EUR wait for you."]
    assert lp.ensure_default_policy().id == before


def test_openapi_lists_proposed_paths(world):
    client, *_ = world
    paths = client.get("/openapi.json").json()["paths"]
    assert f"{P}/payment-permissions/{{pid}}/requests" in paths


def test_agent_cannot_revoke_or_decide_for_others(world):
    client, lp, pp, _ = world
    c = pid_of(lp, "Merchant C")
    hdr = {"X-Lupa-Agent": "shopping-agent"}
    r = client.post(f"{P}/payment-permissions/{c}/revoke", headers=hdr)
    assert r.status_code == 403 and r.json()["error"]["code"] == "agent_not_authorized"
    assert lp.permission(c).status == "active"
    held = client.post(f"{P}/payment-permissions/{c}/requests", json={"amount": 8990}).json()["data"]["request"]
    r = client.post(f"{P}/requests/{held['id']}/decision", headers=hdr, json={"decision": "approve", "confidence": 1})
    assert r.status_code == 403


def test_sync_respects_the_seed_floor(world):
    client, lp, pp, _ = world
    lp.repo.set_meta("sync_since", (NOW - timedelta(days=2)).isoformat())
    starts = []

    def row(tid, at):
        return {"transaction_info": {"transaction_id": tid, "transaction_event_code": "T0006",
                                     "transaction_initiation_date": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                     "transaction_amount": {"value": "-9.99", "currency_code": "EUR"},
                                     "transaction_status": "S"},
                "payer_info": {}, "cart_info": {}}

    def search(request):
        starts.append(request.url.params["start_date"])
        if len(starts) > 1:
            return httpx.Response(200, json={"transaction_details": [], "total_pages": 1})
        return httpx.Response(200, json={"transaction_details": [
            row("OLDROUND", NOW - timedelta(days=3)), row("THISROUND", NOW - timedelta(hours=1))],
            "total_pages": 1})

    pp.router.get(f"{BASE}/v1/reporting/transactions").mock(side_effect=search)
    r = client.post("/paypal/sync").json()
    assert r["marker"] == "●" and r["transaction_search"] == "ok"
    # The search window is not narrowed (PayPal 404s on a start date newer than its data) ...
    assert min(starts) < (NOW - timedelta(days=80)).strftime("%Y-%m-%dT%H:%M:%S")
    # ... the floor is applied to the rows instead.
    assert r["transactions"] == 1
