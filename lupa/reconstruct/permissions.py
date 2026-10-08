"""Deterministic grouping of charges into permissions (build spec 4).

Grouping key, in order of preference:
  1. subscription id (SUB / I-...)
  2. pre-approved payment id (PAP / B-...)
  3. the counterparty, when it has two or more charges
  4. a lone charge is a one-time authority only if the known agreement list
     says the counterparty still holds an active agreement; otherwise it is a
     plain purchase and not a permission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path

import yaml

from ..importers.txn import Txn, is_charge, is_refund
from ..ledger.models import Payment, Permission, Profile
from ..ledger.repo import Repo
from . import classify, profile


@dataclass
class KnownMerchant:
    alias: str
    category: str = "digital service"
    agreement: str | None = None          # "active" when the settings list shows one
    agreement_ref: str | None = None
    last_known_payment: datetime | None = None


@dataclass
class Known:
    reference_date: datetime | None = None
    merchants: dict[str, KnownMerchant] = field(default_factory=dict)

    def has_agreement(self, alias: str) -> bool:
        m = self.merchants.get(alias)
        return bool(m and m.agreement == "active")

    def category(self, alias: str) -> str | None:
        m = self.merchants.get(alias)
        return m.category if m else None


def _dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time(12), tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc)


def load_known(path: str | Path | None) -> Known:
    if not path or not Path(path).exists():
        return Known()
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    known = Known(reference_date=_dt(data.get("reference_date")))
    for alias, m in (data.get("merchants") or {}).items():
        m = m or {}
        known.merchants[alias] = KnownMerchant(
            alias=alias,
            category=m.get("category", "digital service"),
            agreement=m.get("agreement"),
            agreement_ref=m.get("agreement_ref"),
            last_known_payment=_dt(m.get("last_known_payment")),
        )
    return known


@dataclass
class Reconstructed:
    permission: Permission
    profile: Profile
    payments: list[Txn]


def _source(t: Txn, key_kind: str) -> str:
    if t.source == "import_csv":
        return "import_csv"
    return {"SUB": "paypal_sub", "PAP": "paypal_pap"}.get(key_kind, "paypal_order")


def group(txns: list[Txn], known: Known) -> dict[tuple[str, str], list[Txn]]:
    charges = [t for t in txns if is_charge(t) and not is_refund(t)]
    refunds = [t for t in txns if is_refund(t)]
    groups: dict[tuple[str, str], list[Txn]] = {}
    loose: dict[str, list[Txn]] = {}
    # A charge can point at an authorization row instead of the agreement; that
    # authorization row carries the B- reference. Follow that one hop.
    agreement_of = {t.txn_id: t.ref_id for t in txns
                    if t.ref_type in ("SUB", "PAP") and t.ref_id and t.txn_id}
    for t in charges:
        ref_type, ref_id = t.ref_type, t.ref_id
        if ref_type not in ("SUB", "PAP") and ref_id in agreement_of:
            ref_id = agreement_of[ref_id]
            ref_type = "SUB" if ref_id.startswith("I-") else "PAP"
        if ref_type in ("SUB", "PAP") and ref_id:
            groups.setdefault((ref_type, ref_id), []).append(t)
        else:
            loose.setdefault(t.counterparty, []).append(t)
    for cp, ts in loose.items():
        if len(ts) >= 2:
            groups[("CP", cp)] = ts
        elif known.has_agreement(cp):
            groups[("ONE", cp)] = ts
    # refunds attach to the first group of the same counterparty, as negative payments
    for r in refunds:
        for key, ts in groups.items():
            if ts and ts[0].counterparty == r.counterparty:
                ts.append(r)
                break
    return groups


def reconstruct(txns: list[Txn], known: Known, now: datetime) -> list[Reconstructed]:
    out: list[Reconstructed] = []
    seen_aliases: set[str] = set()
    for (kind_key, ref), ts in sorted(group(txns, known).items(), key=lambda kv: kv[1][0].at):
        ts.sort(key=lambda t: t.at)
        positive = [(t.at, t.amount) for t in ts if t.amount > 0]
        first = ts[0]
        alias = first.counterparty
        seen_aliases.add(alias)
        external_ref = ref if kind_key in ("SUB", "PAP") else f"cp:{ref}"
        perm = Permission(
            source=_source(first, kind_key),
            external_ref=external_ref,
            merchant_alias=alias,
            merchant_category=first.category or known.category(alias) or "digital service",
            first_seen=positive[0][0] if positive else first.at,
            last_payment_at=positive[-1][0] if positive else None,
            last_amount=positive[-1][1] if positive else None,
            currency=first.currency,
            marker="●",
        )
        out.append(Reconstructed(perm, _profile(perm, positive, known, now), ts))

    # Agreements on the settings list with no charge in the window: still permissions.
    for alias, m in known.merchants.items():
        if m.agreement != "active" or alias in seen_aliases:
            continue
        perm = Permission(
            source="import_csv",
            external_ref=m.agreement_ref or f"agreement:{alias}",
            merchant_alias=alias,
            merchant_category=m.category,
            first_seen=None,
            last_payment_at=m.last_known_payment,
            currency="EUR",
            marker="●",
        )
        out.append(Reconstructed(perm, _profile(perm, [], known, now), []))
    return out


def _profile(perm: Permission, positive: list[tuple[datetime, int]], known: Known, now: datetime) -> Profile:
    km = known.merchants.get(perm.merchant_alias)
    last_known = km.last_known_payment if km else None
    prof = profile.compute(perm.id, positive, now, last_known=last_known)
    perm.kind = classify.kind_of(prof, known.has_agreement(perm.merchant_alias))
    if perm.kind == "unknown" and perm.source == "paypal_sub":
        # A live subscription's plan is fixed-price by definition, even before three charges.
        perm.kind = "fixed_recurring"
    perm.attention = classify.attention(prof, perm.kind, perm.status, positive, perm.first_seen, now)
    return prof


def rebuild(repo: Repo, txns: list[Txn], known: Known, now: datetime) -> list[Reconstructed]:
    """Upsert reconstructed permissions, keeping ids, status, policy and delegation.

    A permission the human revoked or suspended stays that way: reconstruction
    describes history, it never restores authority.
    """
    result = reconstruct(txns, known, now)
    with repo.db.transaction():
        for rec in result:
            p = rec.permission
            existing = repo.permission_by_ref(p.source, p.external_ref)
            if existing:
                p.id = existing.id
                p.status = existing.status
                p.policy_id = existing.policy_id
                p.delegation_id = existing.delegation_id
                p.created_at = existing.created_at
                p.suggestion = existing.suggestion
                positive = [(t.at, t.amount) for t in rec.payments if t.amount > 0]
                p.attention = classify.attention(rec.profile, p.kind, p.status, positive, p.first_seen, now)
            rec.profile.permission_id = p.id
            repo.save(p)
            repo.save(rec.profile)
            for t in rec.payments:
                src = "import_csv" if t.source == "import_csv" else t.source
                dup = repo.list(Payment, "source = ? AND paypal_txn_id = ?", (src, t.txn_id))
                pay = Payment(
                    id=dup[0].id if dup else Payment.model_fields["id"].default_factory(),
                    permission_id=p.id, paypal_txn_id=t.txn_id, amount=t.amount,
                    currency=t.currency, at=t.at, event_code=t.type, status=t.status, source=src,
                )
                repo.save(pay)
    return result
