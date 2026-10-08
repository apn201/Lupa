"""S0: the day-zero sandbox checks. Prints a pass/fail table.

    python scripts/spike.py            # all checks
    python scripts/spike.py --search   # only Transaction Search (rerun ~3 h after the first run)

Needs PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET and LUPA_TEST_CARD_NUMBER in .env.
Writes what it created to var/spike.json so a later run can look for it.
"""

from __future__ import annotations

import json
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lupa.config import settings_from_env  # noqa: E402
from lupa.paypal import orders, reporting, subscriptions  # noqa: E402
from lupa.paypal.client import PayPalClient, PayPalError  # noqa: E402

STATE = ROOT / "var" / "spike.json"
results: list[tuple[str, str, str]] = []


def check(name: str, fn):
    try:
        detail = fn()
        results.append((name, "PASS", str(detail or "")))
        return detail
    except PayPalError as exc:
        results.append((name, "FAIL", f"{exc.status} {exc.name} {exc.message} debug_id={exc.debug_id} "
                                      f"{json.dumps(exc.details)[:300]}"))
    except Exception as exc:  # noqa: BLE001 - the spike reports everything
        results.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))
    return None


def main() -> int:
    s = settings_from_env()
    if not s.paypal_enabled:
        print("Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env first.")
        return 2
    pp = PayPalClient(s)
    run = secrets.token_hex(4)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    only_search = "--search" in sys.argv

    check("1 token", lambda: "access token received" if pp.token() else None)

    if not only_search:
        # 2. product + plan + subscription + approve link
        prod = check("2a product", lambda: subscriptions.create_product(pp, f"Lupa spike {run}", f"spike-{run}-prod"))
        plan = prod and check("2b plan (monthly 3.14 EUR)", lambda: subscriptions.create_plan(
            pp, prod["id"], f"Spike monthly {run}", 314, "EUR", "MONTH", f"spike-{run}-plan"))
        sub = plan and check("2c subscription", lambda: subscriptions.create_subscription(
            pp, plan["id"], "Merchant Spike", f"spike-{run}-sub"))
        if sub:
            link = subscriptions.approve_link(sub)
            results.append(("2d approve link", "PASS" if link else "FAIL", link or "no approve link"))
            state["subscription_id"] = sub["id"]
            state["plan_id"] = plan["id"]

        # 3. card AUTHORIZE order -> authorize -> partial final capture -> status
        if not s.card_number:
            results.append(("3 card order", "FAIL", "LUPA_TEST_CARD_NUMBER is empty"))
        else:
            rid = f"spike-{run}-a"
            order = check("3a order AUTHORIZE with card source",
                          lambda: orders.create_authorize_order(pp, rid, 1890, "EUR", "Spike authorize"))
            auth = None
            if order:
                results.append(("3b order status", "PASS", order.get("status")))
                auth = orders.authorization_of(order)
                if auth is None:
                    # PAYER_ACTION_REQUIRED here is a 3DS contingency; the sandbox may still authorize.
                    o2 = check("3c authorize", lambda: orders.authorize(pp, order["id"], rid))
                    auth = o2 and orders.authorization_of(o2)
            if auth:
                cap = check("3d partial capture 15.00 final",
                            lambda: orders.capture(pp, auth["id"], 1500, "EUR", key=rid, final=True))
                if cap:
                    a = check("3e authorization status", lambda: orders.get_authorization(pp, auth["id"]))
                    if a:
                        results.append(("3f status is CAPTURED", "PASS" if a.get("status") in
                                        ("CAPTURED", "PARTIALLY_CAPTURED") else "FAIL", a.get("status")))
                state["captured_order"] = order["id"]

            # 4. second order, voided
            rid2 = f"spike-{run}-b"
            order2 = check("4a second order", lambda: orders.create_authorize_order(pp, rid2, 4500, "EUR", "Spike void"))
            auth2 = order2 and (orders.authorization_of(order2) or orders.authorization_of(
                orders.authorize(pp, order2["id"], rid2)))
            if auth2:
                check("4b void", lambda: orders.void(pp, auth2["id"], key=rid2))
                a2 = check("4c status", lambda: orders.get_authorization(pp, auth2["id"]))
                if a2:
                    results.append(("4d status is VOIDED", "PASS" if a2.get("status") == "VOIDED" else "FAIL",
                                    a2.get("status")))
        state["first_run"] = state.get("first_run") or datetime.now(timezone.utc).isoformat()

    # 5. Transaction Search reference types, and the delay
    now = datetime.now(timezone.utc)

    def search():
        rows = list(reporting.search(pp, now - timedelta(days=30), now))
        types: dict[str, int] = {}
        codes: dict[str, int] = {}
        for d in rows:
            info = d.get("transaction_info", {})
            types[info.get("paypal_reference_id_type") or "-"] = types.get(info.get("paypal_reference_id_type") or "-", 0) + 1
            codes[info.get("transaction_event_code") or "-"] = codes.get(info.get("transaction_event_code") or "-", 0) + 1
        return f"{len(rows)} rows, reference types {types}, event codes {codes}"

    if not check("5 transaction search", search) and results[-1][2].startswith("403"):
        results.append(("5c hint", "INFO", "Enable Transaction Search in the sandbox app's features; "
                                          "a new token can take hours to carry the scope."))
    if state.get("first_run"):
        hours = (now - datetime.fromisoformat(state["first_run"])).total_seconds() / 3600
        results.append(("5b hours since first run", "INFO", f"{hours:.1f}"))

    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))

    width = max(len(n) for n, *_ in results)
    print()
    for name, status, detail in results:
        print(f"{name:<{width}}  {status:4}  {detail}")
    fails = [r for r in results if r[1] == "FAIL"]
    print(f"\n{len(fails)} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
