"""Real PayPal activity export in private/ -> anonymized sample for the repo (build spec 10).

    python scripts/anonymize_export.py private/Download.CSV data/sample_activity_anonymized.csv

Needs private/anon_key.txt (any long random string; created on first run) and
optionally private/merchant_categories.yml (real name -> category). Neither is
ever committed. Writes data/merchants.yml beside the sample, from
private/settings_list.yml if present (real name -> {agreement, last_known_payment}).

- Merchant names -> Merchant A..Z, AA.. in order of first appearance.
- Emails, names, addresses, subject, note, item titles: dropped.
- Transaction ids and B-/I- references: HMAC-SHA256, truncated to 17 chars with
  the original prefix, so grouping survives and the originals cannot be recovered.
- Dates shifted by one constant offset of 0-13 days (derived from the key).
- Amounts and currencies untouched. Header written in English.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import string
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lupa.importers.activity_csv import FI_TYPES, read_rows  # noqa: E402
from lupa.money import fmt, parse_amount  # noqa: E402

PRIVATE = ROOT / "private"
OUT_HEADER = ["Date", "Time", "TimeZone", "Name", "Type", "Status", "Currency", "Gross", "Fee", "Net",
              "From Email Address", "To Email Address", "Transaction ID", "Reference Txn ID", "Balance",
              "Balance Impact", "Category"]


def key() -> bytes:
    path = PRIVATE / "anon_key.txt"
    if not path.exists():
        PRIVATE.mkdir(exist_ok=True)
        path.write_text(secrets.token_hex(32))
    return path.read_text().strip().encode()


def alias_names():
    letters = string.ascii_uppercase
    for c in letters:
        yield f"Merchant {c}"
    for a in letters:
        for b in letters:
            yield f"Merchant {a}{b}"


def hash_id(k: bytes, value: str) -> str:
    if not value:
        return ""
    prefix = value[:2] if value[:2] in ("B-", "I-") else ""
    digest = hmac.new(k, value.encode(), hashlib.sha256).hexdigest().upper()
    return (prefix + digest)[:17]


def main(src: str, dst: str) -> int:
    k = key()
    shift = timedelta(days=int(hmac.new(k, b"date-shift", hashlib.sha256).hexdigest(), 16) % 14)
    cats_path = PRIVATE / "merchant_categories.yml"
    categories = yaml.safe_load(cats_path.read_text(encoding="utf-8")) if cats_path.exists() else {}
    raw = Path(src).read_bytes()
    text = next(raw.decode(e) for e in ("utf-8-sig", "utf-16", "cp1252") if _decodes(raw, e))
    aliases: dict[str, str] = {}
    gen = alias_names()
    out = []
    for row in read_rows(text):
        name = (row.get("Name") or "").strip()
        alias = ""
        if name:
            if name not in aliases:
                aliases[name] = next(gen)
            alias = aliases[name]
        d = None
        for f in ("%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%m/%d/%Y"):
            try:
                d = datetime.strptime(row["Date"].strip(), f)
                break
            except ValueError:
                continue
        if d is None:
            raise SystemExit(f"unknown date {row['Date']!r}")
        type_text = FI_TYPES.get(row.get("Type", "").strip().lower(), row.get("Type", "").strip())
        out.append({
            "Date": (d + shift).strftime("%d/%m/%Y"), "Time": row.get("Time", ""),
            "TimeZone": row.get("TimeZone", ""), "Name": alias, "Type": type_text,
            "Status": row.get("Status", ""), "Currency": row["Currency"],
            "Gross": fmt(parse_amount(row["Gross"])),
            "Fee": fmt(parse_amount(row["Fee"])) if row.get("Fee") else "0.00",
            "Net": fmt(parse_amount(row["Net"])) if row.get("Net") else "",
            "From Email Address": "", "To Email Address": "",
            "Transaction ID": hash_id(k, row["Transaction ID"].strip()),
            "Reference Txn ID": hash_id(k, (row.get("Reference Txn ID") or "").strip()),
            "Balance": "", "Balance Impact": row.get("Balance Impact", ""),
            "Category": categories.get(name, "digital service") if name else "",
        })
    import csv
    with open(dst, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_HEADER)
        w.writeheader()
        w.writerows(out)

    settings_path = PRIVATE / "settings_list.yml"
    settings_list = yaml.safe_load(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    # The settings page and the export can name the same merchant differently
    # ("Example (USA) Inc.," on one, "Example BV" in the other); the agreement id is the join key.
    name_by_ref: dict[str, str] = {}
    for row in read_rows(text):
        ref_id = (row.get("Reference Txn ID") or "").strip()
        if ref_id.startswith("B-") and (row.get("Name") or "").strip():
            name_by_ref.setdefault(ref_id, row["Name"].strip())
    merchants = {}
    matched = 0
    for name, info in (settings_list or {}).items():
        info = info or {}
        ref_id = info.get("agreement_ref")
        if ref_id in name_by_ref:
            name = name_by_ref[ref_id]
            matched += 1
        if name not in aliases:
            aliases[name] = next(gen)
        m = {"category": categories.get(name, "digital service"), "agreement": info.get("agreement", "active")}
        if ref_id:
            m["agreement_ref"] = hash_id(k, ref_id)
        if info.get("last_known_payment"):
            m["last_known_payment"] = str(datetime.fromisoformat(str(info["last_known_payment"])).date() + shift)
        merchants[aliases[name]] = m
    for name, alias in aliases.items():
        merchants.setdefault(alias, {"category": categories.get(name, "digital service")})
    print(f"settings list: {len(settings_list or {})} agreements, {matched} matched to the export by agreement id")
    ref = max(datetime.strptime(r["Date"], "%d/%m/%Y") for r in out) + timedelta(days=1)
    known = {"reference_date": ref.date().isoformat(), "merchants": dict(sorted(merchants.items()))}
    (Path(dst).parent / "merchants.yml").write_text(
        "# Anonymized. alias -> category and the settings-list agreement state.\n"
        + yaml.safe_dump(known, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"{len(out)} rows, {len(aliases)} merchants -> {dst}")
    return 0


def _decodes(raw: bytes, enc: str) -> bool:
    try:
        raw.decode(enc)
        return True
    except UnicodeDecodeError:
        return False


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
