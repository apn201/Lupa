"""Subscriptions v1 and the catalog product a plan needs (reference section 5)."""

from __future__ import annotations

from ..money import fmt
from .client import PayPalClient


def create_product(client: PayPalClient, name: str, key: str, type_: str = "SERVICE") -> dict:
    return client.request("POST", "/v1/catalogs/products", json={"name": name, "type": type_},
                          idempotency_key=key)


def create_plan(client: PayPalClient, product_id: str, name: str, amount: int, currency: str,
                interval_unit: str, key: str, interval_count: int = 1) -> dict:
    body = {
        "product_id": product_id,
        "name": name,
        "status": "ACTIVE",
        "billing_cycles": [{
            "frequency": {"interval_unit": interval_unit, "interval_count": interval_count},
            "tenure_type": "REGULAR",
            "sequence": 1,
            "total_cycles": 0,
            "pricing_scheme": {"fixed_price": {"currency_code": currency, "value": fmt(amount)}},
        }],
        "payment_preferences": {"auto_bill_outstanding": True, "setup_fee_failure_action": "CONTINUE",
                                "payment_failure_threshold": 1},
    }
    return client.request("POST", "/v1/billing/plans", json=body, idempotency_key=key)


def create_subscription(client: PayPalClient, plan_id: str, custom_id: str, key: str,
                        return_url: str = "https://example.com/return",
                        cancel_url: str = "https://example.com/cancel") -> dict:
    body = {
        "plan_id": plan_id,
        "custom_id": custom_id,
        "application_context": {"return_url": return_url, "cancel_url": cancel_url,
                                "user_action": "SUBSCRIBE_NOW"},
    }
    return client.request("POST", "/v1/billing/subscriptions", json=body, idempotency_key=key)


def approve_link(sub: dict) -> str | None:
    for link in sub.get("links", []):
        if link.get("rel") == "approve":
            return link.get("href")
    return None


def get(client: PayPalClient, sub_id: str) -> dict:
    return client.request("GET", f"/v1/billing/subscriptions/{sub_id}")


def list_transactions(client: PayPalClient, sub_id: str, start_time: str, end_time: str) -> list[dict]:
    body = client.request("GET", f"/v1/billing/subscriptions/{sub_id}/transactions",
                          params={"start_time": start_time, "end_time": end_time})
    return body.get("transactions", [])


def cancel(client: PayPalClient, sub_id: str, reason: str, key: str) -> dict:
    return client.request("POST", f"/v1/billing/subscriptions/{sub_id}/cancel",
                          json={"reason": reason}, idempotency_key=key)


def suspend(client: PayPalClient, sub_id: str, reason: str, key: str) -> dict:
    return client.request("POST", f"/v1/billing/subscriptions/{sub_id}/suspend",
                          json={"reason": reason}, idempotency_key=key)


def update_pricing(client: PayPalClient, plan_id: str, amount: int, currency: str, key: str) -> dict:
    body = {"pricing_schemes": [{
        "billing_cycle_sequence": 1,
        "pricing_scheme": {"fixed_price": {"currency_code": currency, "value": fmt(amount)}},
    }]}
    return client.request("POST", f"/v1/billing/plans/{plan_id}/update-pricing-schemes",
                          json=body, idempotency_key=key)
