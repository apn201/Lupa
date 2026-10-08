"""Fixed English sentences per rule and reason code (build spec 6).

The UI shows these and only these. Number slots are filled from the ledger by
code; the model's own prose is never shown.
"""

from __future__ import annotations

from ..ledger.models import Permission, Policy, Profile
from ..money import fmt

RULE_SENTENCES = {
    "R01": "This permission is {status}. Nothing can be paid through it.",
    "R02": "The policy for this permission has expired.",
    "R03": "Paid in {request_currency}, but the policy is set in {policy_currency}.",
    "R04": "Your policy does not allow this kind of payment.",
    "R10": "Above your limit of {max_amount} {currency}.",
    "R11": "Recurring payments need your approval.",
    "R12": "{amount} is more than {tolerance_pct}% above the usual {median}.",
    "R13": "{amount} is more than {tolerance_pct}% above the usual {median}, and your policy blocks increases.",
    "R14": "{merchant} is not the merchant this permission was given to.",
    "R15": "This would bring the month to {projected} {currency}, over your cap of {max_per_month}.",
    "R16": "This permission has been silent for a long time. A new charge needs you.",
    "R20": "The agent can propose this payment. You decide.",
    "R21": "This is outside what you delegated to the agent.",
    "R30": "The assessment advises against this payment. It waits for you.",
    "R31": "The assessment is not confident enough to pay without you.",
    "R32": "The assessment is unavailable, so this waits for you.",
    "PAYPAL_UNAVAILABLE": "PayPal could not be reached. Nothing was charged.",
}

REASON_SENTENCES = {
    "AI_UNAVAILABLE_WITHIN_HARD_LIMITS": "The assessment is unavailable, but this is within your hard limits.",
    "AMOUNT_IN_RANGE": "{amount} is within the usual range of {min} to {max}.",
    "AMOUNT_ABOVE_RANGE": "{amount} is above the usual range of {min} to {max}.",
    "AMOUNT_RATIO": "{amount} is {ratio}x the usual {median}.",
    "MERCHANT_MATCH": "Same merchant as before.",
    "MERCHANT_UNKNOWN": "A merchant this permission has not paid before.",
    "INTERVAL_MATCH": "On the usual schedule.",
    "INTERVAL_EARLY": "Earlier than the usual schedule.",
    "FIRST_CHARGE": "The first charge on this permission.",
    "DORMANT_REACTIVATED": "A charge after a long silence.",
}

ATTENTION_SENTENCES = {
    "DORMANT_6M": "No payment in {months} months, still active.",
    "DORMANT_12M": "No payment in over a year, still active.",
    "AMOUNT_JUMP": "{amount} is {ratio}x the usual {median}.",
    "INTERVAL_BREAK": "Charged again after a long gap.",
    "ONE_OFF_STILL_ACTIVE": "Looks like a one-off purchase, but the permission is still active.",
    "NO_HISTORY": "Active, with no payment in the data.",
    "NEW_LAST_30D": "New in the last 30 days.",
}

INTENT_SENTENCES = {
    "INTENT_THRESHOLD": "Payments over {max_amount} {currency} wait for you.",
    "INTENT_RECURRING_APPROVAL": "Recurring payments need your approval.",
    "INTENT_RECURRING_BLOCK": "Recurring payments are blocked.",
    "INTENT_INCREASE_APPROVAL": "A payment more than {tolerance}% above the usual amount waits for you.",
    "INTENT_NO_NEW_MERCHANTS": "Payments to new merchants are not allowed without you.",
    "INTENT_AMBIGUOUS": "The sentence was unclear, so the strictest reading was used.",
}

LIMIT_SENTENCE = (
    "Your recent payments range from {min} to {max}. {limit} leaves room for normal "
    "variation and sends larger ones to you."
)


class _Safe(dict):
    def __missing__(self, key):
        return "?"


def _money_values(values: dict, currency: str) -> dict:
    out = _Safe(currency=currency)
    for k, v in values.items():
        if k in ("amount", "max_amount", "median", "month_total", "max_per_month", "delegation_max", "min", "max", "limit", "projected"):
            out[k] = fmt(v) if isinstance(v, int) else v
        else:
            out[k] = v
    return out


def for_rule(rule: str, values: dict, currency: str = "EUR") -> str:
    v = dict(values)
    if rule == "R15":
        v["projected"] = v.get("month_total", 0) + v.get("amount", 0)
    return RULE_SENTENCES[rule].format_map(_money_values(v, currency))


def for_reason(code: str, values: dict, currency: str = "EUR") -> str | None:
    template = REASON_SENTENCES.get(code)
    return template.format_map(_money_values(values, currency)) if template else None


def ratio(amount: int, median: int | None) -> str:
    if not median:
        return "?"
    return f"{amount / median:.1f}"


def for_attention(code: str, perm: Permission, prof: Profile | None) -> str:
    v: dict = {}
    if prof is not None:
        v["months"] = int(prof.months_since_last or 0)
        v["median"] = prof.amount_median
        if perm.last_amount is not None:
            v["amount"] = perm.last_amount
            v["ratio"] = ratio(perm.last_amount, prof.amount_median)
    return ATTENTION_SENTENCES[code].format_map(_money_values(v, perm.currency))


def for_intent(code: str, pol: Policy) -> str | None:
    template = INTENT_SENTENCES.get(code)
    if not template:
        return None
    return template.format_map(_money_values(
        {"max_amount": pol.max_amount, "tolerance": pol.increase_tolerance_pct}, pol.currency))


def for_limit(prof: Profile, limit: int, currency: str = "EUR") -> str:
    return LIMIT_SENTENCE.format_map(_money_values(
        {"min": prof.amount_min, "max": prof.amount_max, "limit": limit}, currency))
