"""Write a synthetic six-month activity export and its merchants.yml.

Stand-in until `anonymize_export.py` produces data/sample_activity_anonymized.csv
from the real export. Deterministic (fixed seed), so tests can freeze counts.

    python scripts/make_synthetic_sample.py
"""

from __future__ import annotations

import hashlib
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lupa.money import fmt  # noqa: E402

HEADER = ["Date", "Time", "TimeZone", "Name", "Type", "Status", "Currency", "Gross", "Fee", "Net",
          "From Email Address", "To Email Address", "Transaction ID", "Reference Txn ID", "Balance",
          "Balance Impact", "Category"]
START = date(2026, 4, 1)
END = date(2026, 9, 30)
REFERENCE = "2026-10-01"
PAP = "PreApproved Payment Bill User Payment"
EXPRESS = "Express Checkout Payment"

rnd = random.Random(20261008)


def tid(*parts) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:17].upper()


def bref(alias: str) -> str:
    return "B-" + hashlib.sha256(alias.encode()).hexdigest()[:15].upper()


def monthly(day: int, months=range(4, 10)) -> list[date]:
    return [date(2026, m, min(day, 28)) for m in months]


# alias: (category, type, dates, amounts-in-cents or callable, has B- reference)
PLAN: list[tuple[str, str, str, list[date], list[int], bool]] = []


def add(alias, category, dates, amounts, kind=PAP, ref=True):
    PLAN.append((alias, category, kind, dates, amounts, ref))


add("Merchant A", "digital service", monthly(3), [849] * 6)
add("Merchant B", "media", monthly(11), [314] * 6)
add("Merchant C", "software", monthly(1), [1890, 1750, 1990, 1890, 2130, 1850])
add("Merchant D", "cloud", monthly(2), [210, 455, 980, 312, 640, 525])
add("Merchant E", "utility", monthly(25), [6210, 5130, 4820, 4500, 4710, 5590])
add("Merchant F", "digital service", monthly(8), [1299, 1299, 1299, 1299, 1299, 2199])
weekly = [START + timedelta(days=4 + 7 * i) for i in range(26)]
add("Merchant G", "media", weekly, [299] * len(weekly))
add("Merchant H", "travel provider", [date(2026, 5, 14)], [8900])
add("Merchant I", "retailer", [date(2026, 4, 22), date(2026, 7, 2)], [3450, 2290], kind=EXPRESS, ref=False)
add("Merchant J", "marketplace", [date(2026, 6, 9)], [1599], kind=EXPRESS, ref=False)
add("Merchant K", "software", [date(2026, 6, 30)], [7500])
add("Merchant L", "digital service", [date(2026, 4, 20), date(2026, 5, 20), date(2026, 8, 20), date(2026, 9, 20)],
    [599] * 4)
add("Merchant M", "digital service", [date(2026, 9, 15)], [999])

# On the settings list, no charge in the window. last_known_payment from the list.
SILENT = {
    "Merchant N": ("digital service", "2023-11-02"),
    "Merchant O": ("media", "2024-02-17"),
    "Merchant P": ("software", "2024-08-30"),
    "Merchant Q": ("retailer", "2022-12-05"),
    "Merchant R": ("travel provider", "2025-01-11"),
    "Merchant S": ("marketplace", "2025-06-21"),
    "Merchant T": ("digital service", "2026-01-28"),
    "Merchant U": ("individual", "2025-03-03"),
    "Merchant V": ("cloud", None),
    "Merchant W": ("media", "2026-02-14"),
}
AGREEMENT = {"Merchant A", "Merchant B", "Merchant C", "Merchant D", "Merchant E", "Merchant F",
             "Merchant G", "Merchant H", "Merchant K", "Merchant L", "Merchant M"}


def rows() -> list[dict]:
    out = []
    for alias, category, kind, dates, amounts, ref in PLAN:
        for i, (d, cents) in enumerate(zip(dates, amounts)):
            t = f"{rnd.randint(6, 22):02d}:{rnd.randint(0, 59):02d}:{rnd.randint(0, 59):02d}"
            pay_id = tid(alias, d, i)
            base = {"Date": d.strftime("%d/%m/%Y"), "Time": t, "TimeZone": "Europe/Helsinki",
                    "Currency": "EUR", "Fee": "0.00", "From Email Address": "", "To Email Address": "",
                    "Balance": "0.00", "Category": category}
            out.append({**base, "Name": "", "Type": "General Card Deposit", "Status": "Completed",
                        "Gross": fmt(cents), "Net": fmt(cents), "Transaction ID": tid("fund", pay_id),
                        "Reference Txn ID": pay_id, "Balance Impact": "Credit", "Category": ""})
            out.append({**base, "Name": alias, "Type": kind, "Status": "Completed",
                        "Gross": fmt(-cents), "Net": fmt(-cents), "Transaction ID": pay_id,
                        "Reference Txn ID": bref(alias) if ref else "", "Balance Impact": "Debit"})
    # a refund for Merchant I and a currency conversion pair that must be ignored
    out.append({"Date": "09/07/2026", "Time": "10:00:00", "TimeZone": "Europe/Helsinki", "Name": "Merchant I",
                "Type": "Payment Refund", "Status": "Completed", "Currency": "EUR", "Gross": "22.90", "Fee": "0.00",
                "Net": "22.90", "From Email Address": "", "To Email Address": "", "Transaction ID": tid("refund"),
                "Reference Txn ID": tid("Merchant I", date(2026, 7, 2), 1), "Balance": "0.00",
                "Balance Impact": "Credit", "Category": "retailer"})
    for gross, cur, impact in (("-10.00", "EUR", "Debit"), ("11.62", "USD", "Credit")):
        out.append({"Date": "12/08/2026", "Time": "09:00:00", "TimeZone": "Europe/Helsinki", "Name": "",
                    "Type": "General Currency Conversion", "Status": "Completed", "Currency": cur,
                    "Gross": gross, "Fee": "0.00", "Net": gross, "From Email Address": "",
                    "To Email Address": "", "Transaction ID": tid("conv", cur), "Reference Txn ID": "",
                    "Balance": "0.00", "Balance Impact": impact, "Category": ""})
    out.sort(key=lambda r: (datetime.strptime(r["Date"], "%d/%m/%Y"), r["Time"], r["Type"]))
    return out


def merchants_yml() -> str:
    lines = ["# Synthetic sample. alias -> category and the settings-list agreement state.",
             f"reference_date: {REFERENCE}", "merchants:"]
    for alias, category, *_ in PLAN:
        lines.append(f"  {alias}:")
        lines.append(f"    category: {category}")
        if alias in AGREEMENT:
            lines.append("    agreement: active")
            lines.append(f"    agreement_ref: {bref(alias)}")
    for alias, (category, last) in SILENT.items():
        lines.append(f"  {alias}:")
        lines.append(f"    category: {category}")
        lines.append("    agreement: active")
        lines.append(f"    agreement_ref: {bref(alias)}")
        if last:
            lines.append(f"    last_known_payment: {last}")
    return "\n".join(lines) + "\n"


def main() -> None:
    import csv
    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    with open(data / "sample_activity_synthetic.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows())
    (data / "merchants_synthetic.yml").write_text(merchants_yml(), encoding="utf-8")
    print("wrote data/sample_activity_synthetic.csv and data/merchants_synthetic.yml")


if __name__ == "__main__":
    main()
