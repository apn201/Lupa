"""Typed CRUD over the ledger. Rows in, models out; JSON and datetimes handled here only."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, TypeVar

from pydantic import BaseModel

from .db import Database
from .models import (
    Decision, Delegation, Event, Payment, PaymentRequest, Permission, Policy, Profile,
)

M = TypeVar("M", bound=BaseModel)

TABLES: dict[type[BaseModel], tuple[str, str]] = {
    Permission: ("permission", "id"),
    Profile: ("profile", "permission_id"),
    Payment: ("payment", "id"),
    Policy: ("policy", "id"),
    Delegation: ("delegation", "id"),
    PaymentRequest: ("payment_request", "id"),
    Decision: ("decision", "id"),
    Event: ("event", "id"),
}


def _to_db(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _row(model: BaseModel) -> dict[str, Any]:
    return {k: _to_db(v) for k, v in model.model_dump(mode="python").items()}


def _from_db(cls: type[M], row) -> M:
    data = dict(row)
    for name, field in cls.model_fields.items():
        value = data.get(name)
        if isinstance(value, str) and value[:1] in "[{" and _is_json_field(field.annotation):
            data[name] = json.loads(value)
    return cls.model_validate(data)


def _is_json_field(annotation: Any) -> bool:
    text = str(annotation)
    return "list" in text or "dict" in text


class Repo:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---- generic -----------------------------------------------------------
    def save(self, model: M) -> M:
        table, _ = TABLES[type(model)]
        row = _row(model)
        cols = ", ".join(row)
        marks = ", ".join(f":{k}" for k in row)
        self.db.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({marks})", row)
        return model

    def get(self, cls: type[M], key: str) -> M | None:
        table, pk = TABLES[cls]
        rows = self.db.query(f"SELECT * FROM {table} WHERE {pk} = ?", (key,))
        return _from_db(cls, rows[0]) if rows else None

    def list(self, cls: type[M], where: str = "", params: tuple = (), order: str = "") -> list[M]:
        table, _ = TABLES[cls]
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        if order:
            sql += f" ORDER BY {order}"
        return [_from_db(cls, r) for r in self.db.query(sql, params)]

    # ---- permissions -------------------------------------------------------
    def permission_by_ref(self, source: str, external_ref: str) -> Permission | None:
        found = self.list(Permission, "source = ? AND external_ref = ?", (source, external_ref))
        return found[0] if found else None

    def permission_by_alias(self, alias: str) -> list[Permission]:
        return self.list(Permission, "merchant_alias = ?", (alias,), "created_at")

    def payments_for(self, permission_id: str) -> list[Payment]:
        return self.list(Payment, "permission_id = ?", (permission_id,), "at")

    def profile_for(self, permission_id: str) -> Profile | None:
        return self.get(Profile, permission_id)

    # ---- policies ----------------------------------------------------------
    def default_policy(self) -> Policy | None:
        found = self.list(Policy, "permission_id IS NULL", (), "created_at DESC")
        return found[0] if found else None

    def policy_for(self, perm: Permission) -> Policy | None:
        """The permission's own policy, else the account default."""
        if perm.policy_id:
            pol = self.get(Policy, perm.policy_id)
            if pol:
                return pol
        return self.default_policy()

    # ---- delegations -------------------------------------------------------
    def active_delegation(self, permission_id: str, agent_id: str | None) -> Delegation | None:
        if not agent_id:
            return None
        found = self.list(
            Delegation, "permission_id = ? AND agent_id = ? AND revoked_at IS NULL",
            (permission_id, agent_id), "expires_at DESC",
        )
        return found[0] if found else None

    # ---- requests and decisions -------------------------------------------
    def decisions_for(self, request_id: str) -> list[Decision]:
        return self.list(Decision, "request_id = ?", (request_id,), "resolved_at")

    def month_total(self, permission_id: str, at: datetime, exclude_request: str | None = None) -> int:
        """Captured plus allowed spend on this permission in the request's calendar month."""
        month = at.strftime("%Y-%m")
        rows = self.db.query(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM payment_request WHERE permission_id = ? "
            "AND substr(requested_at, 1, 7) = ? AND state IN ('allowed', 'captured') AND id != ?",
            (permission_id, month, exclude_request or ""),
        )
        return int(rows[0]["s"])

    # ---- meta --------------------------------------------------------------
    def get_meta(self, key: str) -> str | None:
        rows = self.db.query("SELECT value FROM meta WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))

    # ---- audit -------------------------------------------------------------
    def log(self, kind: str, marker: str, ref_id: str | None = None, **payload: Any) -> Event:
        return self.save(Event(kind=kind, marker=marker, ref_id=ref_id, payload=payload))

    def events_since(self, since: str | None = None, limit: int = 500) -> list[Event]:
        if since:
            return self.list(Event, "at > ?", (since,), f"at DESC LIMIT {int(limit)}")
        return self.list(Event, "", (), f"at DESC LIMIT {int(limit)}")
