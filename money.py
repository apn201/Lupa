"""Money as integer minor units. Floats never touch an amount."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

UNICODE_MINUS = "−"


def parse_amount(text: str | int | float | Decimal) -> int:
    """'18.90' -> 1890, '−3,14' -> -314, '1 234,50' -> 123450, 12 -> 1200.

    Handles the Finnish export: decimal comma, the Unicode minus sign and
    spaces or dots as thousands separators.
    """
    if isinstance(text, int) and not isinstance(text, bool):
        return text * 100
    if isinstance(text, (float, Decimal)):
        return int((Decimal(str(text)) * 100).quantize(Decimal(1), ROUND_HALF_UP))
    s = str(text).strip().replace(UNICODE_MINUS, "-").replace(" ", "").replace(" ", "")
    if not s:
        raise ValueError("empty amount")
    if "," in s and "." in s:
        # whichever comes last is the decimal separator
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        value = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"not an amount: {text!r}") from exc
    return int((value * 100).quantize(Decimal(1), ROUND_HALF_UP))


def fmt(cents: int | None) -> str:
    """1890 -> '18.90'. The one way an amount is ever printed."""
    if cents is None:
        return "-"
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def ceil5(cents: float) -> int:
    """Round up to the next whole 5 units of currency (500 cents)."""
    step = 500
    whole = int(cents)
    if whole < cents:
        whole += 1
    return -(-whole // step) * step
