"""PayPal Activity Download CSV (the consumer export), English and Finnish headers.

The export is the consumer's view: purchases are negative gross with balance
impact Debit, the card top-up that funds them is a separate Credit row.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator
from zoneinfo import ZoneInfo

from ..money import parse_amount
from .txn import Txn, ref_type_of

# Canonical English header -> known variants. Finnish names verified against the
# real export for the ones listed in the build spec; the rest are best guesses
# and fall back gracefully because only the canonical keys below are read.
HEADERS: dict[str, tuple[str, ...]] = {
    "Date": ("Date", "Päiväys", "Päivämäärä"),
    "Time": ("Time", "Kellonaika", "Aika"),
    "TimeZone": ("TimeZone", "Time Zone", "Aikavyöhyke"),
    "Name": ("Name", "Nimi"),
    "Type": ("Type", "Tyyppi", "Kuvaus"),
    "Status": ("Status", "Tila"),
    "Currency": ("Currency", "Valuutta"),
    "Gross": ("Gross", "Brutto"),
    "Fee": ("Fee", "Maksu", "Palkkio"),
    "Net": ("Net", "Netto"),
    "From Email Address": ("From Email Address", "Lähettäjän sähköpostiosoite"),
    "To Email Address": ("To Email Address", "Vastaanottajan sähköpostiosoite"),
    "Transaction ID": ("Transaction ID", "Tapahtuman tunniste"),
    "Reference Txn ID": ("Reference Txn ID", "Viitetapahtuman tunniste"),
    "Balance": ("Balance", "Saldo"),
    "Balance Impact": ("Balance Impact", "Vaikutus saldoon"),
    "Category": ("Category",),  # only in the anonymized sample
}

# Finnish "Kuvaus" values seen in exports mapped to the English type text.
FI_TYPES = {
    "esivaltuutetun maksun käyttäjän laskumaksu": "PreApproved Payment Bill User Payment",
    "express checkout -maksu": "Express Checkout Payment",
    "yleinen korttitalletus": "General Card Deposit",
    "yleinen valuutanmuunto": "General Currency Conversion",
    "tilausmaksu": "Subscription Payment",
    "maksun hyvitys": "Payment Refund",
}
IMPACT = {"debit": "debit", "veloitus": "debit", "credit": "credit", "hyvitys": "credit", "memo": "memo", "muistio": "memo"}
STATUS = {"completed": "S", "valmis": "S", "suoritettu": "S", "pending": "P", "odottaa": "P",
          "denied": "D", "hylätty": "D", "reversed": "V", "peruutettu": "V", "refunded": "S"}


def _canon(header: list[str]) -> dict[str, str]:
    """Map canonical key -> actual column name present in this file."""
    present = {h.strip().lstrip("﻿"): h for h in header}
    out = {}
    for key, variants in HEADERS.items():
        for v in variants:
            if v in present:
                out[key] = present[v]
                break
    missing = {"Date", "Type", "Gross", "Currency", "Transaction ID"} - out.keys()
    if missing:
        raise ValueError(f"not a PayPal activity export, missing columns: {sorted(missing)}")
    return out


def _parse_dt(date: str, time: str, tz: str) -> datetime:
    date = date.strip()
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            d = datetime.strptime(date, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"unknown date format: {date!r}")
    if time and time.strip():
        h, m, *s = (time.strip().split(":") + ["0"])[:3]
        d = d.replace(hour=int(h), minute=int(m), second=int(s[0]) if s else 0)
    zone: timezone | ZoneInfo = timezone.utc
    tz = (tz or "").strip()
    if tz in ("EET", "EEST"):
        zone = ZoneInfo("Europe/Helsinki")
    elif tz in ("PDT", "PST"):
        zone = ZoneInfo("America/Los_Angeles")  # PayPal's own exports often use Pacific time
    elif tz in ("CET", "CEST"):
        zone = ZoneInfo("Europe/Berlin")
    elif "/" in tz:
        try:
            zone = ZoneInfo(tz)
        except Exception:
            zone = timezone.utc
    elif tz.startswith(("GMT", "UTC")) and len(tz) > 3:
        sign = 1 if tz[3] == "+" else -1
        hh, _, mm = tz[4:].partition(":")
        zone = timezone(sign * timedelta(hours=int(hh or 0), minutes=int(mm or 0)))
    return d.replace(tzinfo=zone).astimezone(timezone.utc)


def _sniff(text: str) -> str:
    first = text.splitlines()[0] if text else ""
    return ";" if first.count(";") > first.count(",") else ","


def read_rows(text: str) -> Iterator[dict[str, str]]:
    reader = csv.reader(io.StringIO(text), delimiter=_sniff(text))
    header = next(reader)
    cols = _canon(header)
    idx = {k: header.index(v) for k, v in cols.items()}
    for raw in reader:
        if not any(c.strip() for c in raw):
            continue
        yield {k: (raw[i] if i < len(raw) else "") for k, i in idx.items()}


def to_txn(row: dict[str, str]) -> Txn:
    type_text = row.get("Type", "").strip()
    type_text = FI_TYPES.get(type_text.lower(), type_text)
    gross = parse_amount(row["Gross"])
    impact = IMPACT.get(row.get("Balance Impact", "").strip().lower())
    if impact is None:
        impact = "debit" if gross < 0 else "credit"
    counterparty = (row.get("Name") or row.get("To Email Address") or "").strip() or "unknown"
    ref = (row.get("Reference Txn ID") or "").strip() or None
    amount = -gross  # consumer side: a debit of -18.90 is a payment of 18.90
    if type_text.lower() in ("payment refund", "refund") and amount > 0:
        amount = -amount
    return Txn(
        txn_id=row["Transaction ID"].strip(),
        at=_parse_dt(row["Date"], row.get("Time", ""), row.get("TimeZone", "")),
        counterparty=counterparty,
        amount=amount,
        currency=row["Currency"].strip().upper(),
        type=type_text,
        status=STATUS.get(row.get("Status", "").strip().lower(), "S"),
        ref_id=ref,
        ref_type=ref_type_of(ref),
        balance_impact=impact,
        source="import_csv",
        category=(row.get("Category") or "").strip() or None,
    )


def load(path: str | Path) -> list[Txn]:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return parse(text)


def parse(text: str) -> list[Txn]:
    return [to_txn(r) for r in read_rows(text)]


def write(rows: Iterable[dict[str, str]], path: str | Path, header: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)
