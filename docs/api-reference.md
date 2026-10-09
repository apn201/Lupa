# Consumer Payment Authorization API (proposed) v1

This is a proposal. PayPal has no such API today. The prototype in this repository implements
it on top of the PayPal sandbox, so every endpoint below can be called on the hosted demo at
`https://lupa.helppox.com` or on a local copy (`make run`, `http://127.0.0.1:8000`).

The API is for the buyer's side of a payment. PayPal's REST APIs let a merchant create orders,
subscriptions and billing agreements. Nothing lets the buyer, or software acting for the buyer,
list those standing permissions, set limits on them, hand bounded authority to an AI agent and
approve what falls outside it. These endpoints do that. The web portal and the MCP server in
this repository are two clients of this API, nothing more.

Interactive version (Swagger UI): `https://lupa.helppox.com/docs`. Machine readable:
[openapi.json](openapi.json).

## Contents

- [Overview](#overview)
- [Payment permissions](#payment-permissions)
- [Policies](#policies)
- [Delegations](#delegations)
- [Payment requests](#payment-requests)
- [Events](#events)
- [Objects](#objects)
- [Policy rules](#policy-rules)
- [Errors](#errors)
- [Sandbox and demo routes](#sandbox-and-demo-routes)
- [MCP tools](#mcp-tools)

## Overview

### Base URL

| Environment | URL |
|---|---|
| Hosted demo | `https://lupa.helppox.com/proposed/v1/me` |
| Local | `http://127.0.0.1:8000/proposed/v1/me` |

`/me` is the signed-in buyer. In a real deployment this would come from a buyer access token.
The prototype has one buyer and no authentication.

### Authentication

Not implemented in the prototype. For a production version the proposal is OAuth 2.0 like the
rest of PayPal's APIs, with buyer-consented scopes:

| Scope (proposed) | Allows |
|---|---|
| `payment-permissions.read` | list and read permissions, requests and events |
| `payment-permissions.manage` | policies, delegations, revoke, suspend |
| `payment-requests.create` | create payment requests (merchants, agents) |
| `payment-requests.resolve` | approve or reject held requests (the buyer only) |

An agent would get only `payment-permissions.read` and `payment-requests.create`. It could never
hold `payment-requests.resolve`, so it can not approve its own payment.

### Headers

| Header | Description |
|---|---|
| `Content-Type: application/json` | Required on every request with a body. |
| `X-Lupa-Agent` | The calling agent's id, for example `shopping-agent`. Set by agents only. A request with this header is checked against that agent's delegation. In the prototype it is not authenticated. |

### Amounts

Every amount is an integer in minor units: `1890` is 18.90 EUR. Currency is an ISO 4217 code.
The MCP server converts to and from decimal strings for agents.

### Response envelope

Every response is wrapped in the same envelope:

```json
{
  "marker": "◇",
  "proposed": true,
  "data": { },
  "paypal": {
    "marker": "●",
    "calls": [
      {
        "method": "POST",
        "path": "/v2/payments/authorizations/41E81931L54327411/capture",
        "status": 201,
        "paypal_id": "6RB16247DX7104402",
        "debug_id": "f41c25b1e3a2c",
        "request_id": "req_b7918549dd5f",
        "marker": "●",
        "extra": {}
      }
    ]
  }
}
```

| Field | Type | Description |
|---|---|---|
| `marker` | string | Always `◇`: the response comes from the proposed API. |
| `proposed` | boolean | Always `true`. |
| `data` | object or array | The result. |
| `paypal` | object or null | The real PayPal sandbox calls this request caused, in order. `null` when there were none. `request_id` is the `PayPal-Request-Id` idempotency key that was sent. |

### Markers

Each object says where it came from, so a client can show it:

| Marker | Meaning |
|---|---|
| `●` | PayPal: a real sandbox call, or data PayPal produced |
| `◇` | The proposed API |
| `◆` | AI interpretation |
| `■` | Deterministic policy |

### The authority rule

Only the policy engine (`■`) can return `ALLOW`. An AI assessment (`◆`), whether from Lupa's
own model or from the agent, can turn `ALLOW` into `HOLD`. It can never turn `HOLD` or `BLOCK`
into `ALLOW`. Only the buyer, through
[resolve](#resolve-a-held-request), can release a held payment. `tests/test_policy_engine.py`
checks this on 1000 random cases on every push.

### Decision to PayPal mapping

| Final decision | PayPal sandbox calls |
|---|---|
| `ALLOW` | Orders v2 with `intent: AUTHORIZE`, authorize, capture (`final_capture: true`) |
| `HOLD` | Orders v2 with `intent: AUTHORIZE`, authorize. The authorization waits for the buyer. |
| `BLOCK` | None. An existing authorization is voided. |

Approving a held request captures its authorization. Rejecting it voids the authorization. A
held request not resolved in 72 hours expires and is voided.

---

## Payment permissions

A payment permission is anything that lets someone take money from the buyer without asking
again: a subscription, a billing agreement, a vaulted payment method used by a merchant, or a
bounded authority given to an AI agent. Lupa rebuilds them from payment history (a PayPal
activity export and the sandbox Transaction Search API) because PayPal does not list them for
the buyer.

### List payment permissions

`GET /payment-permissions`

Lists the buyer's payment permissions, newest payment first, with a headline.

**Query parameters**

| Name | Type | Description |
|---|---|---|
| `status` | string | Filter: `active`, `suspended`, `dormant`, `revoked`, `expired`. |
| `kind` | string | Filter: `fixed_recurring`, `variable_recurring`, `one_time_authority`, `agent_authority`, `unknown`. |
| `attention` | string | Only permissions with this attention code, for example `DORMANT_12M`. |

**Sample request**

```bash
curl https://lupa.helppox.com/proposed/v1/me/payment-permissions?status=active
```

**Sample response**

```json
{
  "marker": "◇",
  "proposed": true,
  "data": {
    "headline": {
      "active": 25,
      "silent_over_a_year": 1,
      "text": "25 companies can take money from you. 1 has not in over a year."
    },
    "permissions": [
      {
        "id": "pp_b84a7a4bf2fa",
        "source": "paypal_sub",
        "external_ref": "I-2VEWNLDCCXWP",
        "merchant_alias": "Sandbox Software",
        "merchant_category": "digital service",
        "kind": "fixed_recurring",
        "status": "active",
        "first_seen": "2026-10-08T12:45:10Z",
        "last_payment_at": "2026-10-08T12:45:10Z",
        "last_amount": 1849,
        "currency": "EUR",
        "policy_id": null,
        "delegation_id": null,
        "attention": ["NEW_LAST_30D"],
        "marker": "●",
        "suggestion": null,
        "profile": { "n_payments": 1, "amount_median": 1849, "interval_days_median": null },
        "attention_sentences": [
          { "code": "NEW_LAST_30D", "text": "New in the last 30 days.", "marker": "■" }
        ]
      }
    ]
  },
  "paypal": null
}
```

### Show payment permission details

`GET /payment-permissions/{permission_id}`

Returns the [permission](#payment-permission) with its profile, payments, effective policy,
delegations and the last 20 payment requests.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `permission_id` | string | Required. The permission id, for example `pp_9aab7370df92`. |

**Response** `200 OK`. `data` is the permission plus:

| Field | Type | Description |
|---|---|---|
| `profile` | [profile](#profile) | Statistics computed from the payments. |
| `payments` | array | Payments through this permission: `id`, `paypal_txn_id`, `amount`, `currency`, `at`, `event_code`, `status`, `source`. |
| `policy` | [policy](#policy) | The policy in force. |
| `policy_is_default` | boolean | `true` when the account default applies. |
| `delegations` | array of [delegation](#delegation) | Current and past delegations. |
| `requests` | array of [payment request](#payment-request) | The last 20 requests. |

### Create an agent permission

`POST /payment-permissions`

Creates an `agent_authority` permission: a budget an AI agent can spend from. It has no
authority until it is [delegated](#delegate-a-permission-to-an-agent).

**Request body**

| Name | Type | Description |
|---|---|---|
| `agent_id` | string | Required. 1-64 characters. |
| `label` | string | Required. What the agent buys, for example `Shopping`. Becomes the merchant alias. |
| `category` | string | Default `marketplace`. |

**Sample request**

```bash
curl -X POST https://lupa.helppox.com/proposed/v1/me/payment-permissions \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "shopping-agent", "label": "Shopping"}'
```

**Response** `201 Created` with the new [permission](#payment-permission), `source:
lupa_delegation`, `kind: agent_authority`, `marker: ◇`.

### Revoke a payment permission

`POST /payment-permissions/{permission_id}/revoke`

Ends the permission. Every later request through it is blocked (rule `R01`).

What happens at PayPal depends on the source:

| `source` | Effect | `paypal_action` |
|---|---|---|
| `paypal_sub` | `POST /v1/billing/subscriptions/{id}/cancel` in the sandbox | `cancelled` |
| `lupa_delegation` | Ends the agent's authority in Lupa. No PayPal call. | `none` |
| `import_csv`, `paypal_pap`, `paypal_order` | Marked revoked in Lupa only. PayPal has no buyer-side API for these. The response says so and links to the PayPal settings page. | `not_available_to_buyer` |

An agent (with `X-Lupa-Agent`) can only revoke a permission delegated to it. Anything else
returns `403 agent_not_authorized`.

**Sample response**

```json
{
  "marker": "◇",
  "proposed": true,
  "data": {
    "permission": { "id": "pp_ec1e1fd1415c", "status": "revoked", "source": "paypal_sub" },
    "paypal_action": "cancelled"
  },
  "paypal": {
    "marker": "●",
    "calls": [
      { "method": "POST", "path": "/v1/billing/subscriptions/I-T247L50GF2HM/cancel", "status": 204 }
    ]
  }
}
```

### Suspend a payment permission

`POST /payment-permissions/{permission_id}/suspend`

Same as revoke, but the status becomes `suspended` and a PayPal subscription is suspended
(`POST /v1/billing/subscriptions/{id}/suspend`) instead of cancelled.

### Get a suggested limit

`GET /payment-permissions/{permission_id}/suggested-limit`

Code computes candidate limits from the payment profile. The model (`◆`) picks one and gives a
reason code. It can only pick from the candidates. Without a model, the policy picks (`■`).
Nothing is stored.

**Response** `200 OK`

| Field | Type | Description |
|---|---|---|
| `candidates` | array of integer | Limits computed by code. |
| `pick` | integer | Index of the chosen candidate. |
| `limit` | integer | The suggested limit, minor units. |
| `reason_code` | string | Why this candidate. |
| `by` | string | `ai` or `policy`. |
| `marker` | string | `◆` or `■`. |
| `sentence` | string | A fixed sentence for display. Its numbers come from the ledger. |

Returns `409 no_history` for a permission with no payments.

### Explain a permission

`POST /payment-permissions/{permission_id}/explain`

For a permission of kind `unknown`, the model suggests what it looks like (`◆`). The suggestion
is stored in `suggestion`. It never changes `kind`. Returns the stored suggestion for other
kinds, or `null`.

---

## Policies

A policy sets the limits a payment must pass. Each permission can have its own. Otherwise the
account default applies.

### Set a permission's policy

`PUT /payment-permissions/{permission_id}/policy`

**Request body**: a [policy input](#policy).

**Sample request**

```bash
curl -X PUT https://lupa.helppox.com/proposed/v1/me/payment-permissions/pp_b84a7a4bf2fa/policy \
  -H "Content-Type: application/json" \
  -d '{"max_amount": 2000, "recurring": "allow", "amount_increase": "require_approval",
       "increase_tolerance_pct": 10, "new_merchant": "require_approval"}'
```

**Response** `200 OK` with the stored [policy](#policy).

Errors: `422 policy_invalid`.

### Show the default policy

`GET /policies/default`

### Set the default policy

`PUT /policies/default`

Same body as a permission policy. Applies to every permission without its own.

### Draft a policy from a sentence

`POST /intent`

The model (`◆`) turns one sentence into a draft policy. Nothing is stored. The client shows the
draft and stores it with `PUT .../policy` if the buyer accepts (`created_by:
ai_draft_accepted`).

**Request body**

| Name | Type | Description |
|---|---|---|
| `text` | string | Required. 3-300 characters. |

**Sample request**

```bash
curl -X POST https://lupa.helppox.com/proposed/v1/me/intent \
  -H "Content-Type: application/json" \
  -d '{"text": "Anything recurring over 20 euros needs me."}'
```

**Sample response**

```json
{
  "marker": "◇",
  "proposed": true,
  "data": {
    "draft": {
      "max_amount": 2000,
      "currency": "EUR",
      "recurring": "allow",
      "amount_increase": "require_approval",
      "increase_tolerance_pct": 20,
      "new_merchant": "require_approval",
      "max_per_month": null,
      "expires_at": null,
      "created_by": "ai_draft_accepted",
      "intent_text": "Anything recurring over 20 euros needs me."
    },
    "reason_codes": ["INTENT_THRESHOLD"],
    "sentences": ["Payments over 20.00 EUR wait for you."],
    "model": "openai/gpt-5.6-luna",
    "prompt_version": "intent_to_policy/2",
    "stored": false
  },
  "paypal": null
}
```

Errors: `503 ai_unavailable` when no model answers. The buyer sets the policy by hand instead.

---

## Delegations

A delegation hands part of a permission's authority to one agent, with its own, tighter limits.

### Delegate a permission to an agent

`POST /payment-permissions/{permission_id}/delegate`

**Request body**

| Name | Type | Description |
|---|---|---|
| `agent_id` | string | Required. Must match the agent's `X-Lupa-Agent` header. |
| `authority` | string | `propose` (default): every payment waits for the buyer (rule `R20`). `approve`: the agent's requests can pass inside the limits below. |
| `max_amount` | integer | Required. Largest single payment, minor units. |
| `recurring_allowed` | boolean | Default `false`. |
| `amount_change_pct` | integer | Default `20`. Largest change from the usual amount, percent. |
| `min_confidence` | number | Default `0.95`. Lower confidence holds the payment (rule `R31`). |
| `expires_at` | string | Required. RFC 3339. Must be in the future. |

**Sample request**

```bash
curl -X POST https://lupa.helppox.com/proposed/v1/me/payment-permissions/pp_9aab7370df92/delegate \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "shopping-agent", "authority": "approve", "max_amount": 8000,
       "recurring_allowed": false, "expires_at": "2026-10-15T13:27:14Z"}'
```

**Sample response**

```json
{
  "marker": "◇",
  "proposed": true,
  "data": {
    "id": "dlg_4c84a722a673",
    "permission_id": "pp_9aab7370df92",
    "agent_id": "shopping-agent",
    "authority": "approve",
    "max_amount": 8000,
    "recurring_allowed": false,
    "amount_change_pct": 20,
    "min_confidence": 0.95,
    "expires_at": "2026-10-15T13:27:14.410983Z",
    "revoked_at": null
  },
  "paypal": null
}
```

Errors: `400 delegation_expired`.

### Revoke a delegation

`DELETE /delegations/{delegation_id}`

Ends the delegation now. The agent's later requests are held (rule `R21`).

---

## Payment requests

A payment request is a charge that wants to go through a permission. It can come from a
merchant, from an agent (with `X-Lupa-Agent`), from a webhook or from a test scenario. Lupa
assesses it (`◆`), decides (`■`) and executes the decision in PayPal (`●`), in that order, in
one call.

### Create a payment request

`POST /payment-permissions/{permission_id}/requests`

**Request body**

| Name | Type | Description |
|---|---|---|
| `amount` | integer | Required. Minor units, greater than 0. |
| `currency` | string | Default `EUR`. |
| `merchant_alias` | string | Who is charging. Default: the permission's merchant. A different merchant triggers `R14` or `R04`. |
| `is_recurring` | boolean | Default `false`. |
| `purpose` | string | Up to 200 characters. What the payment is for. |
| `assessment` | [assessment](#assessment) | The agent's own view. Stored as an AI verdict. It can only make the decision stricter. |
| `execute` | boolean | Call PayPal. Default: when PayPal credentials are configured. |
| `source` | string | `api` (default), `agent`, `webhook`, `scenario`. Set to `agent` automatically when `X-Lupa-Agent` is present. |

**Sample request** (an agent buying a desk lamp)

```bash
curl -X POST https://lupa.helppox.com/proposed/v1/me/payment-permissions/pp_9aab7370df92/requests \
  -H "Content-Type: application/json" \
  -H "X-Lupa-Agent: shopping-agent" \
  -d '{"amount": 4500, "currency": "EUR", "merchant_alias": "Online Shop",
       "purpose": "Desk lamp", "assessment": {"decision": "approve", "confidence": 0.97}}'
```

**Sample response** (allowed and captured)

```json
{
  "marker": "◇",
  "proposed": true,
  "data": {
    "request": {
      "id": "req_3f9d0c2a71b4",
      "permission_id": "pp_9aab7370df92",
      "amount": 4500,
      "currency": "EUR",
      "merchant_alias": "Online Shop",
      "is_recurring": false,
      "requested_at": "2026-10-09T08:05:12.114Z",
      "source": "agent",
      "agent_id": "shopping-agent",
      "purpose": "Desk lamp",
      "paypal_order_id": "8XK41529UL3360920",
      "paypal_authorization_id": "0VD47130XB892644E",
      "state": "captured",
      "hold_until": null
    },
    "decision": {
      "id": "dec_a81f5e0b9c13",
      "request_id": "req_3f9d0c2a71b4",
      "ai_verdict": "approve",
      "ai_confidence": 0.97,
      "ai_reason_codes": ["WITHIN_DELEGATION", "AMOUNT_IN_RANGE"],
      "policy_verdict": "ALLOW",
      "rule_hits": [],
      "final": "ALLOW",
      "resolved_by": null,
      "paypal_action": "captured",
      "sentences": ["Within what you delegated to the agent."],
      "markers": { "policy": "■", "ai": "◆", "paypal": "●" }
    }
  },
  "paypal": {
    "marker": "●",
    "calls": [
      { "method": "POST", "path": "/v2/checkout/orders", "status": 201, "paypal_id": "8XK41529UL3360920" },
      { "method": "POST", "path": "/v2/checkout/orders/8XK41529UL3360920/authorize", "status": 201 },
      { "method": "POST", "path": "/v2/payments/authorizations/0VD47130XB892644E/capture", "status": 201 }
    ]
  }
}
```

The same agent asking for 120.00 gets `final: HOLD` with a rule hit
`{"rule": "R21", "verdict": "HOLD", "values": {"why": ["amount"], "amount": 12000,
"delegation_max": 8000}}`, `state: held`, and only the order and authorize calls.

Errors: `404 permission_not_found`, `422 invalid_request`. A PayPal failure never returns an
error here: the request is held with rule `PAYPAL_UNAVAILABLE` and nothing is captured.

### List payment requests

`GET /requests`

**Query parameters**

| Name | Type | Description |
|---|---|---|
| `state` | string | Default `held`, which is the buyer's queue. Empty string for all. Values: `received`, `held`, `allowed`, `captured`, `blocked`, `voided`, `expired`. |

### Resolve a held request

`POST /requests/{request_id}/resolve`

The buyer approves or rejects a held request. This is the only way a `HOLD` becomes a payment.
Agents can not call it in a production version (no `payment-requests.resolve` scope).

**Request body**

| Name | Type | Description |
|---|---|---|
| `action` | string | Required. `approve` captures the authorization. `reject` voids it. |

**Sample request**

```bash
curl -X POST https://lupa.helppox.com/proposed/v1/me/requests/req_b7918549dd5f/resolve \
  -H "Content-Type: application/json" \
  -d '{"action": "approve"}'
```

**Response** `200 OK` with the request (`state: captured` or `voided`) and a new decision with
`resolved_by: human` and `sentences: ["You approved this payment."]`.

Errors: `404 request_not_found`, `409 request_not_held`, `502 paypal_error`.

A held request nobody resolves expires at `hold_until` (72 hours by default): the authorization is voided and the state becomes `expired`.

### Submit an agent decision

`POST /requests/{request_id}/decision`

An agent gives its own verdict on one of its requests. Lupa stores it as an AI verdict and
evaluates again. The new verdict can keep or add a hold. It can not lift a hold the policy set.

**Request body**: an [assessment](#assessment).

Errors: `403 agent_not_authorized` when the request belongs to another agent, `409
request_closed`.

---

## Events

### List events

`GET /events`

The audit trail, newest first. Every step of every request is here with its marker: what was
asked, what the model said, what the policy decided, what PayPal did.

**Query parameters**

| Name | Type | Description |
|---|---|---|
| `since` | string | RFC 3339. Only events after this time. |
| `limit` | integer | Default 300. |

**Sample response** (one request, newest first)

```json
{
  "marker": "◇",
  "proposed": true,
  "data": [
    { "kind": "paypal.captured", "marker": "●", "ref_id": "req_3f9d0c2a71b4",
      "payload": { "capture_id": "6RB16247DX7104402", "status": "COMPLETED" } },
    { "kind": "paypal.authorized", "marker": "●", "ref_id": "req_3f9d0c2a71b4",
      "payload": { "order_id": "8XK41529UL3360920", "authorization_id": "0VD47130XB892644E" } },
    { "kind": "policy.evaluated", "marker": "■", "ref_id": "req_3f9d0c2a71b4",
      "payload": { "policy_verdict": "ALLOW", "final": "ALLOW", "rules": [] } },
    { "kind": "ai.assessed", "marker": "◆", "ref_id": "req_3f9d0c2a71b4",
      "payload": { "verdict": "approve", "confidence": 0.97, "model": "openai/gpt-5.6-luna" } },
    { "kind": "request.received", "marker": "◇", "ref_id": "req_3f9d0c2a71b4",
      "payload": { "amount": 4500, "currency": "EUR", "agent_id": "shopping-agent" } }
  ],
  "paypal": null
}
```

Event kinds: `import.csv`, `paypal.sync`, `paypal.search_unavailable`, `paypal.webhook`,
`paypal.webhook.rejected`, `permission.created`, `permission.revoke`, `permission.suspend`,
`permission.explained`, `paypal.subscription.revoke`, `paypal.subscription.suspend`,
`policy.set`, `intent.draft`, `intent.unavailable`, `limit.suggested`, `delegation.created`,
`delegation.revoked`, `request.received`, `ai.assessed`, `ai.unavailable`,
`request.agent_decision`, `policy.evaluated`, `paypal.authorized`, `paypal.captured`,
`paypal.voided`, `paypal.error`, `request.approved_by_human`, `request.rejected_by_human`,
`request.expired`, `agent.revoke_refused`.

In a production version the same events would go out as buyer-side webhooks, so a wallet, a
bank app or a family member's phone could subscribe to them. PayPal's webhooks today go to the
merchant only.

---

## Objects

### Payment permission

| Field | Type | Description |
|---|---|---|
| `id` | string | `pp_` + 12 hex. |
| `source` | string | Where it was found: `import_csv` (activity export), `paypal_sub` (sandbox subscription), `paypal_pap` (pre-approved payment), `paypal_order` (orders seen in Transaction Search), `lupa_delegation` (agent authority). |
| `external_ref` | string | The PayPal id (`I-...`, `B-...`) or a keyed hash for imported rows. |
| `merchant_alias` | string | Merchant name. The demo data uses aliases only. |
| `merchant_category` | string | For example `digital service`, `cloud`, `media`. |
| `kind` | string | `fixed_recurring`, `variable_recurring`, `one_time_authority`, `agent_authority`, `unknown`. Set by code, never by the model. |
| `status` | string | `active`, `suspended`, `dormant`, `revoked`, `expired`. |
| `first_seen`, `last_payment_at` | string | RFC 3339. |
| `last_amount` | integer | Minor units. |
| `currency` | string | ISO 4217. |
| `policy_id`, `delegation_id` | string | Own policy and active delegation, or `null`. |
| `attention` | array of string | `DORMANT_6M`, `DORMANT_12M`, `AMOUNT_JUMP`, `INTERVAL_BREAK`, `ONE_OFF_STILL_ACTIVE`, `NO_HISTORY`, `NEW_LAST_30D`. |
| `attention_sentences` | array | `{code, text, marker}` for display. |
| `suggestion` | object | The model's guess for an `unknown` kind (`◆`), or `null`. |
| `marker` | string | `●` for PayPal data, `◇` for agent authority. |

### Profile

| Field | Type | Description |
|---|---|---|
| `n_payments` | integer | Number of payments. |
| `amount_min`, `amount_max`, `amount_median`, `amount_p95` | integer | Minor units. |
| `interval_days_median`, `interval_days_mad` | number | Days between payments, and its spread. |
| `months_since_last` | number | Since the last payment. |
| `amount_trend` | number | Last amount against the median, percent. |

### Policy

| Field | Type | Default | Description |
|---|---|---|---|
| `max_amount` | integer | required | Largest single payment, minor units. |
| `currency` | string | `EUR` | A payment in another currency is blocked (`R03`). |
| `recurring` | string | `allow` | `allow`, `require_approval`, `block`. |
| `amount_increase` | string | `require_approval` | What to do when the amount is above the usual one by more than the tolerance. |
| `increase_tolerance_pct` | integer | `20` | 0-500. |
| `new_merchant` | string | `require_approval` | A different merchant on this permission. |
| `max_per_month` | integer | `null` | Monthly cap, minor units. |
| `expires_at` | string | `null` | After this the policy blocks everything (`R02`). |
| `created_by` | string | `human` | `human` or `ai_draft_accepted`. |
| `intent_text` | string | `null` | The sentence the draft came from. |

Response only: `id`, `permission_id` (`null` for the default), `created_at`.

### Delegation

See [Delegate a permission to an agent](#delegate-a-permission-to-an-agent). Response adds `id`,
`permission_id` and `revoked_at`.

### Assessment

| Field | Type | Description |
|---|---|---|
| `decision` | string | Required. `approve`, `escalate`, `reject`. |
| `confidence` | number | Required. 0-1. |
| `reason` | string | Up to 300 characters. Stored, never shown as a decision reason. |

When both Lupa's model and the agent give an assessment, the stricter one counts: the worse
verdict, the lower confidence.

### Payment request

| Field | Type | Description |
|---|---|---|
| `id` | string | `req_` + 12 hex. |
| `permission_id` | string | |
| `amount`, `currency`, `merchant_alias`, `is_recurring`, `purpose` | | As sent. |
| `requested_at` | string | RFC 3339. |
| `source` | string | `api`, `agent`, `webhook`, `scenario`. |
| `agent_id` | string | From `X-Lupa-Agent`, or `null`. |
| `paypal_order_id`, `paypal_authorization_id` | string | The sandbox order and authorization. |
| `state` | string | `received`, `held`, `allowed`, `captured`, `blocked`, `voided`, `expired`. |
| `hold_until` | string | When a held request expires and is voided. |
| `decision` | [decision](#decision) | The latest decision. |

### Decision

| Field | Type | Description |
|---|---|---|
| `id` | string | `dec_` + 12 hex. |
| `request_id` | string | |
| `ai_verdict`, `ai_confidence`, `ai_reason_codes` | | The assessment used (`◆`). Reason codes come from a fixed list: `AMOUNT_IN_RANGE`, `AMOUNT_ABOVE_RANGE`, `AMOUNT_RATIO`, `MERCHANT_MATCH`, `MERCHANT_UNKNOWN`, `INTERVAL_MATCH`, `INTERVAL_EARLY`, `FIRST_CHARGE`, `DORMANT_REACTIVATED`, `WITHIN_DELEGATION`. |
| `ai_model`, `ai_prompt_version` | string | Recorded on every decision. |
| `policy_verdict` | string | `ALLOW`, `HOLD`, `BLOCK` from rules R01-R21, without the AI. |
| `rule_hits` | array | `{rule, verdict, values}` for each rule that fired. |
| `final` | string | The decision. Never less strict than `policy_verdict`, until a human resolves it. |
| `resolved_by` | string | `human` after resolve, `expiry` when the hold window passed, otherwise `null`. |
| `paypal_action` | string | `captured`, `authorized`, `voided` or `null`. |
| `sentences` | array of string | Fixed sentences for display. The model's own text is never shown. |
| `markers` | object | `{policy, ai, paypal}`. |

---

## Policy rules

Rules R01-R21 run first and never look at the AI. R30-R32 read the AI verdict and can only add
`HOLD`. The strictest verdict wins.

| Rule | Verdict | When |
|---|---|---|
| `R01` | BLOCK | Permission revoked, expired or suspended |
| `R02` | BLOCK | Policy expired |
| `R03` | BLOCK | Currency differs from the policy |
| `R04` | BLOCK | Recurring when the policy blocks recurring, or a new merchant when it blocks new merchants |
| `R10` | HOLD | Amount above the policy limit |
| `R11` | HOLD | Recurring and the policy asks for approval |
| `R12` | HOLD | Amount above the usual range and the policy asks for approval |
| `R13` | BLOCK | Amount above the usual range and the policy blocks increases |
| `R14` | HOLD | Merchant is not this permission's merchant |
| `R15` | HOLD | Monthly total would pass the monthly cap |
| `R16` | HOLD | Permission silent for a year, or never used |
| `R20` | HOLD | The agent may only propose |
| `R21` | HOLD | Outside the agent's delegation (amount, recurring, change, expired, or no delegation) |
| `R30` | HOLD | AI recommends rejecting. Only a human can block. |
| `R31` | HOLD | AI escalates, or is less confident than `min_confidence` |
| `R32` | HOLD | AI unavailable, and the payment is not inside the hard limits |
| `PAYPAL_UNAVAILABLE` | HOLD | The PayPal call failed. Nothing was captured. |

---

## Errors

Errors use HTTP status codes and one body shape:

```json
{
  "error": {
    "code": "request_not_held",
    "message": "Request is captured"
  }
}
```

| HTTP | `code` | When |
|---|---|---|
| 400 | `delegation_expired` | `expires_at` is in the past |
| 403 | `agent_not_authorized` | An agent acting on a permission or request that is not its own |
| 404 | `permission_not_found`, `request_not_found`, `delegation_not_found` | Unknown id |
| 409 | `permission_exists` | The permission already exists |
| 409 | `no_history` | No payments to base a limit on |
| 409 | `request_not_held`, `request_closed` | The request is no longer waiting |
| 422 | `invalid_request`, `policy_invalid` | Body failed validation. `details` lists the fields. |
| 502 | `paypal_error` | PayPal returned an error. `paypal` has `name` and `debug_id`. |
| 503 | `ai_unavailable` | No model answered for a task that needs one |

---

## Sandbox and demo routes

These are not part of the proposal. They connect the prototype to the PayPal sandbox.

| Method and path | Description |
|---|---|
| `GET /paypal/status` | Whether sandbox credentials, the test card and webhook verification are configured. |
| `POST /paypal/sync?days=90` | Reads Transaction Search (in 31-day windows) and each known subscription's transactions, then rebuilds permissions. Returns `transactions`, `permissions`, `reference_types`, `transaction_search`. |
| `POST /paypal/webhook` | Receives PayPal webhooks. Verifies the signature with `/v1/notifications/verify-webhook-signature` when `PAYPAL_WEBHOOK_ID` is set, stores the event and syncs the resource it refers to. |
| `GET /api/markers` | The marker legend. |

---

## MCP tools

`lupa/mcp/server.py` exposes the API to any MCP client (Claude Desktop, Claude Code and
others). Each tool is one HTTP call with the agent's id in `X-Lupa-Agent`. The agent never sees
PayPal credentials and has no tool to resolve a held request.

| Tool | Calls |
|---|---|
| `list_payment_permissions(status)` | `GET /payment-permissions` |
| `inspect_payment_permission(permission_id)` | `GET /payment-permissions/{id}` |
| `request_payment(permission_id, amount, purpose, currency, merchant, is_recurring, your_confidence)` | `POST /payment-permissions/{id}/requests` |
| `submit_decision(request_id, decision, confidence, reason)` | `POST /requests/{id}/decision` |
| `revoke_payment_permission(permission_id)` | `POST /payment-permissions/{id}/revoke` |

Configuration: `LUPA_API_URL` (default `http://127.0.0.1:8000`), `LUPA_AGENT_ID` (default
`shopping-agent`). See the README for a Claude Desktop config block.
