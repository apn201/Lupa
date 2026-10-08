"""The one shape every source is normalised into before reconstruction.

Amounts are from the consumer's side: positive = money left the consumer,
negative = money came back (refund). Funding and conversion rows are kept
here and dropped by `is_charge`, so the importer never decides what counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Txn:
    txn_id: str
    at: datetime
    counterparty: str          # merchant alias or account id
    amount: int                # minor units, consumer side
    currency: str
    type: str                  # CSV type text or T-code
    status: str = "S"          # S P D V
    ref_id: str | None = None  # I-..., B-..., order id
    ref_type: str | None = None  # SUB PAP ODR TXN
    balance_impact: str = "debit"  # debit | credit | memo
    source: str = "import_csv"     # import_csv | paypal_search | paypal_sub_txn
    category: str | None = None


IGNORED_TYPES = {
    "general card deposit",
    "general currency conversion",
    "general authorization",
    "void of authorization",
    "bank deposit to pp account",
    "general credit card deposit",
}
REFUND_TYPES = {"payment refund", "refund"}


def ref_type_of(ref_id: str | None, declared: str | None = None) -> str | None:
    if declared:
        return declared
    if not ref_id:
        return None
    if ref_id.startswith("I-"):
        return "SUB"
    if ref_id.startswith("B-"):
        return "PAP"
    return "TXN"


def is_refund(t: Txn) -> bool:
    return t.type == "T1107" or t.type.lower() in REFUND_TYPES


def is_charge(t: Txn) -> bool:
    """Rows to ignore, build spec 4: funding, conversions, authorizations, fees, credits."""
    if is_refund(t):
        return True
    if t.status in ("D", "V"):
        return False
    code = t.type.upper()
    if code.startswith(("T07", "T03", "T01")) or code == "T2000":
        return False
    if len(code) == 5 and code[0] == "T" and code[1:].isdigit() and not code.startswith("T00"):
        # Transaction Search rows: only T00xx are payments (adjustments, holds, fees are not).
        return False
    if t.type.lower() in IGNORED_TYPES:
        return False
    if t.balance_impact != "debit":
        return False
    return t.amount > 0
