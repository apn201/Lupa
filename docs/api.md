# Lupa - Consumer Payment Authorization API (proposed)

◇ endpoints under /proposed/v1/me are proposed; PayPal has no such API today. ● routes under /paypal call the PayPal sandbox. ◆ marks AI interpretation, ■ deterministic policy enforcement. Amounts are integer minor units.

Generated from the OpenAPI document FastAPI emits (`make openapi`). Do not edit by hand.

## ◇ proposed `GET /proposed/v1/me/payment-permissions`

**List Permissions**

| parameter | in | required |
|---|---|---|
| `status` | query | False |
| `kind` | query | False |
| `attention` | query | False |

## ◇ proposed `POST /proposed/v1/me/payment-permissions`

**Create Agent Permission**

Create an agent_authority permission. Delegate it with POST .../delegate.

Body `AgentPermissionIn`:

| field | type | default |
|---|---|---|
| `agent_id` | string | required |
| `label` | string | required |
| `category` | string | "marketplace" |

## ◇ proposed `GET /proposed/v1/me/payment-permissions/{pid}`

**Get Permission**

| parameter | in | required |
|---|---|---|
| `pid` | path | True |

## ◇ proposed `POST /proposed/v1/me/payment-permissions/{pid}/revoke`

**Revoke**

| parameter | in | required |
|---|---|---|
| `pid` | path | True |

## ◇ proposed `POST /proposed/v1/me/payment-permissions/{pid}/suspend`

**Suspend**

| parameter | in | required |
|---|---|---|
| `pid` | path | True |

## ◇ proposed `PUT /proposed/v1/me/payment-permissions/{pid}/policy`

**Put Policy**

| parameter | in | required |
|---|---|---|
| `pid` | path | True |

Body `PolicyIn`:

| field | type | default |
|---|---|---|
| `max_amount` | integer | required |
| `currency` | string | "EUR" |
| `recurring` | allow \| require_approval \| block | "allow" |
| `amount_increase` | allow \| require_approval \| block | "require_approval" |
| `increase_tolerance_pct` | integer | 20 |
| `new_merchant` | allow \| require_approval \| block | "require_approval" |
| `max_per_month` | integer | null | null |
| `expires_at` | string | null | null |
| `created_by` | human \| ai_draft_accepted | "human" |
| `intent_text` | string | null | null |

## ◇ proposed `GET /proposed/v1/me/policies/default`

**Get Default**

## ◇ proposed `PUT /proposed/v1/me/policies/default`

**Put Default**

Body `PolicyIn`:

| field | type | default |
|---|---|---|
| `max_amount` | integer | required |
| `currency` | string | "EUR" |
| `recurring` | allow \| require_approval \| block | "allow" |
| `amount_increase` | allow \| require_approval \| block | "require_approval" |
| `increase_tolerance_pct` | integer | 20 |
| `new_merchant` | allow \| require_approval \| block | "require_approval" |
| `max_per_month` | integer | null | null |
| `expires_at` | string | null | null |
| `created_by` | human \| ai_draft_accepted | "human" |
| `intent_text` | string | null | null |

## ◇ proposed `POST /proposed/v1/me/intent`

**Intent**

◆ Draft a policy from one sentence. Nothing is stored until PUT .../policy.

Body `IntentIn`:

| field | type | default |
|---|---|---|
| `text` | string | required |

## ◇ proposed `GET /proposed/v1/me/payment-permissions/{pid}/suggested-limit`

**Suggested Limit**

| parameter | in | required |
|---|---|---|
| `pid` | path | True |

## ◇ proposed `POST /proposed/v1/me/payment-permissions/{pid}/explain`

**Explain**

| parameter | in | required |
|---|---|---|
| `pid` | path | True |

## ◇ proposed `POST /proposed/v1/me/payment-permissions/{pid}/delegate`

**Delegate**

| parameter | in | required |
|---|---|---|
| `pid` | path | True |

Body `DelegateIn`:

| field | type | default |
|---|---|---|
| `agent_id` | string | required |
| `authority` | propose \| approve | "propose" |
| `max_amount` | integer | required |
| `recurring_allowed` | boolean | false |
| `amount_change_pct` | integer | 20 |
| `min_confidence` | number | 0.95 |
| `expires_at` | string | required |

## ◇ proposed `DELETE /proposed/v1/me/delegations/{did}`

**Revoke Delegation**

| parameter | in | required |
|---|---|---|
| `did` | path | True |

## ◇ proposed `POST /proposed/v1/me/payment-permissions/{pid}/requests`

**Payment Request**

A payment request arrives. ◆ assess, ■ decide, ● execute.

| parameter | in | required |
|---|---|---|
| `pid` | path | True |
| `x-lupa-agent` | header | False |

Body `PaymentRequestIn`:

| field | type | default |
|---|---|---|
| `amount` | integer | required |
| `currency` | string | "EUR" |
| `merchant_alias` | string | null | null |
| `is_recurring` | boolean | false |
| `purpose` | string | null | null |
| `execute` | boolean | null | null |
| `source` | webhook \| scenario \| agent \| api | "api" |
| `assessment` | Assessment | null | null |

## ◇ proposed `POST /proposed/v1/me/requests/{rid}/decision`

**Submit Decision**

An agent submits its own verdict. Stored as an AI verdict; the engine still decides.

| parameter | in | required |
|---|---|---|
| `rid` | path | True |
| `x-lupa-agent` | header | False |

Body `Assessment`:

| field | type | default |
|---|---|---|
| `decision` | approve \| escalate \| reject | required |
| `confidence` | number | required |
| `reason` | string | null | null |

## ◇ proposed `POST /proposed/v1/me/requests/{rid}/resolve`

**Resolve**

| parameter | in | required |
|---|---|---|
| `rid` | path | True |

Body `ResolveIn`:

| field | type | default |
|---|---|---|
| `action` | approve \| reject | required |

## ◇ proposed `GET /proposed/v1/me/requests`

**Requests**

| parameter | in | required |
|---|---|---|
| `state` | query | False |

## ◇ proposed `GET /proposed/v1/me/events`

**Events**

| parameter | in | required |
|---|---|---|
| `since` | query | False |
| `limit` | query | False |

## ● paypal `GET /paypal/status`

**Status**

## ● paypal `POST /paypal/sync`

**Sync**

| parameter | in | required |
|---|---|---|
| `days` | query | False |

## ● paypal `POST /paypal/webhook`

**Webhook**

Store the event, then sync what it refers to. Signature checked when PAYPAL_WEBHOOK_ID is set.

## ui `GET /api/markers`

**Markers**

