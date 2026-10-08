# LUPA - build specification

This file is written for Claude Code. It describes what to build, in what order, and what "done" means for each step. Read it fully before writing code. Read `docs/paypal-api-reference.md` for the PayPal field names and enums; do not guess PayPal payloads.

Lupa (Finnish: permit) is a working prototype of a **Consumer Payment Authorization API** for agentic commerce, built on the PayPal sandbox, with an AI layer on top that shows what the API makes possible. The first application is an automatic-payment guard: discover, understand and protect the standing permissions that let merchants and agents take money from a consumer.

One sentence: AI can act on your behalf without getting a blank cheque.

## 0. Rules that govern every line of code

1. **The model proposes. Code decides.** No LLM output ever changes a limit, approves a payment, or calls PayPal. The policy engine is pure Python with no network access, and it is the only thing that can say ALLOW.
2. **AI cannot expand authority.** An AI verdict can turn ALLOW into HOLD. It can never turn HOLD or BLOCK into ALLOW. There is a test for this and it must never be skipped.
3. **Every number shown to the user comes from the ledger.** Any AI text containing a number not present in the data it was given is dropped and replaced by the fixed sentence for its reason code. (Same rule as `virta/guardrails.py`.)
4. **Real and proposed are labelled, always.** Four markers in the API responses and the UI: `●` PAYPAL (live sandbox call), `◇` PROPOSED (the API this project proposes), `◆` AI (interpretation), `■` POLICY (deterministic enforcement). Nothing proposed is ever presented as an existing PayPal endpoint.
5. **Sandbox only. No real money, no real names.** Real merchant names, emails, account IDs and the real export never enter the repo, the hosted demo or the video. `private/` is gitignored and `tools/check_secrets.py` runs before any push.
6. **Fail closed.** PayPal down, LLM down, malformed JSON, missing policy: the answer is HOLD, never ALLOW.
7. **Idempotent PayPal calls.** Every order, capture and void sends `PayPal-Request-Id` set to the Lupa request or decision id. Retrying never double-charges.
8. **No chatbot.** The user never talks to a model in a chat window. They type one sentence of intent into a field, or click. The model is invisible.

## 1. Stack

- Python 3.12, FastAPI, uvicorn, pydantic v2, SQLite via `sqlite3` with a thin repository layer (no ORM needed), `httpx` for PayPal, `pytest` + `respx` for tests.
- LLM: any OpenAI-compatible chat endpoint. Config by env: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`. Port the client from `Apps\Virta\virta\nebius_client.py` (handles the reasoning-model case where `message.content` is empty and text sits in `reasoning_content`). Also port `cost_control.py` (call and spend ceiling, fails closed) and `guardrails.py` (number check).
- Frontend: one static page, `web/index.html` + `web/app.js` + `web/style.css`, served by FastAPI. No build step. Vanilla JS, `fetch`. Phone width must work.
- MCP server (stretch): Python `mcp` package, FastMCP, tools call the local proposed API over HTTP. Never PayPal directly.
- Hosting: one Docker image, `uvicorn lupa.api.app:app`. Deployable to Fly.io, Railway or a Hetzner box. SQLite file on a volume.
- Secrets scan: copy `tools/check_secrets.py` and `tools/check_publishable.py` from `Apps\Whyf`.
- License: MIT (file at repo root; it must show in the GitHub About section).

## 2. Repository layout

```
lupa/
  README.md            how to run, what is real and what is proposed, demo script
  LICENSE              MIT
  SECURITY.md          what the sandbox keys can and cannot do, how to report
  .env.example
  .gitignore           private/, *.db, .env
  Makefile             run, test, seed, sync, check, demo
  pyproject.toml
  Dockerfile
  docs/
    LUPA_BUILD.md      this file
    paypal-api-reference.md
    api.md             the proposed API, generated from the OpenAPI that FastAPI emits
  lupa/
    config.py          env, markers, thresholds
    paypal/
      client.py        oauth token cache, request(), idempotency header, retries, error type
      orders.py        create_authorize_order, authorize, capture, void, get_authorization
      subscriptions.py create_product, create_plan, create_subscription, get, list_transactions, cancel, suspend, update_pricing
      reporting.py     transaction search with date windowing and paging
      webhooks.py      receiver, signature verify (optional), event to ledger
    importers/
      activity_csv.py  PayPal Activity Download CSV (the consumer export format), both the English and Finnish header variants
      sandbox_sync.py  pulls Transaction Search + subscriptions into the ledger
    ledger/
      db.py            schema, migrations, connection
      repo.py          typed CRUD per table
      models.py        pydantic models for every row
    reconstruct/
      permissions.py   deterministic grouping of charges into permissions
      profile.py       behaviour statistics per permission
      classify.py      deterministic kind + attention flags; AI only for the ambiguous residue
    policy/
      engine.py        pure functions: evaluate(request, permission, policy, delegation, ai_verdict) -> Decision
      rules.py         the rule table and reason codes
      sentences.py     fixed sentences per reason code, number slots filled from the ledger
    ai/
      llm.py           ported client + cost control
      intent_to_policy.py
      suggest_limit.py
      assess_payment.py
      explain_permission.py
      prompts/         one .md per task, versioned
      guard.py         number check, JSON validation, fallback
    api/
      app.py           FastAPI app, static mount, markers middleware
      proposed.py      ◇ /proposed/v1/me/...
      paypal_routes.py ● /paypal/...
      ui_routes.py     screens' data endpoints
      schemas.py       request/response models
    workers/
      expiry.py        voids held authorizations past their hold window
      sync.py          periodic sandbox sync
    mcp/
      server.py        stretch
  web/
    index.html app.js style.css
  data/
    sample_activity_anonymized.csv   six months, anonymized, committed
    merchants.yml                    alias -> category for the sample
    seed_plan.yml                    what seed_sandbox.py creates
    scenarios/                       demo payment requests as JSON
  scripts/
    anonymize_export.py  real CSV in private/ -> data/sample_activity_anonymized.csv
    seed_sandbox.py      creates products, plans, subscriptions, a few orders; prints approve links
    demo.py              replays data/scenarios against the running API
    spike.py             the day-zero sandbox checks, prints a pass/fail table
  tests/
    test_policy_engine.py   includes the authority invariant
    test_reconstruct.py     expected counts on the sample CSV
    test_guard.py
    test_api.py             respx-mocked PayPal
    test_live_sandbox.py    skipped unless LUPA_LIVE=1
```

## 3. Data model (SQLite)

All money as integer minor units plus `currency` (EUR cents). All times UTC ISO 8601 strings. IDs are prefixed: `pp_` permission, `pol_` policy, `dlg_` delegation, `req_` payment request, `dec_` decision, `evt_` event.

**permission**
- `id`, `source` (`paypal_sub` | `paypal_pap` | `paypal_order` | `import_csv` | `lupa_delegation`), `external_ref` (I-xxx, B-xxx, order id, or hash), `merchant_alias` (Merchant A...), `merchant_category` (digital service, travel provider, software, media, retailer, cloud, utility, marketplace, individual), `kind` (`fixed_recurring` | `variable_recurring` | `one_time_authority` | `agent_authority` | `unknown`), `status` (`active` | `dormant` | `suspended` | `revoked` | `expired`), `first_seen`, `last_payment_at`, `last_amount`, `currency`, `created_at`, `policy_id` nullable, `delegation_id` nullable, `attention` (JSON list of flag codes), `marker` (`●` or `◇`, where the permission came from: ● for data PayPal produced, either a live sandbox call or PayPal's own activity export; ◇ for a permission that exists only in Lupa. The UI also labels every row "from export", "live sandbox" or "agent authority in Lupa", so an export row is never mistaken for a live call.)

**profile** (one per permission, recomputed on sync)
- `permission_id`, `n_payments`, `amount_min`, `amount_max`, `amount_median`, `amount_p95`, `interval_days_median`, `interval_days_mad`, `months_since_last`, `amount_trend` (last vs median, percent), `computed_at`

**payment** (one per charge seen)
- `id`, `permission_id`, `paypal_txn_id` nullable, `amount`, `currency`, `at`, `event_code` (T0002 etc or CSV type), `status` (S/P/D/V), `source` (`paypal_search` | `paypal_sub_txn` | `import_csv` | `lupa_capture`)

**policy**
- `id`, `permission_id` nullable (null = account default), `max_amount`, `currency`, `recurring` (`allow` | `require_approval` | `block`), `amount_increase` (`allow` | `require_approval` | `block`), `increase_tolerance_pct` (default 20), `new_merchant` (`allow` | `require_approval` | `block`), `max_per_month` nullable, `expires_at` nullable, `created_by` (`human` | `ai_draft_accepted`), `intent_text` nullable, `created_at`

**delegation**
- `id`, `permission_id`, `agent_id`, `authority` (`propose` | `approve`), `max_amount`, `recurring_allowed` bool, `amount_change_pct`, `min_confidence` (default 0.95), `expires_at`, `revoked_at` nullable

**payment_request**
- `id`, `permission_id`, `amount`, `currency`, `merchant_alias`, `is_recurring` bool, `requested_at`, `source` (`webhook` | `scenario` | `agent` | `api`), `agent_id` nullable, `paypal_order_id` nullable, `paypal_authorization_id` nullable, `state` (`received` | `allowed` | `held` | `blocked` | `captured` | `voided` | `expired`), `hold_until` nullable

**decision**
- `id`, `request_id`, `ai_verdict` (`approve` | `escalate` | `reject` | null), `ai_confidence` float nullable, `ai_reason_codes` JSON, `policy_verdict` (`ALLOW` | `HOLD` | `BLOCK`), `rule_hits` JSON (rule ids with the values compared), `final` (`ALLOW` | `HOLD` | `BLOCK`), `resolved_by` (`policy` | `human` | `expiry`), `resolved_at`, `paypal_action` (`captured` | `voided` | `none`), `sentences` JSON (the fixed sentences shown)

**event** (append-only audit)
- `id`, `at`, `kind`, `ref_id`, `marker`, `payload` JSON

## 4. Reconstructing permissions (deterministic)

Input: payments from the CSV importer and from sandbox sync. Output: permissions with profiles and attention flags. No LLM in this module.

Grouping key, in order of preference:
1. Subscription id (`paypal_reference_id_type = SUB`, or `I-...` from the Subscriptions API).
2. Pre-approved payment id (`PAP`, or CSV `Reference Txn ID` starting `B-`).
3. Otherwise the counterparty (`paypal_account_id`, or CSV `To Email Address` / `Name`) when that counterparty has two or more payments.
4. A single payment with no reference and no repeat is a `one_time_authority` only if the account's known permission list says the counterparty still holds an active agreement (the seeded `data/merchants.yml` carries that for the sample). Otherwise it is a plain purchase and not a permission.

Rows to ignore: CSV types "General Card Deposit", "General Currency Conversion", "General Authorization", "Void of Authorization", and anything with `Balance Impact = Credit`; event codes T07xx, T03xx, T2000, T01xx. Keep refunds (T1107) as negative payments attached to the permission.

Classification (`classify.py`), deterministic:
- `fixed_recurring`: n >= 3, interval median in {28..31, 7, 365 +-5}, amount spread (max-min)/median < 5 percent.
- `variable_recurring`: n >= 3, regular interval, amount spread >= 5 percent.
- `one_time_authority`: n <= 2 and an active agreement exists.
- `unknown`: anything else. Only `unknown` is sent to `explain_permission.py` for an AI opinion, and the opinion is stored as a suggestion, never as the kind.

Attention flags (fixed codes, each with a fixed sentence):
- `DORMANT_6M`, `DORMANT_12M`: months_since_last >= 6 / 12 with status active.
- `AMOUNT_JUMP`: last_amount > 1.5 x median.
- `INTERVAL_BREAK`: a gap > 2 x interval median followed by a new charge.
- `ONE_OFF_STILL_ACTIVE`: kind one_time_authority, active.
- `NO_HISTORY`: active permission with zero payments in the window.
- `NEW_LAST_30D`: first_seen within 30 days.

Expected counts on `data/sample_activity_anonymized.csv` are fixed in `tests/test_reconstruct.py` once the anonymized file exists. Write the test from the real numbers, then freeze.

## 5. The proposed API (◇)

Prefix `/proposed/v1/me`. Every response carries `"marker": "◇"` and `"proposed": true`. Where a call triggers a real PayPal call, the response also carries `"paypal": {"marker": "●", "calls": [...]}` listing what was sent and the PayPal ids returned.

| Method and path | Does |
|---|---|
| `GET /payment-permissions?status=&kind=&attention=` | list, with profile summary and attention flags |
| `POST /payment-permissions` | ◇ create an `agent_authority` permission (source `lupa_delegation`) for an agent; delegate it next. Agents get their own permission rather than borrowing a merchant's history. |
| `GET /payment-permissions/{id}` | full record: profile, payments, policy, delegation, last decisions |
| `POST /payment-permissions/{id}/revoke` | `paypal_sub`: calls `POST /v1/billing/subscriptions/{I}/cancel` (●) then marks revoked. `import_csv` and `paypal_pap`: marks revoked locally and returns `paypal_action: "not_available_to_buyer"` plus the buyer's own PayPal settings deep link. Never pretend. |
| `POST /payment-permissions/{id}/suspend` | same shape with `suspend` |
| `PUT /payment-permissions/{id}/policy` | set a policy (validated, stored, effective at once) |
| `GET /policies/default`, `PUT /policies/default` | account default policy |
| `POST /intent` | body `{text}`. ◆ AI drafts a policy. Returns the draft plus the fixed-sentence explanation. Nothing is stored until `PUT .../policy` is called with the draft. |
| `GET /payment-permissions/{id}/suggested-limit` | ◆ AI picks and explains a limit from code-computed candidates (section 7) |
| `POST /payment-permissions/{id}/delegate` | create a delegation for an agent |
| `DELETE /delegations/{id}` | revoke it |
| `POST /payment-permissions/{id}/requests` | a payment request arrives. Runs AI assessment, then the engine. Returns the decision. If `execute: true` and ALLOW: creates an AUTHORIZE order and captures (●). HOLD: authorizes only and sets `hold_until`. BLOCK: no PayPal call, or void if an authorization already exists. |
| `POST /requests/{id}/decision` | an agent submits `{decision, confidence, reason}`. Stored as the AI verdict and re-evaluated by the engine. The engine still decides. |
| `POST /requests/{id}/resolve` | human `{action: approve | reject}` on a held request. approve -> capture (●), reject -> void (●). |
| `GET /requests?state=held` | the approval queue |
| `GET /events?since=` | audit trail |

Error shape: `{"error": {"code": "...", "message": "..."}}`. Codes: `permission_not_found`, `policy_invalid`, `delegation_expired`, `paypal_error` (with PayPal's `name` and `debug_id`), `ai_unavailable` (and the request is HELD, never dropped).

FastAPI generates the OpenAPI; export it to `docs/api.md` in the Makefile. That document is part of the submission.

## 6. The policy engine (■)

`policy/engine.py` exposes one function:

```python
def evaluate(req: PaymentRequest, perm: Permission, prof: Profile | None,
             pol: Policy, dlg: Delegation | None, ai: AiVerdict | None) -> Decision
```

Pure. No IO. Deterministic. Returns the decision with `rule_hits` naming every rule that fired and the values it compared.

Rule order (first BLOCK wins, then HOLD, else ALLOW):

| id | condition | verdict |
|---|---|---|
| R01 | permission status revoked, expired or suspended | BLOCK |
| R02 | policy expired | BLOCK |
| R03 | currency mismatch with policy | BLOCK |
| R04 | recurring and policy.recurring == block, or merchant not the permission's merchant and new_merchant == block (any amount: "never recurring" means never) | BLOCK |
| R10 | amount > max_amount | HOLD |
| R11 | is_recurring and policy.recurring == require_approval | HOLD |
| R12 | profile exists and amount > median x (1 + tolerance) and amount_increase == require_approval | HOLD |
| R13 | profile exists and amount > median x (1 + tolerance) and amount_increase == block | BLOCK |
| R14 | merchant not the permission's merchant and new_merchant == require_approval | HOLD |
| R15 | max_per_month set and month total + amount > max_per_month | HOLD |
| R16 | permission has attention flag DORMANT_12M or NO_HISTORY | HOLD |
| R20 | delegation present: agent authority == propose | HOLD |
| R21 | delegation present: amount > delegation.max_amount, or recurring and not recurring_allowed, or change > amount_change_pct, or delegation expired | HOLD |
| R30 | ai verdict is reject | HOLD (a model cannot block, a human can) |
| R31 | ai verdict is escalate, or confidence < delegation.min_confidence (default 0.95 when no delegation) | HOLD |
| R32 | ai is null (unavailable) | HOLD unless amount <= max_amount and policy.recurring == allow and no other rule fired; then ALLOW with reason `AI_UNAVAILABLE_WITHIN_HARD_LIMITS` |

ALLOW only when no rule fired. Note R30 and R31 only add holds. There is no rule that uses the AI verdict to remove a hold. Also: an agent request on a permission where that agent holds no delegation fires R21 (`no_delegation`).

`tests/test_policy_engine.py` has a property test over 1000 random cases. The baseline is the policy verdict from R01-R21, which never reads the AI: for every AI verdict, `final` is at least as strict as that verdict; if it is HOLD or BLOCK, no AI verdict gives ALLOW; a BLOCK stays BLOCK. (The first draft compared against `ai=None`, but R32 makes `ai=None` stricter than an approving AI on purpose, so that comparison contradicted R32.)

Sentences: each rule id and reason code maps to one fixed English sentence in `policy/sentences.py` with slots for ledger numbers, e.g. `R10: "Above your limit of {max_amount} {currency}."`, `AMOUNT_JUMP: "{amount} is {ratio}x the usual {median}."`. The UI shows these. The model's own prose is never shown.

## 7. The AI layer (◆)

All four tasks return JSON, validated with pydantic. On any failure: log, return `None`, and the caller falls back (engine treats `ai=None`). All calls go through `cost_control` (per-hour cap, daily spend ceiling, fails closed) and `guard.py` (number check).

1. **intent_to_policy(text, context)** -> `PolicyDraft` with the policy fields plus `reason_codes[]` from a fixed vocabulary (`INTENT_THRESHOLD`, `INTENT_RECURRING_APPROVAL`, `INTENT_NO_NEW_MERCHANTS`, `INTENT_AMBIGUOUS`). Context: the account default policy and currency. The draft is shown with fixed sentences and the user confirms it. Test inputs: "Anything recurring over 20 euros needs me." "Handle my electricity automatically but ask if it jumps." "Let this shopping agent buy things but never start anything recurring."

2. **suggest_limit(profile)**: code computes candidates first: `ceil5(max x 1.15)`, `ceil5(p95 x 1.25)`, `ceil5(median x 1.5)`. The model picks one and names a reason code (`LIMIT_SEASONAL_ROOM`, `LIMIT_TIGHT`, `LIMIT_STABLE`). Code clamps to `[max, 2 x max]`. Both the candidates and the pick are stored. The sentence shown: "Your recent payments range from {min} to {max}. {limit} leaves room for normal variation and sends larger ones to you."

3. **assess_payment(request, profile, policy)** -> `{verdict: approve|escalate|reject, confidence: 0..1, reason_codes[]}`. Vocabulary: `AMOUNT_IN_RANGE`, `AMOUNT_ABOVE_RANGE`, `AMOUNT_RATIO` (with a code-computed ratio attached by the caller), `MERCHANT_MATCH`, `MERCHANT_UNKNOWN`, `INTERVAL_MATCH`, `INTERVAL_EARLY`, `FIRST_CHARGE`, `DORMANT_REACTIVATED`. The caller attaches the numbers from the profile; the model only picks codes and a confidence. The prompt gets the profile as a small table and the request, nothing else.

4. **explain_permission(profile, payments)**: only for kind `unknown`. Returns a suggested kind and one reason code. Stored as `suggestion`, displayed as "Looks like {kind}" with the ◆ marker.

Prompts live in `lupa/ai/prompts/*.md` and each has a version line. Record the model name and prompt version on every decision.

## 8. Real PayPal integration (●)

Everything PayPal goes through `paypal/client.py`: token cache with refresh on `expires_in`, `request(method, path, json, idempotency_key)` that sets `PayPal-Request-Id`, raises `PayPalError(status, name, debug_id, details)`, retries once on 5xx, never on 4xx.

Execution mapping for a payment request:
- ALLOW: `POST /v2/checkout/orders` (`intent: AUTHORIZE`, `custom_id: req id`, card payment source from `.env` test card) -> `POST .../authorize` -> `POST /v2/payments/authorizations/{id}/capture` with `final_capture: true`. State `captured`.
- HOLD: create and authorize only. State `held`, `hold_until = now + policy hold window (default 72 h, inside PayPal's 3-day honor period)`. Resolution: approve -> capture, reject -> void. Expiry worker voids anything past `hold_until`. State `voided` or `expired`.
- BLOCK: no PayPal call. If an authorization exists for this request (re-evaluation), void it.
- Revoke on a `paypal_sub` permission: `POST /v1/billing/subscriptions/{I}/cancel`. Suspend: `/suspend`.
- Sync: `GET /v1/reporting/transactions` in 31-day windows for the last 90 days with `fields=transaction_info,payer_info,cart_info`, plus `GET /v1/billing/subscriptions/{id}` and `/transactions` for every known subscription id. Upsert into `payment`, then rebuild permissions and profiles.
- Webhooks: `POST /paypal/webhook` stores the event and triggers a sync of the referenced resource. Signature verification on when `PAYPAL_WEBHOOK_ID` is set. Without a public URL, `scripts/demo.py` posts recorded event bodies to the same endpoint.

**Spike result (Oct 8):** the card source works without a browser. The order comes back `PAYER_ACTION_REQUIRED` (a 3-D Secure contingency, even with `attributes.verification.method: SCA_WHEN_REQUIRED`), but `POST .../authorize` succeeds anyway, then capture or void. No fallback was needed. Transaction Search needs the feature enabled on the app, and the token can take hours to carry the scope; `sync` continues with the subscription endpoints when search is unavailable.

If the spike shows card payment sources need a feature the sandbox app cannot enable, fallback in this order: (a) `payment_source.paypal` with `vault_id` after one approval in the sandbox buyer login, (b) pre-approve a batch of AUTHORIZE orders through the approve link before the demo and let the API consume them, (c) wallet approve link per request, shown in the UI as a one-click step. Document which one shipped.

The sandbox business account plays every merchant and the test card plays the consumer's funding. Say so in the README under "What is real".

## 9. Sandbox seeding

`scripts/seed_sandbox.py`, driven by `data/seed_plan.yml`:
- 1 product, 4 plans (EUR): monthly 3.14, monthly 8.49, monthly 18.49, yearly 75.00. One plan gets a pricing-scheme update after the first charge, for the AMOUNT_JUMP story.
- 4 subscriptions, one per plan, `custom_id` set to the sample merchant alias. The script prints the approve links; the maintainer opens each, logged in as the sandbox personal account. Rerun the script with `--check` until all are `ACTIVE`.
- 6 one-off orders with `intent: CAPTURE` to Merchant aliases for one-time history.
- Wait up to 3 hours, then `make sync`. Record what `paypal_reference_id_type` values came back and fix the mapping in `reporting.py` if they differ from the expected SUB and ODR.

The anonymized CSV gives the six-month pattern on day one; the sandbox gives live permissions that can be revoked and charged. The UI shows both, each with its marker. Judges running the hosted demo see a pre-seeded sandbox and need no PayPal login.

## 10. Anonymization

`scripts/anonymize_export.py private/Download.CSV data/sample_activity_anonymized.csv`:
- Merchant names -> `Merchant A..Z` in order of first appearance, category from a mapping file in `private/` (never committed), fallback "digital service".
- Emails, names, addresses, phone, subject, note, item titles: dropped or replaced with the category.
- Transaction ids and `B-` references: HMAC-SHA256 with a key from `private/`, truncated to 17 chars with the original prefix, so grouping survives and the originals cannot be recovered.
- Dates shifted by one constant random offset of 0-13 days (keeps intervals). Amounts and currencies untouched.
- Output header in English regardless of the source locale. Finnish headers (`Päiväys`, `Kellonaika`, `Kuvaus`, `Brutto`, `Netto`, `Saldo`, `Tapahtuman tunniste`, `Viitetapahtuman tunniste`) are mapped in `importers/activity_csv.py`.
- Decimal commas and the Unicode minus sign (U+2212) in the export must be handled: `"−3,14"` -> `-314` cents.

## 11. UI (one page, four screens)

Served at `/`. Phone width first. Markers rendered as small chips with a legend in the footer.

1. **Permissions.** Header: "N companies can take money from you. M have not in over a year." Then the list, grouped by status, each row: alias, category, kind, last amount, last date, attention chips, marker. Tap a row for the detail panel with the profile numbers, the payments, the policy, "Suggest a limit", "Set policy", "Delegate", "Revoke" (with the honest note when revoke cannot reach PayPal).
2. **Intent.** One text field, one button. Shows the ◆ draft as fixed sentences and the ■ policy fields, with "Apply" and "Discard". Nothing else.
3. **Queue.** Held requests with amount, merchant, the ■ sentences, the ◆ confidence, "Approve" and "Reject". Approving shows the ● capture id. Rejecting shows the ● void.
4. **Trace.** The audit trail as a vertical timeline with the four markers, newest first. This is the screen the video uses to reveal the architecture: every step labelled.

No charts. No dashboard. No avatar.

## 12. MCP server (stretch, slice S8)

`lupa/mcp/server.py` with FastMCP. Tools: `list_payment_permissions`, `inspect_payment_permission`, `request_payment(permission_id, amount, currency, purpose)`, `submit_decision(request_id, decision, confidence, reason)`, `revoke_payment_permission`. Every tool calls the local proposed API over HTTP with an agent id header. The agent never sees PayPal credentials. An agent can revoke only a permission delegated to it, and submit a decision only on its own requests: cancelling a live subscription is real, so a misled agent must not be able to cancel the person's agreements. Built on `mcp` 2.x (`MCPServer`, formerly FastMCP). README shows a Claude Desktop config block. The demo scenario "agent asks to pay 89.90 and is held" runs through this when it exists; otherwise through `scripts/demo.py`.

## 13. Demo scenarios (`data/scenarios/*.json`)

Each file: a permission alias, a list of requests with amount, recurring flag, merchant, and the expected final verdict. `scripts/demo.py` posts them in order with a pause and prints a table of expected vs actual. The video follows `demo_main.json`:
1. Merchant C, 18.90, recurring, expected ALLOW (within limit, in range).
2. Merchant C, 89.90, recurring, expected HOLD (R10, AMOUNT_RATIO).
3. Human approves 2 -> capture.
4. Merchant X (unknown), 12.00, expected HOLD (R14).
5. Agent `shopping-agent` with delegation max 80, requests 120.00, expected HOLD (R21).
6. Agent requests 45.00 with confidence 0.97, expected ALLOW -> capture.
7. Revoke Merchant F (paypal_sub) -> ● cancel, then a request against it, expected BLOCK (R01).

## 14. Slices

The deadline is Nov 12 2026, 22:00 Helsinki.

| # | Slice | Done when | When |
|---|---|---|---|
| S0 | Spike: `scripts/spike.py`. Token; product + plan + subscription + approve link; card AUTHORIZE order -> authorize -> partial capture (final) -> status; a second order voided; Transaction Search returns the rows with reference types; note the delay. Prints a pass/fail table. | Table has no FAIL rows, or each FAIL has a chosen fallback written into this file section 8. | before Oct 12 or Oct 26 |
| S1 | Repo skeleton, config, PayPal client, ledger schema, CSV importer, anonymizer, sample CSV committed, secrets check in Makefile. | `make test` green; `make import` loads the sample; `check_secrets` passes. | Nov 1 |
| S2 | Reconstruct + profile + classify. Expected counts frozen in tests. | Sample yields the permission list with attention flags; counts match the test. | Nov 2 |
| S3 | Policy engine + rules + sentences + authority invariant test. | 100 percent branch coverage on `engine.py`; invariant property test passes 1000 cases. | Nov 3 |
| S4 | Proposed API: permissions, policy, delegate, requests, decision, resolve, queue, events. Error shape. OpenAPI exported. | `test_api.py` green with respx; `docs/api.md` generated. | Nov 4-5 |
| S5 | Real PayPal: orders authorize/capture/void, subscriptions cancel/suspend, sync, expiry worker, webhook receiver. Seed script run; sandbox populated. | Live test (`LUPA_LIVE=1`) runs the main scenario against the sandbox end to end; capture and void ids visible in Trace. | Nov 5-6 |
| S6 | AI layer: four tasks, prompts, guard, cost control. | Each task has a fixture test with a recorded response; guard drops a planted bad number; `ai=None` path verified. | Nov 7 |
| S7 | UI, four screens, markers, phone width. | Demo scenario runs from the UI; screenshots in README. | Nov 8-9 |
| S8 | MCP server (stretch). | Claude Desktop lists the five tools; scenario step 5 runs through MCP. | Nov 9 if S7 done |
| S9 | README (what is real, what is proposed, run instructions, hosted URL), SECURITY.md, Dockerfile, deploy, text description, tools list. | A clean clone runs with `cp .env.example .env && make run` and the hosted URL serves the seeded demo. | Nov 10 |
| S10 | Video under 3 minutes, no trademarks, no music without a license. Submit. | Uploaded public on YouTube; Devpost form complete. | Nov 11 |

Cut order if time runs out: S8, then the webhook receiver (polling stays), then the Intent screen (policies set by form), then `explain_permission`. Never cut: the engine and its invariant test, authorize/capture/void against the sandbox, the markers, the sample data, the video.

## 15. README outline

1. One sentence and the four-marker legend.
2. What is real (sandbox calls, list them) and what is proposed (the ◇ endpoints) and why PayPal has no buyer-side equivalent today.
3. Run it: `.env` keys, `make seed`, approve links, `make sync`, `make run`, `make demo`.
4. The architecture picture (human intent -> AI -> policy engine -> PayPal) and the authority rule.
5. API summary with a link to `docs/api.md`.
6. What the AI does and does not do.
7. Limits: sandbox only; the business account plays every merchant; the three-hour reporting lag; `revoke` cannot reach a real buyer's agreements; prior art (Google AP2 mandates, Privacy.com single-use cards) and what differs here (PayPal rail, permissions reconstructed from history, authority invariant).
8. License, security contact.

## 16. Demo video script (under 3 minutes)

- 0:00-0:20 Permissions screen on the sample. "N companies can take money from me. M have not in a year." One line: permissions today are designed for humans; agents will need them too.
- 0:20-0:45 ● Sync from the sandbox. Counter: transactions imported, permissions reconstructed.
- 0:45-1:15 ◆ attention flags appear. No chat, just results.
- 1:15-1:40 Intent: "Anything recurring over 20 euros needs me." Draft shown, Apply. ■ POLICY ACTIVE.
- 1:40-2:05 Request 18.90 -> ALLOW -> ● captured. Request 89.90 -> HOLD.
- 2:05-2:30 Queue: the held request with its sentences and confidence. Approve -> ● capture id appears. The agent could not do this on its own.
- 2:30-2:50 Trace screen: the four markers down the timeline. One real API call shown: `POST /proposed/v1/me/payment-permissions/{id}/requests`.
- 2:50-3:00 "PayPal knows how to move your money. We built the layer that tells agents what they're allowed to do with it."

No merchant names on screen. No PayPal logo beyond what the sandbox pages show if they appear at all; prefer not to show them.

## 17. Definition of done for the whole entry

- A judge can clone, set two env values, run `make run` and see the seeded demo, or open the hosted URL.
- Every ● call in the Trace has a PayPal id that exists in the sandbox.
- Every ◇ response says it is proposed.
- The authority invariant test is in CI (GitHub Actions, `make test` on push).
- `check_secrets.py` passes on the full history.
- Video, repo, description and tools list submitted by Nov 11.
