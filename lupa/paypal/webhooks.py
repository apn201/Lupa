"""Webhook verification and event routing (reference section 6).

Verify the exact verify-webhook-signature field names against the Webhooks
API page before relying on verification in a hosted demo.
"""

from __future__ import annotations

from .client import PayPalClient

HEADER_FIELDS = {
    "auth_algo": "paypal-auth-algo",
    "cert_url": "paypal-cert-url",
    "transmission_id": "paypal-transmission-id",
    "transmission_sig": "paypal-transmission-sig",
    "transmission_time": "paypal-transmission-time",
}


def verify(client: PayPalClient, webhook_id: str, headers: dict, event: dict) -> bool:
    lower = {k.lower(): v for k, v in headers.items()}
    body = {k: lower.get(h, "") for k, h in HEADER_FIELDS.items()}
    body["webhook_id"] = webhook_id
    body["webhook_event"] = event
    resp = client.request("POST", "/v1/notifications/verify-webhook-signature", json=body)
    return resp.get("verification_status") == "SUCCESS"


def referenced_resource(event: dict) -> tuple[str, str | None]:
    """(kind, id) of the resource an event is about: subscription, authorization, capture, sale."""
    etype = event.get("event_type", "")
    res = event.get("resource") or {}
    if etype.startswith("BILLING.SUBSCRIPTION"):
        return "subscription", res.get("id")
    if etype.startswith("PAYMENT.SALE"):
        return "subscription", res.get("billing_agreement_id")
    if etype.startswith("PAYMENT.AUTHORIZATION"):
        return "authorization", res.get("id")
    if etype.startswith("PAYMENT.CAPTURE"):
        return "capture", res.get("id")
    return "other", res.get("id")
