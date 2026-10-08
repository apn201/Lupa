# Lupa

AI can act on your behalf without getting a blank cheque.

Lupa (Finnish: permit) is a working prototype of a **Consumer Payment Authorization API** for
agentic commerce, built on the PayPal sandbox. The first application is an automatic-payment
guard: find the standing permissions that let merchants and agents take money from you, see what
they do, and decide what they may do next.

| Marker | Meaning |
|---|---|
| ● PAYPAL | a live call to the PayPal sandbox, or data PayPal produced (rows say "from export" or "live sandbox") |
| ◇ PROPOSED | the API this project proposes; PayPal has no such endpoint today |
| ◆ AI | interpretation by a model |
| ■ POLICY | deterministic enforcement |

> Status: in development for the PayPal AI hackathon. This README is a working draft.

## What is real and what is proposed

Real (●), against the sandbox:

- Orders v2 with `intent: AUTHORIZE`, then authorize, capture (`final_capture`) and void
- Subscriptions v1: product, plan, subscription, get, transactions, cancel, suspend, pricing update
- Transaction Search, in 31-day windows, mapped by `paypal_reference_id_type` (`SUB`, `PAP`, `ODR`, `TXN`)
- Webhook receiver, with signature verification when `PAYPAL_WEBHOOK_ID` is set

The sandbox business account plays every merchant and a sandbox test card plays the consumer's
funding. A payment decision maps onto real authorization states: ALLOW authorizes and captures,
HOLD authorizes only and waits for you, BLOCK makes no call (or voids an existing authorization).

Proposed (◇): everything under `/proposed/v1/me`. PayPal has no buyer-side API for automatic
payments today, no buyer webhook, and no way for a consumer to give an agent bounded authority.
See [docs/api.md](docs/api.md).

## Run it

```bash
make install
cp .env.example .env    # PayPal and LLM keys are optional
make run                # http://127.0.0.1:8000
```

Without PayPal keys the engine and the API still work and every response says no PayPal call was
made. Without an LLM the engine treats every assessment as unavailable and fails closed.

With sandbox keys:

```bash
make spike        # S0 checks, prints a pass/fail table
make seed         # prints subscription approve links; approve as the sandbox personal account
make seed-check   # until all are ACTIVE
make sync         # after up to 3 hours (Transaction Search lag)
make demo         # replays data/scenarios/demo_main.json against the running server
```

## Give an agent bounded authority (MCP)

`lupa/mcp/server.py` exposes five tools to any MCP client: `list_payment_permissions`,
`inspect_payment_permission`, `request_payment`, `submit_decision`, `revoke_payment_permission`.
Each calls the proposed API over HTTP with the agent's id. The agent never sees PayPal credentials,
cannot approve its own payment, and can only revoke a permission delegated to it.

Claude Desktop, `claude_desktop_config.json` (with `make run` going):

```json
{
  "mcpServers": {
    "lupa": {
      "command": "/path/to/lupa/.venv/bin/python",
      "args": ["-m", "lupa.mcp.server"],
      "env": {"LUPA_API_URL": "http://127.0.0.1:8000", "LUPA_AGENT_ID": "shopping-agent"}
    }
  }
}
```

On Windows the command is `.venv\Scripts\python.exe`. Create the agent's permission and delegation
first in the UI (a permission's **Delegate** button) or with `make demo`.

## The authority rule

```
human intent ──▶ ◆ AI drafts, assesses ──▶ ■ policy engine decides ──▶ ● PayPal executes
```

The model proposes, code decides. `lupa/policy/engine.py` is pure Python with no IO and is the
only thing that can say ALLOW. An AI verdict can turn ALLOW into HOLD; it can never turn HOLD or
BLOCK into ALLOW. `tests/test_policy_engine.py` checks that on 1000 random cases on every push.

## What the AI does and does not do

It drafts a policy from one sentence, picks a limit from candidates code computed, assesses a
payment request with a verdict, a confidence and reason codes from a fixed list, and suggests what
an unclassifiable permission looks like. It never changes a limit, never approves a payment, never
calls PayPal, and its prose is never shown: the UI shows fixed sentences whose numbers come from
the ledger. An answer holding a number that is not in its input is dropped.

## Limits

- Sandbox only. The business account plays every merchant.
- Transaction Search lags up to three hours.
- Revoking a permission reconstructed from a real export cannot reach PayPal: there is no buyer API.
  Lupa says so and links to the PayPal settings page.
- The sample data in `data/` is synthetic until the anonymized export replaces it.
- Prior art: Google AP2 mandates, Privacy.com single-use cards, Coinbase agent session caps. What
  differs here: the PayPal rail, permissions reconstructed from payment history, and the authority
  invariant as a tested property.

## License

MIT. Security contact: see [SECURITY.md](SECURITY.md).
