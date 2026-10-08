"""Copy-paste of PayPal's Automatic payments page -> private/settings_list.yml.

    python scripts/parse_autopay.py private/autopay_raw.txt private/settings_list.yml

The paste is one block per agreement, blocks separated by a line with `---`, each
starting with the agreement's .../autopay/connect/B-.../cancel URL. Finnish UI
labels (Tila, Aloituspäivämäärä, Viimeinen maksu, Aiemmat maksut) and English
ones (Status, Start date, Last payment, Previous payments) are both read.
Output stays in private/; scripts/anonymize_export.py turns it into aliases.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import yaml

LABELS = {"tila", "status", "peruuta", "cancel", "maksutapa", "payment method", "saldo", "balance"}
ACTIVE = {"aktiivinen", "active"}
DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
HISTORY = re.compile(r"^(\d{1,2}) (\d{1,2})\n(\d{4})$", re.M)  # "9 24\n2026" = month day, year
REF = re.compile(r"\bB-[0-9A-Z]{10,}\b")


def _d(m) -> date:
    return date(int(m[2]), int(m[1]), int(m[0])) if isinstance(m, tuple) else m


def parse_block(block: str) -> dict | None:
    ref = REF.search(block)
    if not ref:
        return None
    lines = [l.strip() for l in block.splitlines() if l.strip()]
    name = ""
    if len(lines) > 1 and lines[1].lower() not in LABELS:
        name = lines[1].rstrip(",").strip()
    history = [date(int(y), int(m), int(d)) for m, d, y in HISTORY.findall(block)]
    if not name:
        # The header line is sometimes missing from the paste; the payment list repeats the name.
        for i, l in enumerate(lines):
            if HISTORY.match(f"{l}\n{lines[i + 1]}" if i + 1 < len(lines) else ""):
                if i + 2 < len(lines):
                    name = lines[i + 2].rstrip(",").strip()
                    break
    status = ""
    for i, l in enumerate(lines):
        if l.lower() in ("tila", "status") and i + 1 < len(lines):
            status = lines[i + 1].lower()
            break
    last = None
    m = re.search(r"(?:Viimeinen maksu|Last payment)\s+(\d{1,2}\.\d{1,2}\.\d{4})", block)
    if m:
        d, mo, y = DATE.search(m.group(1)).groups()
        last = date(int(y), int(mo), int(d))
    if history:
        last = max([last, *history]) if last else max(history)
    start = None
    m = re.search(r"(?:Aloituspäivämäärä|Start date)\s*\n\s*(\d{1,2}\.\d{1,2}\.\d{4})", block)
    if m:
        d, mo, y = DATE.search(m.group(1)).groups()
        start = date(int(y), int(mo), int(d))
    return {
        "name": name or ref.group(0),
        "agreement": "active" if status in ACTIVE else (status or "unknown"),
        "agreement_ref": ref.group(0),
        "start_date": start.isoformat() if start else None,
        "last_known_payment": last.isoformat() if last else None,
        "payments_listed": len(history),
    }


def main(src: str, dst: str) -> int:
    text = Path(src).read_text(encoding="utf-8")
    out: dict[str, dict] = {}
    for block in text.split("\n---"):
        entry = parse_block(block)
        if entry:
            name = entry.pop("name")
            out[name] = {k: v for k, v in entry.items() if v is not None}
    Path(dst).write_text("# PRIVATE. Parsed from PayPal's Automatic payments page. Never committed.\n"
                         + yaml.safe_dump(out, sort_keys=True, allow_unicode=True), encoding="utf-8")
    print(f"{len(out)} agreements -> {dst}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
