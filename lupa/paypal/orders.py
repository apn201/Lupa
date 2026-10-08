"""Orders v2 and Payments v2: create AUTHORIZE order, authorize, capture, void.

Field names from docs/paypal-api-reference.md sections 3 and 4.
"""

from __future__ import annotations

from ..money import fmt
from .client import PayPalClient


def _money(cents: int, currency: str) -> dict:
    return {"currency_code": currency, "value": fmt(cents)}


def card_source(client: PayPalClient) -> dict:
    s = client.settings
    return {"card": {
        "number": s.card_number,
        "expiry": s.card_expiry,
        "name": s.card_name,
        # Ask for 3-D Secure only when the issuer requires it, so a sandbox
        # test card can be authorized without a browser step.
        "attributes": {"verification": {"method": "SCA_WHEN_REQUIRED"}},
        "billing_address": {"address_line_1": "1 Test St", "admin_area_2": "Helsinki",
                            "postal_code": "00100", "country_code": "FI"},
    }}


def create_authorize_order(client: PayPalClient, request_id: str, amount: int, currency: str,
                           description: str, intent: str = "AUTHORIZE", merchant_alias: str | None = None) -> dict:
    """custom_id carries the merchant alias (sync reads it back); invoice_id the Lupa request id."""
    body = {
        "intent": intent,
        "purchase_units": [{
            "reference_id": request_id,
            "custom_id": merchant_alias or request_id,
            "invoice_id": request_id,
            "description": description[:127],
            "amount": _money(amount, currency),
        }],
        "payment_source": card_source(client),
    }
    return client.request("POST", "/v2/checkout/orders", json=body, idempotency_key=f"{request_id}-order")


def authorize(client: PayPalClient, order_id: str, request_id: str) -> dict:
    return client.request("POST", f"/v2/checkout/orders/{order_id}/authorize", json={},
                          idempotency_key=f"{request_id}-authorize")


def authorization_of(order: dict) -> dict | None:
    """The first authorization inside an order response, if any."""
    for pu in order.get("purchase_units", []):
        auths = (pu.get("payments") or {}).get("authorizations") or []
        if auths:
            return auths[0]
    return None


def get_authorization(client: PayPalClient, authorization_id: str) -> dict:
    return client.request("GET", f"/v2/payments/authorizations/{authorization_id}")


def capture(client: PayPalClient, authorization_id: str, amount: int, currency: str,
            key: str, final: bool = True) -> dict:
    body = {"amount": _money(amount, currency), "final_capture": final}
    return client.request("POST", f"/v2/payments/authorizations/{authorization_id}/capture",
                          json=body, idempotency_key=f"{key}-capture")


def void(client: PayPalClient, authorization_id: str, key: str) -> dict:
    # 200 with the authorization or 204 with no body are both documented.
    return client.request("POST", f"/v2/payments/authorizations/{authorization_id}/void",
                          idempotency_key=f"{key}-void")


def capture_order(client: PayPalClient, order_id: str, key: str) -> dict:
    return client.request("POST", f"/v2/checkout/orders/{order_id}/capture", json={},
                          idempotency_key=f"{key}-capture")
