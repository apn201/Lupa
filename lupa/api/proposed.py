"""◇ /proposed/v1/me - the Consumer Payment Authorization API this project proposes.

None of these endpoints exist at PayPal. Every response says so: `"marker": "◇"`
and `"proposed": true`. Where a call caused real sandbox calls, they are listed
under `"paypal": {"marker": "●", "calls": [...]}`.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Request

from ..ledger.models import AiVerdict, Policy
from ..paypal.client import Call
from ..service import Lupa, Outcome
from .schemas import AgentPermissionIn, Assessment, DelegateIn, Envelope, IntentIn, PaymentRequestIn, PolicyIn, ResolveIn

router = APIRouter(prefix="/proposed/v1/me", tags=["◇ proposed"])


def lupa(request: Request) -> Lupa:
    return request.app.state.lupa


def env(data, calls: list[Call] | None = None) -> Envelope:
    paypal = None
    if calls:
        paypal = {"marker": "●", "calls": [c.__dict__ for c in calls]}
    return Envelope(data=data, paypal=paypal)


def out(o: Outcome) -> Envelope:
    return env(o.data, o.calls)


@router.get("/payment-permissions", summary="List payment permissions", response_model=Envelope)
def list_permissions(request: Request, status: str | None = None, kind: str | None = None,
                     attention: str | None = None):
    lp = lupa(request)
    return env({"headline": lp.headline(), "permissions": lp.list_permissions(status, kind, attention)})


@router.post("/payment-permissions", summary="Create an agent permission", response_model=Envelope, status_code=201)
def create_agent_permission(body: AgentPermissionIn, request: Request):
    """Create an agent_authority permission. Delegate it with POST .../delegate."""
    lp = lupa(request)
    return env(lp.summary(lp.create_agent_permission(body.agent_id, body.label, body.category)))


@router.get("/payment-permissions/{pid}", summary="Show payment permission details", response_model=Envelope)
def get_permission(pid: str, request: Request):
    return env(lupa(request).permission_detail(pid))


@router.post("/payment-permissions/{pid}/revoke", summary="Revoke a payment permission", response_model=Envelope)
def revoke(pid: str, request: Request, x_lupa_agent: str | None = Header(default=None)):
    lupa(request).check_agent_may_revoke(pid, x_lupa_agent)
    return out(lupa(request).revoke(pid, "revoke"))


@router.post("/payment-permissions/{pid}/suspend", summary="Suspend a payment permission", response_model=Envelope)
def suspend(pid: str, request: Request, x_lupa_agent: str | None = Header(default=None)):
    lupa(request).check_agent_may_revoke(pid, x_lupa_agent)
    return out(lupa(request).revoke(pid, "suspend"))


@router.put("/payment-permissions/{pid}/policy", summary="Set a permission's policy", response_model=Envelope)
def put_policy(pid: str, body: PolicyIn, request: Request):
    pol = lupa(request).set_policy(pid, Policy(**body.model_dump()))
    return env(pol.model_dump(mode="json"))


@router.get("/policies/default", summary="Show the default policy", response_model=Envelope)
def get_default(request: Request):
    return env(lupa(request).ensure_default_policy().model_dump(mode="json"))


@router.put("/policies/default", summary="Set the default policy", response_model=Envelope)
def put_default(body: PolicyIn, request: Request):
    pol = lupa(request).set_policy(None, Policy(**body.model_dump()))
    return env(pol.model_dump(mode="json"))


@router.post("/intent", summary="Draft a policy from a sentence", response_model=Envelope)
def intent(body: IntentIn, request: Request):
    """◆ Draft a policy from one sentence. Nothing is stored until PUT .../policy."""
    return env(lupa(request).draft_from_intent(body.text))


@router.get("/payment-permissions/{pid}/suggested-limit", summary="Get a suggested limit", response_model=Envelope)
def suggested_limit(pid: str, request: Request):
    return env(lupa(request).suggested_limit(pid))


@router.post("/payment-permissions/{pid}/explain", summary="Explain a permission", response_model=Envelope)
def explain(pid: str, request: Request):
    return env(lupa(request).explain(pid))


@router.post("/payment-permissions/{pid}/delegate", summary="Delegate a permission to an agent", response_model=Envelope)
def delegate(pid: str, body: DelegateIn, request: Request):
    dlg = lupa(request).delegate(pid, **body.model_dump())
    return env(dlg.model_dump(mode="json"))


@router.delete("/delegations/{did}", summary="Revoke a delegation", response_model=Envelope)
def revoke_delegation(did: str, request: Request):
    return env(lupa(request).revoke_delegation(did).model_dump(mode="json"))


@router.post("/payment-permissions/{pid}/requests", summary="Create a payment request", response_model=Envelope)
def payment_request(pid: str, body: PaymentRequestIn, request: Request,
                    x_lupa_agent: str | None = Header(default=None)):
    """A payment request arrives. ◆ assess, ■ decide, ● execute."""
    agent_view = None
    if body.assessment is not None:
        agent_view = AiVerdict(verdict=body.assessment.decision, confidence=body.assessment.confidence,
                               source=f"agent:{x_lupa_agent or 'unknown'}")
    source = "agent" if x_lupa_agent else body.source
    return out(lupa(request).request_payment(
        pid, body.amount, body.currency.upper(), body.merchant_alias, body.is_recurring, source=source,
        agent_id=x_lupa_agent, purpose=body.purpose, execute=body.execute, agent_assessment=agent_view))


@router.post("/requests/{rid}/decision", summary="Submit an agent decision", response_model=Envelope)
def submit_decision(rid: str, body: Assessment, request: Request, x_lupa_agent: str | None = Header(default=None)):
    """An agent submits its own verdict. Stored as an AI verdict; the engine still decides."""
    return out(lupa(request).submit_decision(rid, body.decision, body.confidence, body.reason, x_lupa_agent))


@router.post("/requests/{rid}/resolve", summary="Resolve a held request", response_model=Envelope)
def resolve(rid: str, body: ResolveIn, request: Request):
    return out(lupa(request).resolve(rid, body.action))


@router.get("/requests", summary="List payment requests", response_model=Envelope)
def requests(request: Request, state: str | None = "held"):
    return env(lupa(request).queue(state or None))


@router.get("/events", summary="List events", response_model=Envelope)
def events(request: Request, since: str | None = None, limit: int = 300):
    evs = lupa(request).repo.events_since(since, limit)
    return env([e.model_dump(mode="json") for e in evs])
