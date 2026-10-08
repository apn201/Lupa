"""Seed the PayPal sandbox from data/seed_plan.yml (build spec 9).

    python scripts/seed_sandbox.py            # create product, plans, subscriptions, one-off orders
    python scripts/seed_sandbox.py --check    # show subscription status; rerun until all ACTIVE
    python scripts/seed_sandbox.py --price    # apply the planned price updates (after the first charge)
    python scripts/seed_sandbox.py --fresh    # new subscriptions and orders for a clean recording

Approve each printed link logged in as the sandbox PERSONAL account. There is
no API shortcut for buyer consent. State goes to var/seed.json; reruns reuse it.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lupa.config import settings_from_env  # noqa: E402
from lupa.ledger.db import Database  # noqa: E402
from lupa.ledger.models import Permission  # noqa: E402
from lupa.ledger.repo import Repo  # noqa: E402
from lupa.money import parse_amount  # noqa: E402
from lupa.paypal import orders, subscriptions  # noqa: E402
from lupa.paypal.client import PayPalClient, PayPalError  # noqa: E402

STATE = ROOT / "var" / "seed.json"


def main() -> int:
    s = settings_from_env()
    if not s.paypal_enabled:
        print("Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env first.")
        return 2
    pp = PayPalClient(s)
    plan = yaml.safe_load((ROOT / "data" / "seed_plan.yml").read_text(encoding="utf-8"))
    state = json.loads(STATE.read_text()) if STATE.exists() else {"plans": {}, "subs": {}, "orders": []}
    cur = plan["currency"]

    if "--check" in sys.argv:
        repo = Repo(Database(s.db_path))
        for alias, sid in state["subs"].items():
            sub = subscriptions.get(pp, sid)
            print(f"{alias:12} {sid:16} {sub.get('status')}")
            # Register the live subscription as a ● permission so it can be revoked for real.
            if sub.get("status") == "ACTIVE" and not repo.permission_by_ref("paypal_sub", sid):
                repo.save(Permission(source="paypal_sub", external_ref=sid, merchant_alias=alias,
                                     kind="fixed_recurring", currency=cur, marker="●"))
        return 0

    if "--price" in sys.argv:
        for p in plan["plans"]:
            if p.get("price_update") and p["alias"] in state["plans"]:
                subscriptions.update_pricing(pp, state["plans"][p["alias"]], parse_amount(p["price_update"]), cur,
                                             key=f"seed-price-{p['alias']}")
                print(f"{p['alias']}: price now {p['price_update']}")
        return 0

    if "--fresh" in sys.argv:
        # For the video: new subscriptions (and orders) on the same plans; old ones are left as they are.
        state.setdefault("abandoned_subs", []).extend(state["subs"].values())
        state["subs"] = {}
        state["orders"] = []
        state["round"] = state.get("round", 1) + 1
        # Sync only what this round creates; earlier rounds (and their test payments) stay out.
        # Five minutes of slack for clock skew between this machine and PayPal.
        since = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        Repo(Database(s.db_path)).set_meta("sync_since", since)
        print(f"Sync floor set to {since}")

    rnd = state.get("round", 1)
    if "product" not in state:
        state["product"] = subscriptions.create_product(pp, plan["product"], "seed-product")["id"]
    for p in plan["plans"]:
        alias = p["alias"]
        if alias not in state["plans"]:
            state["plans"][alias] = subscriptions.create_plan(
                pp, state["product"], p["name"], parse_amount(p["amount"]), cur, p["interval"],
                key=f"seed-plan-{alias}")["id"]
        if alias not in state["subs"]:
            key = f"seed-sub-{alias}" if rnd == 1 else f"seed-sub-{alias}-r{rnd}"
            sub = subscriptions.create_subscription(pp, state["plans"][alias], alias, key=key)
            state["subs"][alias] = sub["id"]
            print(f"{alias}: approve as the sandbox personal account:\n  {subscriptions.approve_link(sub)}")
    if not state["orders"]:
        for i, o in enumerate(plan["one_off_orders"]):
            try:
                key = f"seed-order2-{i}" if rnd == 1 else f"seed-order-r{rnd}-{i}"
                order = orders.create_authorize_order(pp, key, parse_amount(o["amount"]), cur,
                                                      o["alias"], intent="CAPTURE", merchant_alias=o["alias"])
                if order.get("status") != "COMPLETED":
                    order = orders.capture_order(pp, order["id"], key=key)
                state["orders"].append({"alias": o["alias"], "id": order["id"], "status": order.get("status")})
            except PayPalError as exc:
                print(f"order {i} failed: {exc}")
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))
    print(f"\nState in {STATE.relative_to(ROOT)}. Rerun with --check until every subscription is ACTIVE.")
    print("Then wait up to 3 hours and run `make sync`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
