"""● /paypal/... - the routes that talk to the real sandbox."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from ..config import PAYPAL
from ..paypal import webhooks
from ..paypal.client import PayPalError

router = APIRouter(prefix="/paypal", tags=["● paypal"])
log = logging.getLogger("lupa.webhook")


@router.get("/status")
def status(request: Request):
    lp = request.app.state.lupa
    return {"marker": PAYPAL, "enabled": lp.paypal.enabled, "base_url": lp.paypal.base,
            "card_configured": bool(lp.settings.card_number),
            "webhook_verification": bool(lp.settings.paypal_webhook_id)}


@router.post("/sync")
def sync(request: Request, days: int = 90):
    lp = request.app.state.lupa
    try:
        return {"marker": PAYPAL, **lp.sync(days)}
    except PayPalError as exc:
        raise HTTPException(502, {"code": "paypal_error", "message": str(exc), "paypal": exc.as_dict()})


@router.post("/webhook")
async def webhook(request: Request):
    """Store the event, then sync what it refers to. Signature checked when PAYPAL_WEBHOOK_ID is set."""
    lp = request.app.state.lupa
    event = await request.json()
    verified = None
    if lp.settings.paypal_webhook_id:
        try:
            verified = webhooks.verify(lp.paypal, lp.settings.paypal_webhook_id, dict(request.headers), event)
        except PayPalError:
            verified = False
        if not verified:
            lp.repo.log("paypal.webhook.rejected", PAYPAL, event.get("id"), event_type=event.get("event_type"))
            raise HTTPException(400, {"code": "webhook_unverified", "message": "signature did not verify"})
    kind, ref = webhooks.referenced_resource(event)
    lp.repo.log("paypal.webhook", PAYPAL, event.get("id"), event_type=event.get("event_type"),
                resource_kind=kind, resource_id=ref, verified=verified)
    synced = None
    if lp.paypal.enabled and kind == "subscription":
        try:
            synced = lp.sync(days=35)
        except PayPalError as exc:
            log.warning("sync after webhook failed: %s", exc)
    return {"marker": PAYPAL, "stored": True, "resource": {"kind": kind, "id": ref}, "synced": synced}
