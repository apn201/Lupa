"""Everything PayPal goes through here (build spec 8).

Token cache with refresh before `expires_in`, `PayPal-Request-Id` on every
write so a retry never double-charges, one retry on 5xx and none on 4xx, and
a recorder so every ● call can be listed in the API response that caused it.
"""

from __future__ import annotations

import contextlib
import contextvars
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

import httpx

from ..config import Settings

_recorder: contextvars.ContextVar[list | None] = contextvars.ContextVar("paypal_calls", default=None)


class PayPalError(RuntimeError):
    def __init__(self, status: int, name: str = "", message: str = "", debug_id: str = "",
                 details: list | None = None) -> None:
        super().__init__(f"PayPal {status} {name}: {message} (debug_id={debug_id})")
        self.status = status
        self.name = name
        self.message = message
        self.debug_id = debug_id
        self.details = details or []

    def as_dict(self) -> dict:
        return {"status": self.status, "name": self.name, "message": self.message,
                "debug_id": self.debug_id, "details": self.details}


class PayPalDisabled(PayPalError):
    def __init__(self) -> None:
        super().__init__(0, "PAYPAL_DISABLED", "No sandbox credentials configured")


@dataclass
class Call:
    method: str
    path: str
    status: int
    paypal_id: str | None = None
    debug_id: str | None = None
    request_id: str | None = None
    marker: str = "●"
    extra: dict = field(default_factory=dict)


@contextlib.contextmanager
def recording() -> Iterator[list[Call]]:
    calls: list[Call] = []
    token = _recorder.set(calls)
    try:
        yield calls
    finally:
        _recorder.reset(token)


class PayPalClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None) -> None:
        self.settings = settings
        self.base = settings.paypal_base_url.rstrip("/")
        self.http = http or httpx.Client(timeout=30.0)
        self._token: str | None = None
        self._token_expires: float = 0.0

    @property
    def enabled(self) -> bool:
        return self.settings.paypal_enabled

    def token(self) -> str:
        if not self.enabled:
            raise PayPalDisabled()
        if self._token and time.monotonic() < self._token_expires - 60:
            return self._token
        r = self.http.post(
            f"{self.base}/v1/oauth2/token",
            auth=(self.settings.paypal_client_id, self.settings.paypal_client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            data={"grant_type": "client_credentials"},
        )
        if r.status_code != 200:
            raise _error(r)
        body = r.json()
        self._token = body["access_token"]
        self._token_expires = time.monotonic() + float(body.get("expires_in", 3600))
        return self._token

    def request(self, method: str, path: str, *, json: Any = None, params: dict | None = None,
                idempotency_key: str | None = None, headers: dict | None = None) -> dict:
        hdrs = {
            "Authorization": f"Bearer {self.token()}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
            "PayPal-Enforce-ISO8601-Format": "true",
        }
        if idempotency_key:
            hdrs["PayPal-Request-Id"] = idempotency_key
        hdrs.update(headers or {})
        url = f"{self.base}{path}"
        r = None
        for attempt in (1, 2):
            try:
                r = self.http.request(method, url, json=json, params=params, headers=hdrs)
            except httpx.TransportError as exc:
                if attempt == 2:
                    self._record(method, path, 0, None, None, idempotency_key)
                    raise PayPalError(0, "TRANSPORT_ERROR", str(exc)) from exc
                continue
            if r.status_code >= 500 and attempt == 1:
                continue
            break
        assert r is not None
        body: dict = {}
        if r.content:
            try:
                body = r.json()
            except ValueError:
                body = {}
        if r.status_code >= 400:
            err = _error(r, body)
            self._record(method, path, r.status_code, None, err.debug_id, idempotency_key)
            raise err
        self._record(method, path, r.status_code, body.get("id"), r.headers.get("paypal-debug-id"), idempotency_key)
        return body

    def _record(self, method, path, status, pid, debug_id, request_id) -> None:
        calls = _recorder.get()
        if calls is not None:
            calls.append(Call(method=method, path=path, status=status, paypal_id=pid,
                              debug_id=debug_id, request_id=request_id))


def _error(r: httpx.Response, body: dict | None = None) -> PayPalError:
    if body is None:
        try:
            body = r.json()
        except ValueError:
            body = {}
    return PayPalError(
        r.status_code,
        name=body.get("name") or body.get("error", ""),
        message=body.get("message") or body.get("error_description", ""),
        debug_id=body.get("debug_id") or r.headers.get("paypal-debug-id", ""),
        details=body.get("details"),
    )
