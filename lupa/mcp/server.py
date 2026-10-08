"""MCP server: what an AI agent sees of Lupa (build spec 12).

Every tool calls the local proposed API over HTTP with the agent's id in
`X-Lupa-Agent`. The agent never sees PayPal credentials and never talks to
PayPal; the policy engine decides every payment it asks for.

    python -m lupa.mcp.server          # stdio, for Claude Desktop

Env: LUPA_API_URL (default http://127.0.0.1:8000), LUPA_AGENT_ID (default shopping-agent).
"""

from __future__ import annotations

import os
from typing import Literal

import httpx
from mcp.server.mcpserver import MCPServer

from ..money import fmt, parse_amount

API = os.environ.get("LUPA_API_URL", "http://127.0.0.1:8000").rstrip("/") + "/proposed/v1/me"
AGENT = os.environ.get("LUPA_AGENT_ID", "shopping-agent")

mcp = MCPServer(
    name="lupa",
    instructions=(
        "Lupa holds the payment permissions a person has given. You can look at them and ask to pay "
        "through one. You cannot approve your own payment: Lupa's policy engine decides, and a held "
        "payment waits for the person. Amounts are decimal strings in the permission's currency."
    ),
)


def _client() -> httpx.Client:
    return httpx.Client(base_url=API, headers={"X-Lupa-Agent": AGENT}, timeout=60)


def _call(method: str, path: str, **kw) -> dict:
    with _client() as c:
        r = c.request(method, path, **kw)
    body = r.json()
    if r.status_code >= 400:
        err = body.get("error") or body.get("detail") or body
        return {"error": err}
    return body


def _perm(p: dict) -> dict:
    prof = p.get("profile") or {}
    return {
        "id": p["id"], "merchant": p["merchant_alias"], "category": p["merchant_category"], "kind": p["kind"],
        "status": p["status"], "currency": p["currency"],
        "last_amount": fmt(p.get("last_amount")) if p.get("last_amount") is not None else None,
        "last_payment": (p.get("last_payment_at") or "")[:10] or None,
        "usual_range": [fmt(prof["amount_min"]), fmt(prof["amount_max"])] if prof.get("amount_min") is not None else None,
        "attention": [a["text"] for a in p.get("attention_sentences", [])],
    }


def _decision(body: dict) -> dict:
    if "error" in body:
        return body
    data = body["data"]
    req, dec = data["request"], data["decision"] or {}
    out = {
        "request_id": req["id"], "verdict": dec.get("final"), "state": req["state"],
        "amount": fmt(req["amount"]), "currency": req["currency"], "merchant": req["merchant_alias"],
        "why": dec.get("sentences", []),
        "marker": "◇ proposed API; ■ decided by Lupa's policy engine",
    }
    if body.get("paypal"):
        out["paypal"] = [f"● {c['method']} {c['path']} -> {c['status']} {c.get('paypal_id') or ''}".strip()
                         for c in body["paypal"]["calls"]]
    if out["state"] == "held":
        out["next"] = "The person must approve this in Lupa. Do not retry or split the payment."
    return out


@mcp.tool()
def list_payment_permissions(status: Literal["active", "revoked", "suspended", "any"] = "active") -> dict:
    """List the payment permissions this person has, with usual amounts and anything needing attention."""
    params = {} if status == "any" else {"status": status}
    body = _call("GET", "/payment-permissions", params=params)
    if "error" in body:
        return body
    return {"summary": body["data"]["headline"]["text"], "permissions": [_perm(p) for p in body["data"]["permissions"]]}


@mcp.tool()
def inspect_payment_permission(permission_id: str) -> dict:
    """One permission in detail: profile, policy, your delegation on it, and recent requests."""
    body = _call("GET", f"/payment-permissions/{permission_id}")
    if "error" in body:
        return body
    d = body["data"]
    pol = d.get("policy") or {}
    mine = [x for x in d.get("delegations", []) if x["agent_id"] == AGENT and not x.get("revoked_at")]
    return {
        **_perm(d),
        "policy": {"limit": fmt(pol.get("max_amount")), "recurring": pol.get("recurring"),
                   "new_merchant": pol.get("new_merchant")} if pol else None,
        "your_delegation": [{"authority": x["authority"], "max_amount": fmt(x["max_amount"]),
                             "recurring_allowed": x["recurring_allowed"], "expires": x["expires_at"][:10]}
                            for x in mine],
        "recent_requests": [{"id": r["id"], "amount": fmt(r["amount"]), "state": r["state"]}
                            for r in d.get("requests", [])[:5]],
    }


@mcp.tool()
def request_payment(permission_id: str, amount: str, purpose: str, currency: str = "EUR",
                    merchant: str | None = None, is_recurring: bool = False,
                    your_confidence: float | None = None) -> dict:
    """Ask to pay through a permission. Lupa decides: ALLOW pays, HOLD waits for the person, BLOCK refuses.

    amount: decimal string such as "45.00". your_confidence: how sure you are this purchase is what
    the person wants (0-1); it can only make Lupa more careful, never less.
    """
    body = {"amount": parse_amount(amount), "currency": currency.upper(), "purpose": purpose[:200],
            "is_recurring": is_recurring, "source": "agent"}
    if merchant:
        body["merchant_alias"] = merchant
    if your_confidence is not None:
        body["assessment"] = {"decision": "approve", "confidence": max(0.0, min(1.0, your_confidence))}
    return _decision(_call("POST", f"/payment-permissions/{permission_id}/requests", json=body))


@mcp.tool()
def submit_decision(request_id: str, decision: Literal["approve", "escalate", "reject"], confidence: float,
                    reason: str = "") -> dict:
    """Give your own verdict on a held request. Lupa re-evaluates; your verdict can never lift a hold the policy set."""
    return _decision(_call("POST", f"/requests/{request_id}/decision",
                           json={"decision": decision, "confidence": confidence, "reason": reason[:300]}))


@mcp.tool()
def revoke_payment_permission(permission_id: str) -> dict:
    """Revoke a permission (for example one the person no longer uses). Revoking only ever removes authority."""
    body = _call("POST", f"/payment-permissions/{permission_id}/revoke")
    if "error" in body:
        return body
    d = body["data"]
    return {"status": d["permission"]["status"], "paypal_action": d["paypal_action"], "note": d.get("note")}


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
