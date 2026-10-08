"""The rule table and reason codes (build spec 6). Data only."""

from __future__ import annotations

RULES: dict[str, tuple[str, str]] = {
    # id: (verdict, condition)
    "R01": ("BLOCK", "permission revoked, expired or suspended"),
    "R02": ("BLOCK", "policy expired"),
    "R03": ("BLOCK", "currency differs from the policy"),
    "R04": ("BLOCK", "recurring when the policy blocks recurring, or a new merchant when it blocks new merchants"),
    "R10": ("HOLD", "amount above the policy limit"),
    "R11": ("HOLD", "recurring and the policy asks for approval"),
    "R12": ("HOLD", "amount above the usual range and the policy asks for approval"),
    "R13": ("BLOCK", "amount above the usual range and the policy blocks increases"),
    "R14": ("HOLD", "merchant is not this permission's merchant"),
    "R15": ("HOLD", "monthly total would pass the monthly cap"),
    "R16": ("HOLD", "permission silent for a year or never used"),
    "R20": ("HOLD", "agent may only propose"),
    "R21": ("HOLD", "outside the agent's delegation"),
    "R30": ("HOLD", "AI recommends rejecting; only a human can block"),
    "R31": ("HOLD", "AI escalates or is not confident enough"),
    "R32": ("HOLD", "AI unavailable"),
    "PAYPAL_UNAVAILABLE": ("HOLD", "PayPal call failed"),
}

# Rules that read the AI verdict. They only ever add HOLD. Nothing reads the
# AI verdict to remove one.
AI_RULES = {"R30", "R31", "R32"}

AI_UNAVAILABLE_WITHIN_HARD_LIMITS = "AI_UNAVAILABLE_WITHIN_HARD_LIMITS"

STRICTNESS = {"ALLOW": 0, "HOLD": 1, "BLOCK": 2}


def stricter(a: str, b: str) -> str:
    return a if STRICTNESS[a] >= STRICTNESS[b] else b
