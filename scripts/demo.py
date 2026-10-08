"""Replay a scenario against the running API and print expected vs actual.

    python scripts/demo.py                         # data/scenarios/demo_main.json on localhost:8000
    python scripts/demo.py --pause 2 --base http://127.0.0.1:8000 data/scenarios/demo_main.json

Uses only the public ◇ API, like any agent would.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
P = "/proposed/v1/me"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", nargs="?", default=str(ROOT / "data" / "scenarios" / "demo_main.json"))
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--pause", type=float, default=0.0)
    args = ap.parse_args()

    steps = json.loads(Path(args.scenario).read_text(encoding="utf-8"))["steps"]
    c = httpx.Client(base_url=args.base, timeout=60)
    perms = c.get(f"{P}/payment-permissions").json()["data"]["permissions"]
    saved: dict[str, str] = {}
    live = c.get("/paypal/status").json().get("enabled", False)
    if not live:
        print("PayPal is off: approved payments end as 'allowed', not 'captured'.\n")

    def pid(ref: str) -> str | None:
        if ref.startswith("@"):
            return saved[ref[1:]]
        if ref == "paypal_sub:first":
            subs = [p for p in perms if p["source"] == "paypal_sub" and p["status"] == "active"]
            return subs[0]["id"] if subs else None
        # Two permissions can share an alias (the export and the live sandbox); the story
        # is about the one with history.
        found = [p for p in perms if p["merchant_alias"] == ref and p["status"] == "active"]
        found.sort(key=lambda p: -((p.get("profile") or {}).get("n_payments") or 0))
        return found[0]["id"] if found else None

    rows = []
    for i, s in enumerate(steps, 1):
        do, expect, actual, extra = s["do"], s.get("expect", ""), "", ""
        if do == "policy":
            r = c.put(f"{P}/payment-permissions/{pid(s['permission'])}/policy", json=s["policy"])
            actual = "set" if r.status_code == 200 else f"error {r.status_code}"
        elif do == "agent_permission":
            r = c.post(f"{P}/payment-permissions", json={"agent_id": s["agent_id"], "label": s["label"]})
            if r.status_code == 409:
                found = [p for p in perms if p["kind"] == "agent_authority" and p["merchant_alias"] == s["label"]]
                saved[s["save_as"]] = found[0]["id"]
            else:
                saved[s["save_as"]] = r.json()["data"]["id"]
            a = saved[s["save_as"]]
            c.put(f"{P}/payment-permissions/{a}/policy", json=s["policy"])
            d = dict(s["delegation"])
            exp = datetime.now(timezone.utc) + timedelta(days=d.pop("days", 7))
            c.post(f"{P}/payment-permissions/{a}/delegate",
                   json={"agent_id": s["agent_id"], "expires_at": exp.isoformat(), **d})
            actual = "created"
        elif do == "request":
            p = pid(s["permission"])
            if p is None:
                rows.append((i, s.get("say", do), expect, "SKIP (no such permission)", ""))
                print(f"{i:2}. {s.get('say', do)}: SKIP (no such permission)")
                continue
            body = {k: s[k] for k in ("amount", "is_recurring", "merchant_alias", "assessment") if k in s}
            hdr = {"X-Lupa-Agent": s["agent"]} if s.get("agent") else {}
            r = c.post(f"{P}/payment-permissions/{p}/requests", json={**body, "source": "scenario"}, headers=hdr)
            data = r.json().get("data") or {}
            dec = data.get("decision") or {}
            actual = dec.get("final", f"error {r.status_code}")
            extra = ", ".join(h["rule"] for h in dec.get("rule_hits", [])) + f" [{data.get('request', {}).get('state')}]"
            if s.get("save_as"):
                saved[s["save_as"]] = data["request"]["id"]
        elif do == "resolve":
            r = c.post(f"{P}/requests/{saved[s['request']]}/resolve", json={"action": s["action"]})
            actual = (r.json().get("data") or {}).get("request", {}).get("state", f"error {r.status_code}")
        elif do == "revoke":
            p = pid(s["permission"])
            if p is None:
                rows.append((i, s.get("say", do), expect, "SKIP (no live subscription; run make seed)", ""))
                print(f"{i:2}. {s.get('say', do)}: SKIP (no live subscription; run make seed)")
                continue
            r = c.post(f"{P}/payment-permissions/{p}/revoke")
            actual = (r.json().get("data") or {}).get("paypal_action", f"error {r.status_code}")
        if not live and expect == "captured":
            expect = "allowed"
        ok = "" if not expect else ("ok" if expect == actual else "MISMATCH")
        rows.append((i, s.get("say", do), expect, actual, f"{extra} {ok}".strip()))
        print(f"{i:2}. {s.get('say', do)}: {actual} {extra} {ok}")
        time.sleep(args.pause)

    bad = [r for r in rows if "MISMATCH" in r[4]]
    print(f"\n{len(rows)} steps, {len(bad)} mismatches")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
