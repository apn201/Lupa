"""Expected counts on the sample, frozen.

These are frozen on the synthetic sample. When data/sample_activity_anonymized.csv
exists, add its counts from the real numbers and freeze those too.
"""

from __future__ import annotations

from collections import Counter

from lupa.importers import activity_csv
from lupa.money import parse_amount
from lupa.reconstruct import permissions as recon

from .conftest import KNOWN, NOW, SAMPLE


def run():
    known = recon.load_known(KNOWN)
    return recon.reconstruct(activity_csv.load(SAMPLE), known, known.reference_date)


def by_alias():
    return {r.permission.merchant_alias: r for r in run()}


def test_counts_frozen():
    res = run()
    assert len(res) == 22
    kinds = Counter(r.permission.kind for r in res)
    assert kinds == {"one_time_authority": 13, "variable_recurring": 4, "fixed_recurring": 4, "unknown": 1}
    flags = Counter(f for r in res for f in r.permission.attention)
    assert flags == {"ONE_OFF_STILL_ACTIVE": 13, "NO_HISTORY": 10, "DORMANT_12M": 7, "DORMANT_6M": 2,
                     "AMOUNT_JUMP": 1, "INTERVAL_BREAK": 1, "NEW_LAST_30D": 1}


def test_kinds():
    m = by_alias()
    assert m["Merchant A"].permission.kind == "fixed_recurring"
    assert m["Merchant G"].permission.kind == "fixed_recurring"  # weekly
    assert m["Merchant C"].permission.kind == "variable_recurring"
    assert m["Merchant H"].permission.kind == "one_time_authority"
    assert m["Merchant I"].permission.kind == "unknown"
    assert "Merchant J" not in m  # one plain purchase, no agreement: not a permission


def test_flags():
    m = by_alias()
    assert "AMOUNT_JUMP" in m["Merchant F"].permission.attention
    assert "INTERVAL_BREAK" in m["Merchant L"].permission.attention
    assert "NEW_LAST_30D" in m["Merchant M"].permission.attention
    assert {"NO_HISTORY", "DORMANT_12M"} <= set(m["Merchant N"].permission.attention)


def test_profile_numbers():
    c = by_alias()["Merchant C"].profile
    assert (c.n_payments, c.amount_min, c.amount_max, c.amount_median) == (6, 1750, 2130, 1890)
    assert 28 <= c.interval_days_median <= 31


def test_funding_and_conversion_rows_ignored():
    pays = [t for r in run() for t in r.payments]
    assert all(t.type not in ("General Card Deposit", "General Currency Conversion") for t in pays)


def test_refund_attached_negative():
    i = by_alias()["Merchant I"]
    assert [t.amount for t in i.payments if t.amount < 0] == [-2290]
    assert i.profile.n_payments == 2


def test_parse_amount_finnish():
    assert parse_amount("−3,14") == -314
    assert parse_amount("1 234,50") == 123450
    assert parse_amount("1.234,50") == 123450
    assert parse_amount("18.90") == 1890


def test_finnish_headers():
    text = ("Päiväys;Kellonaika;Aikavyöhyke;Nimi;Kuvaus;Tila;Valuutta;Brutto;Netto;Saldo;"
            "Tapahtuman tunniste;Viitetapahtuman tunniste\n"
            "03.04.2026;10:00:00;EET;Merchant A;Esivaltuutetun maksun käyttäjän laskumaksu;Valmis;EUR;"
            "−8,49;−8,49;0,00;ABC;B-XYZ\n")
    [t] = activity_csv.parse(text)
    assert t.amount == 849 and t.ref_type == "PAP" and t.type == "PreApproved Payment Bill User Payment"
    assert t.at.hour == 7  # 10:00 Helsinki summer time is 07:00 UTC


def test_rebuild_keeps_revoked_status(lupa_no_ai):
    lp = lupa_no_ai
    c = next(p for p in lp.list_permissions() if p["merchant_alias"] == "Merchant C")
    lp.revoke(c["id"])
    lp.import_csv(str(SAMPLE), str(KNOWN), now=NOW)
    assert lp.permission(c["id"]).status == "revoked"
    assert len(lp.list_permissions()) == 22


# ------------------------------------------------- the anonymized real export
REAL = SAMPLE.parent / "sample_activity_anonymized.csv"
REAL_KNOWN = SAMPLE.parent / "merchants.yml"


def test_real_sample_counts_frozen():
    """Frozen from the real numbers on 2026-10-08: the export plus a partial settings list (8 agreements)."""
    import pytest
    if not REAL.exists():
        pytest.skip("no anonymized sample")
    known = recon.load_known(REAL_KNOWN)
    res = recon.reconstruct(activity_csv.load(REAL), known, known.reference_date)
    assert len(res) == 20
    assert sum(r.permission.external_ref.startswith("B-") for r in res) == 18
    assert Counter(r.permission.kind for r in res) == {
        "unknown": 9, "one_time_authority": 6, "fixed_recurring": 4, "variable_recurring": 1}
    assert Counter(f for r in res for f in r.permission.attention) == {
        "ONE_OFF_STILL_ACTIVE": 6, "NEW_LAST_30D": 3, "NO_HISTORY": 3, "AMOUNT_JUMP": 2,
        "DORMANT_12M": 1, "DORMANT_6M": 1}
    assert Counter(r.permission.currency for r in res) == {"EUR": 17, "USD": 2, "SEK": 1}


def test_charge_linked_through_authorization_joins_its_agreement():
    """Real exports: the payment points at an authorization row, which carries the B- reference."""
    text = ("Date,Time,TimeZone,Name,Type,Status,Currency,Gross,Net,Transaction ID,Reference Txn ID,Balance Impact\n"
            "02/07/2026,10:00:00,PDT,Merchant O,General Authorization,Completed,EUR,-68.46,-68.46,AUTH1,B-AGREEMENT01,Memo\n"
            "02/07/2026,10:00:01,PDT,Merchant O,PreApproved Payment Bill User Payment,Completed,EUR,-68.46,-68.46,PAY1,AUTH1,Debit\n")
    [rec] = recon.reconstruct(activity_csv.parse(text), recon.Known(), NOW)
    assert rec.permission.external_ref == "B-AGREEMENT01" and rec.profile.n_payments == 1
