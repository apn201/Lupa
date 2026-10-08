"""Transaction Search with 31-day windows and paging (reference section 2).

The business account's view: an incoming payment to the merchant is money
that left the consumer, so amounts map to positive consumer-side payments.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator

from ..importers.txn import Txn
from ..money import parse_amount
from .client import PayPalClient

WINDOW = timedelta(days=31)


def _ts(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def windows(start: datetime, end: datetime) -> Iterator[tuple[datetime, datetime]]:
    cur = start
    while cur < end:
        nxt = min(cur + WINDOW, end)
        yield cur, nxt
        cur = nxt


def search(client: PayPalClient, start: datetime, end: datetime,
           fields: str = "transaction_info,payer_info,cart_info") -> Iterator[dict]:
    for a, b in windows(start, end):
        page = 1
        while True:
            body = client.request("GET", "/v1/reporting/transactions", params={
                "start_date": _ts(a), "end_date": _ts(b), "fields": fields,
                "page_size": 100, "page": page,
            })
            yield from body.get("transaction_details", [])
            if page >= int(body.get("total_pages") or 1):
                break
            page += 1


def to_txn(detail: dict) -> Txn | None:
    info = detail.get("transaction_info") or {}
    amount = info.get("transaction_amount") or {}
    if not info.get("transaction_id") or "value" not in amount:
        return None
    raw = info.get("transaction_initiation_date", "").replace("Z", "+00:00")
    try:
        at = datetime.fromisoformat(raw)
    except ValueError:  # Python 3.11+ also reads the "+0000" offset form
        return None
    merchant_cents = parse_amount(amount["value"])
    code = info.get("transaction_event_code", "")
    # Merchant view: +value received = consumer paid. Refunds are negative for the
    # merchant and stay negative on the consumer side.
    consumer_amount = merchant_cents
    alias = (info.get("custom_field") or "").strip() or info.get("paypal_account_id") or "unknown"
    ref_type = info.get("paypal_reference_id_type")
    return Txn(
        txn_id=info["transaction_id"],
        at=at.astimezone(timezone.utc),
        counterparty=alias,
        amount=consumer_amount,
        currency=amount.get("currency_code", "EUR"),
        type=code,
        status=info.get("transaction_status", "S"),
        ref_id=info.get("paypal_reference_id"),
        ref_type=ref_type,
        balance_impact="debit" if consumer_amount > 0 or code == "T1107" else "credit",
        source="paypal_search",
    )
