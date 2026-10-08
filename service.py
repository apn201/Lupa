"""Orchestration: ledger + engine + AI + PayPal. The routes stay thin.

Order of a payment request:
  1. store the request (◇)
  2. ◆ assess it (Lupa's model and, if an agent submitted one, the agent's view)
  3. ■ evaluate: the engine alone decides
  4. ● execute: ALLOW -> authorize + capture, HOLD -> authorize only,
     BLOCK -> nothing (or void an authorization that already exists)
Every step writes an event with its marker. That is the Trace screen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import config
from .ai import assess_payment, explain_permission, intent_to_policy, suggest_limit
from .ai.llm import LLM
from .config import AI, PAYPAL, POLICY, PROPOSED, Settings
from .importers import activity_csv
from .importers.txn import Txn
from .ledger.db import Database
from .ledger.models import (
    AiVerdict, Decision, Delegation, Payment, PaymentRequest, Permission, Policy, RuleHit, utcnow,
)
from .ledger.repo import Repo
from .money import parse_amount
from .paypal import orders, reporting, subscriptions
from .paypal.client import Call, PayPalClient, PayPalError, recording
from .policy import engine, sentences
from .reconstruct import permissions as recon

log = logging.getLogger("lupa")

SETTINGS_LINK = "https://www.paypal.com/myaccount/autopay/"


class LupaError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, **extra) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra


@dataclass
class Outcome:
    """What a write returns: the result plus the ● calls it caused."""
    data: dict
    calls: list[Call] = field(default_factory=list)


class Lupa:
    def __init__(self, settings: Settings, db: Database | None = None, paypal: PayPalClient | None = None,
                 llm: LLM | None = None, clock=utcnow) -> None:
        self.settings = settings
        self.db = db or Database(settings.db_path)
        self.repo = Repo(self.db)
        self.paypal = paypal or PayPalClient(settings)
        self.llm = llm or LLM(settings)
        self.clock = clock
        self.ensure_default_policy()

    # ------------------------------------------------------------------ setup
    def ensure_default_policy(self) -> Policy:
        pol = self.repo.default_policy()
        if pol is None:
            pol = self.repo.save(Policy(permission_id=None, max_amount=5000, currency=self.settings.currency,
                                        recurring="allow", amount_increase="require_approval",
                                        new_merchant="require_approval"))
        return pol

    def import_csv(self, path: str, known_path: str | None, now: datetime | None = None) -> dict:
        txns = activity_csv.load(path)
        known = recon.load_known(known_path)
        now = now or known.reference_date or self.clock()
        result = recon.rebuild(self.repo, txns, known, now)
        self.repo.log("import.csv", PROPOSED, None, rows=len(txns), permissions=len(result))
        return {"rows": len(txns), "permissions": len(result)}

    # ------------------------------------------------------------ permissions
    def permission(self, pid: str) -> Permission:
        perm = self.repo.get(Permission, pid)
        if perm is None:
            raise LupaError("permission_not_found", f"No permission {pid}", 404)
        return perm

    def summary(self, perm: Permission) -> dict:
        prof = self.repo.profile_for(perm.id)
        return {
            **perm.model_dump(mode="json"),
            "profile": prof.model_dump(mode="json") if prof else None,
            "attention_sentences": [
                {"code": c, "text": sentences.for_attention(c, perm, prof), "marker": POLICY}
                for c in perm.attention
            ],
        }

    def list_permissions(self, status: str | None = None, kind: str | None = None,
                         attention: str | None = None) -> list[dict]:
        perms = self.repo.list(Permission, order="last_payment_at IS NULL, last_payment_at DESC")
        out = []
        for p in perms:
            if status and p.status != status:
                continue
            if kind and p.kind != kind:
                continue
            if attention and attention not in p.attention:
                continue
            out.append(self.summary(p))
        return out

    def headline(self) -> dict:
        perms = [p for p in self.repo.list(Permission) if p.status == "active"]
        silent = [p for p in perms if "DORMANT_12M" in p.attention]
        return {"active": len(perms), "silent_over_a_year": len(silent),
                "text": f"{len(perms)} companies can take money from you. "
                        f"{len(silent)} have not in over a year."}

    def permission_detail(self, pid: str) -> dict:
        perm = self.permission(pid)
        pol = self.repo.policy_for(perm)
        reqs = self.repo.list(PaymentRequest, "permission_id = ?", (pid,), "requested_at DESC LIMIT 20")
        dlgs = self.repo.list(Delegation, "permission_id = ?", (pid,), "expires_at DESC")
        return {
            **self.summary(perm),
            "payments": [p.model_dump(mode="json") for p in self.repo.payments_for(pid)],
            "policy": pol.model_dump(mode="json") if pol else None,
            "policy_is_default": bool(pol and pol.permission_id is None),
            "delegations": [d.model_dump(mode="json") for d in dlgs],
            "requests": [self.request_view(r) for r in reqs],
        }

    def create_agent_permission(self, agent_id: str, label: str, category: str = "marketplace") -> Permission:
        """◇ A permission that exists only in Lupa: authority for an agent, not a merchant agreement."""
        perm = Permission(source="lupa_delegation", external_ref=f"agent:{agent_id}:{label}",
                          merchant_alias=label, merchant_category=category, kind="agent_authority",
                          first_seen=self.clock(), currency=self.settings.currency, marker=PROPOSED)
        if self.repo.permission_by_ref(perm.source, perm.external_ref):
            raise LupaError("permission_exists", f"{perm.external_ref} already exists", 409)
        self.repo.save(perm)
        self.repo.log("permission.created", PROPOSED, perm.id, agent_id=agent_id, label=label)
        return perm

    def revoke(self, pid: str, action: str = "revoke") -> Outcome:
        """Real where PayPal allows it, honest where it does not."""
        perm = self.permission(pid)
        new_status = "revoked" if action == "revoke" else "suspended"
        paypal_action = "not_available_to_buyer"
        calls: list[Call] = []
        if perm.source == "paypal_sub":
            fn = subscriptions.cancel if action == "revoke" else subscriptions.suspend
            with recording() as calls:
                try:
                    fn(self.paypal, perm.external_ref, f"{action} via Lupa", key=f"{pid}-{action}")
                    paypal_action = "cancelled" if action == "revoke" else "suspended"
                except PayPalError as exc:
                    self.repo.log(f"permission.{action}.paypal_error", PAYPAL, pid, error=exc.as_dict())
                    raise LupaError("paypal_error", exc.message or exc.name, 502,
                                    paypal={"name": exc.name, "debug_id": exc.debug_id}) from exc
            self.repo.log(f"paypal.subscription.{action}", PAYPAL, pid,
                          subscription_id=perm.external_ref, calls=_calls(calls))
        perm.status = new_status
        perm.attention = [a for a in perm.attention if a not in ("DORMANT_6M", "DORMANT_12M", "ONE_OFF_STILL_ACTIVE", "NO_HISTORY")]
        self.repo.save(perm)
        self.repo.log(f"permission.{action}", PROPOSED, pid, status=new_status, paypal_action=paypal_action)
        data = {"permission": self.summary(perm), "paypal_action": paypal_action}
        if paypal_action == "not_available_to_buyer":
            data["note"] = ("PayPal has no buyer-side API for this agreement. Lupa marked it "
                            f"{new_status} and will block payments through it; cancel it in your "
                            "PayPal settings as well.")
            data["settings_link"] = SETTINGS_LINK
        return Outcome(data, calls)

    # --------------------------------------------------------------- policies
    def set_policy(self, pid: str | None, pol: Policy) -> Policy:
        if pid is not None:
            perm = self.permission(pid)
            pol.permission_id = pid
        _validate_policy(pol)
        self.repo.save(pol)
        if pid is not None:
            perm.policy_id = pol.id
            self.repo.save(perm)
        self.repo.log("policy.set", POLICY, pid or pol.id, policy=pol.model_dump(mode="json"))
        return pol

    def draft_from_intent(self, text: str) -> dict:
        default = self.ensure_default_policy()
        draft = intent_to_policy.run(self.llm, text, default)
        if draft is None:
            self.repo.log("intent.unavailable", AI, None, text=text)
            raise LupaError("ai_unavailable", "The draft could not be made. Set the policy by hand.", 503)
        lines = [s for c in draft.reason_codes if (s := sentences.for_intent(c, draft.policy))]
        self.repo.log("intent.draft", AI, None, text=text, reason_codes=draft.reason_codes,
                      model=draft.model, prompt_version=draft.prompt_version)
        return {"draft": draft.policy.model_dump(mode="json", exclude={"id", "created_at"}),
                "reason_codes": draft.reason_codes, "sentences": lines,
                "model": draft.model, "prompt_version": draft.prompt_version, "stored": False}

    def suggested_limit(self, pid: str) -> dict:
        perm = self.permission(pid)
        prof = self.repo.profile_for(pid)
        if prof is None or not prof.n_payments:
            raise LupaError("no_history", "No payments to base a limit on.", 409)
        s = suggest_limit.run(self.llm, prof)
        self.repo.log("limit.suggested", AI if s.by == "ai" else POLICY, pid,
                      candidates=s.candidates, pick=s.pick, limit=s.limit, reason_code=s.reason_code)
        return {**s.model_dump(), "marker": AI if s.by == "ai" else POLICY,
                "sentence": sentences.for_limit(prof, s.limit, perm.currency)}

    def explain(self, pid: str) -> dict | None:
        perm = self.permission(pid)
        prof = self.repo.profile_for(pid)
        if perm.kind != "unknown" or prof is None:
            return perm.suggestion
        sug = explain_permission.run(self.llm, perm, prof, self.repo.payments_for(pid))
        if sug:
            perm.suggestion = sug
            self.repo.save(perm)
            self.repo.log("permission.explained", AI, pid, **sug)
        return sug

    # ------------------------------------------------------------ delegations
    def delegate(self, pid: str, agent_id: str, authority: str, max_amount: int, recurring_allowed: bool,
                 amount_change_pct: int, min_confidence: float, expires_at: datetime) -> Delegation:
        perm = self.permission(pid)
        if expires_at <= self.clock():
            raise LupaError("delegation_expired", "expires_at is in the past", 400)
        dlg = Delegation(permission_id=pid, agent_id=agent_id, authority=authority, max_amount=max_amount,
                         recurring_allowed=recurring_allowed, amount_change_pct=amount_change_pct,
                         min_confidence=min_confidence, expires_at=expires_at)
        self.repo.save(dlg)
        perm.delegation_id = dlg.id
        self.repo.save(perm)
        self.repo.log("delegation.created", POLICY, dlg.id, permission_id=pid, agent_id=agent_id,
                      authority=authority, max_amount=max_amount)
        return dlg

    def revoke_delegation(self, did: str) -> Delegation:
        dlg = self.repo.get(Delegation, did)
        if dlg is None:
            raise LupaError("delegation_not_found", f"No delegation {did}", 404)
        dlg.revoked_at = self.clock()
        self.repo.save(dlg)
        self.repo.log("delegation.revoked", POLICY, did)
        return dlg

    # --------------------------------------------------------------- requests
    def request_payment(self, pid: str, amount: int, currency: str, merchant_alias: str | None,
                        is_recurring: bool, source: str = "api", agent_id: str | None = None,
                        purpose: str | None = None, execute: bool | None = None,
                        agent_assessment: AiVerdict | None = None) -> Outcome:
        perm = self.permission(pid)
        req = PaymentRequest(permission_id=pid, amount=amount, currency=currency,
                             merchant_alias=merchant_alias or perm.merchant_alias, is_recurring=is_recurring,
                             source=source, agent_id=agent_id, purpose=purpose, requested_at=self.clock())
        self.repo.save(req)
        self.repo.log("request.received", PROPOSED, req.id, permission_id=pid, amount=amount,
                      currency=currency, merchant=req.merchant_alias, recurring=is_recurring, agent_id=agent_id)
        execute = self.paypal.enabled if execute is None else execute
        return self._decide(req, perm, execute=execute, agent_assessment=agent_assessment, assess=True)

    def submit_decision(self, rid: str, decision: str, confidence: float, reason: str | None,
                        agent_id: str | None) -> Outcome:
        req = self._request(rid)
        if req.state not in ("held", "received"):
            raise LupaError("request_closed", f"Request is {req.state}", 409)
        verdict = AiVerdict(verdict=decision, confidence=confidence, reason_codes=[],
                            source=f"agent:{agent_id or 'unknown'}")
        self.repo.log("request.agent_decision", AI, rid, decision=decision, confidence=confidence,
                      reason=reason, agent_id=agent_id)
        perm = self.permission(req.permission_id)
        return self._decide(req, perm, execute=self.paypal.enabled or bool(req.paypal_authorization_id),
                            agent_assessment=verdict, assess=True)

    def _decide(self, req: PaymentRequest, perm: Permission, *, execute: bool,
                agent_assessment: AiVerdict | None, assess: bool) -> Outcome:
        prof = self.repo.profile_for(perm.id)
        pol = self.repo.policy_for(perm) or self.ensure_default_policy()
        dlg = self.repo.active_delegation(perm.id, req.agent_id)
        if req.agent_id and dlg is None:
            # an expired-or-revoked delegation still names the limits it had
            past = self.repo.list(Delegation, "permission_id = ? AND agent_id = ?", (perm.id, req.agent_id),
                                  "expires_at DESC")
            dlg = past[0] if past else None

        lupa_ai = None
        if assess:
            lupa_ai = assess_payment.run(self.llm, req, perm, prof)
            if lupa_ai is not None:
                self.repo.log("ai.assessed", AI, req.id, verdict=lupa_ai.verdict, confidence=lupa_ai.confidence,
                              reason_codes=lupa_ai.reason_codes, model=lupa_ai.model,
                              prompt_version=lupa_ai.prompt_version)
            else:
                self.repo.log("ai.unavailable", AI, req.id)
        ai = engine.combine_ai(lupa_ai, agent_assessment)

        month_total = self.repo.month_total(perm.id, req.requested_at, exclude_request=req.id)
        ev = engine.evaluate(req, perm, prof, pol, dlg, ai, month_total=month_total)
        dec = Decision(
            request_id=req.id, ai_verdict=ai.verdict if ai else None, ai_confidence=ai.confidence if ai else None,
            ai_reason_codes=ai.reason_codes if ai else [], ai_model=ai.model if ai else None,
            ai_prompt_version=ai.prompt_version if ai else None,
            policy_verdict=ev.policy_verdict, rule_hits=ev.rule_hits, final=ev.final, resolved_at=self.clock(),
        )
        dec.sentences = self._sentences(ev.rule_hits, ev.reason_codes, ai, req, prof)
        self.repo.log("policy.evaluated", POLICY, req.id, policy_verdict=ev.policy_verdict, final=ev.final,
                      rules=ev.rule_ids)

        calls: list[Call] = []
        with recording() as calls:
            self._execute(req, dec, pol, execute)
        self.repo.save(dec)
        self.repo.save(req)
        return Outcome({"request": self.request_view(req), "decision": self.decision_view(dec)}, calls)

    def _execute(self, req: PaymentRequest, dec: Decision, pol: Policy, execute: bool) -> None:
        final = dec.final
        if final == "BLOCK":
            req.state = "blocked"
            if req.paypal_authorization_id and execute:
                self._void(req, dec, reason="blocked")
            return
        if not execute:
            req.state = "allowed" if final == "ALLOW" else "held"
            if final == "HOLD":
                req.hold_until = self.clock() + timedelta(hours=self.settings.hold_hours)
            return
        try:
            if not req.paypal_authorization_id:
                order = orders.create_authorize_order(
                    self.paypal, req.id, req.amount, req.currency, f"{req.merchant_alias} via Lupa")
                req.paypal_order_id = order["id"]
                auth = orders.authorization_of(order)
                if auth is None:
                    order = orders.authorize(self.paypal, order["id"], req.id)
                    auth = orders.authorization_of(order)
                if auth is None:
                    raise PayPalError(0, "NO_AUTHORIZATION", f"order {req.paypal_order_id} returned none")
                req.paypal_authorization_id = auth["id"]
                self.repo.log("paypal.authorized", PAYPAL, req.id, order_id=req.paypal_order_id,
                              authorization_id=req.paypal_authorization_id, status=auth.get("status"))
            if final == "ALLOW":
                cap = orders.capture(self.paypal, req.paypal_authorization_id, req.amount, req.currency, key=req.id)
                req.state = "captured"
                dec.paypal_action = "captured"
                self._record_capture(req, cap)
            else:
                req.state = "held"
                req.hold_until = self.clock() + timedelta(hours=self.settings.hold_hours)
                dec.paypal_action = "authorized"
        except PayPalError as exc:
            # Fail closed: nothing captured, the request waits for a human.
            self.repo.log("paypal.error", PAYPAL, req.id, error=exc.as_dict())
            dec.rule_hits.append(RuleHit(rule="PAYPAL_UNAVAILABLE", verdict="HOLD",
                                         values={"name": exc.name, "debug_id": exc.debug_id}))
            dec.final = "HOLD" if dec.final == "ALLOW" else dec.final
            dec.sentences.append(sentences.for_rule("PAYPAL_UNAVAILABLE", {}))
            req.state = "held"
            req.hold_until = self.clock() + timedelta(hours=self.settings.hold_hours)

    def _record_capture(self, req: PaymentRequest, cap: dict) -> None:
        self.repo.log("paypal.captured", PAYPAL, req.id, capture_id=cap.get("id"), status=cap.get("status"),
                      authorization_id=req.paypal_authorization_id)
        self.repo.save(Payment(permission_id=req.permission_id, paypal_txn_id=cap.get("id"), amount=req.amount,
                               currency=req.currency, at=self.clock(), event_code="lupa_capture",
                               status="S", source="lupa_capture"))

    def _void(self, req: PaymentRequest, dec: Decision | None, reason: str) -> None:
        orders.void(self.paypal, req.paypal_authorization_id, key=req.id)
        if dec is not None:
            dec.paypal_action = "voided"
        self.repo.log("paypal.voided", PAYPAL, req.id, authorization_id=req.paypal_authorization_id, reason=reason)

    def resolve(self, rid: str, action: str) -> Outcome:
        """A human approves or rejects a held request. The human is the authority here."""
        req = self._request(rid)
        if req.state != "held":
            raise LupaError("request_not_held", f"Request is {req.state}", 409)
        last = self.repo.decisions_for(rid)
        prev = last[-1] if last else None
        dec = Decision(request_id=rid, policy_verdict=prev.policy_verdict if prev else "HOLD",
                       rule_hits=prev.rule_hits if prev else [], final="ALLOW" if action == "approve" else "BLOCK",
                       resolved_by="human", resolved_at=self.clock(),
                       sentences=["You approved this payment."] if action == "approve" else ["You rejected this payment."])
        calls: list[Call] = []
        with recording() as calls:
            try:
                if action == "approve":
                    if req.paypal_authorization_id:
                        cap = orders.capture(self.paypal, req.paypal_authorization_id, req.amount, req.currency,
                                             key=f"{req.id}-human")
                        dec.paypal_action = "captured"
                        self._record_capture(req, cap)
                        req.state = "captured"
                    else:
                        req.state = "allowed"
                else:
                    if req.paypal_authorization_id:
                        self._void(req, dec, reason="rejected by human")
                    req.state = "voided" if req.paypal_authorization_id else "blocked"
            except PayPalError as exc:
                self.repo.log("paypal.error", PAYPAL, rid, error=exc.as_dict())
                raise LupaError("paypal_error", exc.message or exc.name, 502,
                                paypal={"name": exc.name, "debug_id": exc.debug_id}) from exc
        self.repo.save(dec)
        self.repo.save(req)
        self.repo.log(f"request.{action}d_by_human", PROPOSED, rid, state=req.state)
        return Outcome({"request": self.request_view(req), "decision": self.decision_view(dec)}, calls)

    def expire_holds(self) -> list[str]:
        """Void anything past its hold window. Lupa never relies on PayPal's own expiry."""
        now = self.clock()
        done = []
        for req in self.repo.list(PaymentRequest, "state = 'held' AND hold_until IS NOT NULL AND hold_until <= ?",
                                  (now.isoformat(),)):
            dec = Decision(request_id=req.id, policy_verdict="HOLD", final="BLOCK", resolved_by="expiry",
                           resolved_at=now, sentences=["Nobody approved this in time, so it was cancelled."])
            try:
                if req.paypal_authorization_id and self.paypal.enabled:
                    self._void(req, dec, reason="hold window passed")
                req.state = "expired"
            except PayPalError as exc:
                self.repo.log("paypal.error", PAYPAL, req.id, error=exc.as_dict())
                continue
            self.repo.save(dec)
            self.repo.save(req)
            self.repo.log("request.expired", POLICY, req.id)
            done.append(req.id)
        return done

    def _request(self, rid: str) -> PaymentRequest:
        req = self.repo.get(PaymentRequest, rid)
        if req is None:
            raise LupaError("request_not_found", f"No request {rid}", 404)
        return req

    def queue(self, state: str | None = "held") -> list[dict]:
        where, params = ("state = ?", (state,)) if state else ("", ())
        return [self.request_view(r) for r in self.repo.list(PaymentRequest, where, params, "requested_at DESC")]

    # ------------------------------------------------------------------ views
    def request_view(self, req: PaymentRequest) -> dict:
        decs = self.repo.decisions_for(req.id)
        return {**req.model_dump(mode="json"),
                "decision": self.decision_view(decs[-1]) if decs else None}

    def decision_view(self, dec: Decision) -> dict:
        d = dec.model_dump(mode="json")
        d["markers"] = {"policy": POLICY, "ai": AI if dec.ai_verdict else None,
                        "paypal": PAYPAL if dec.paypal_action != "none" else None}
        return d

    def _sentences(self, hits: list[RuleHit], reasons: list[str], ai: AiVerdict | None,
                   req: PaymentRequest, prof) -> list[str]:
        out = []
        for h in hits:
            out.append(sentences.for_rule(h.rule, h.values, req.currency))
        for r in reasons:
            s = sentences.for_reason(r, {}, req.currency)
            if s:
                out.append(s)
        if ai is not None:
            vals = {"amount": req.amount}
            if prof is not None and prof.n_payments:
                vals.update(min=prof.amount_min, max=prof.amount_max, median=prof.amount_median,
                            ratio=sentences.ratio(req.amount, prof.amount_median))
            for code in ai.reason_codes:
                s = sentences.for_reason(code, vals, req.currency)
                if s and s not in out:
                    out.append(s)
        return out

    # ------------------------------------------------------------------- sync
    def sync(self, days: int = 90) -> dict:
        """● Transaction Search + subscriptions -> ledger -> rebuilt permissions."""
        now = self.clock()
        txns = []
        with recording() as calls:
            for detail in reporting.search(self.paypal, now - timedelta(days=days), now):
                t = reporting.to_txn(detail)
                if t is not None:
                    txns.append(t)
            sub_ids = {p.external_ref for p in self.repo.list(Permission, "source = 'paypal_sub'")}
            sub_ids |= {t.ref_id for t in txns if t.ref_type == "SUB" and t.ref_id}
            for sid in sorted(sub_ids):
                try:
                    sub = subscriptions.get(self.paypal, sid)
                    alias = sub.get("custom_id") or sid
                    for st in subscriptions.list_transactions(
                            self.paypal, sid, _iso(now - timedelta(days=days)), _iso(now)):
                        gross = ((st.get("amount_with_breakdown") or {}).get("gross_amount") or {})
                        if not gross:
                            continue
                        txns.append(Txn(
                            txn_id=st["id"], at=datetime.fromisoformat(st["time"].replace("Z", "+00:00")),
                            counterparty=alias, amount=parse_amount(gross["value"]),
                            currency=gross.get("currency_code", "EUR"), type="T0002",
                            status="S" if st.get("status") == "COMPLETED" else "P",
                            ref_id=sid, ref_type="SUB", source="paypal_sub_txn"))
                except PayPalError as exc:
                    self.repo.log("paypal.error", PAYPAL, sid, error=exc.as_dict())
        # Search rows for a subscription and the subscription's own transaction list
        # describe the same charge; keep one per transaction id.
        seen, unique = set(), []
        for t in txns:
            if t.txn_id in seen:
                continue
            seen.add(t.txn_id)
            unique.append(t)
        # Lupa's own captures are already in the ledger; do not count them twice.
        own = {p.paypal_txn_id for p in self.repo.list(Payment, "source = 'lupa_capture'")}
        unique = [t for t in unique if t.txn_id not in own]
        result = recon.rebuild(self.repo, unique, recon.Known(), now)
        types = sorted({t.ref_type or "-" for t in unique})
        self.repo.log("paypal.sync", PAYPAL, None, transactions=len(unique), permissions=len(result),
                      reference_types=types, calls=len(calls))
        return {"transactions": len(unique), "permissions": len(result), "reference_types": types}


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _calls(calls: list[Call]) -> list[dict]:
    return [c.__dict__ for c in calls]


def _validate_policy(pol: Policy) -> None:
    if pol.max_amount <= 0:
        raise LupaError("policy_invalid", "max_amount must be positive")
    if not 0 <= pol.increase_tolerance_pct <= 500:
        raise LupaError("policy_invalid", "increase_tolerance_pct must be between 0 and 500")
    if pol.max_per_month is not None and pol.max_per_month <= 0:
        raise LupaError("policy_invalid", "max_per_month must be positive")
    if len(pol.currency) != 3:
        raise LupaError("policy_invalid", "currency must be a 3-letter code")
