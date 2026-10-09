# Consumer Payment Authorization API

> This is the original project plan, written before the build started. Parts of it changed on the way. What was built is described in the [README](README.md) and the [API reference](docs/api-reference.md).

## PayPal AI Hackathon — Project Plan

## 1. Executive Summary

### The idea

Build a **consumer payment authorization layer for agentic payments**.

The central proposition:

> **AI agents should never receive unrestricted access to a consumer's money. They should receive bounded, programmable payment authority.**

PayPal already provides powerful payment infrastructure. However, the consumer-facing control model is primarily designed around humans interacting directly with PayPal.

Agentic commerce changes this.

If an AI agent is allowed to act on behalf of a consumer, the consumer needs to be able to define:

- what the agent may pay for
- which merchants it may use
- how much it may spend
- whether payments may recur
- how much an amount may change
- how long the authorization remains valid
- when the agent may act autonomously
- when the agent must ask the consumer
- when a payment must simply be blocked

We propose a **Consumer Payment Authorization API** that exposes these capabilities as programmable primitives.

The API becomes the foundation.

The AI is one application of that foundation.

For the hackathon, we implement a working prototype of this proposed API and build one concrete application on top of it:

> **An AI-powered payment-permission guard that discovers, understands and protects automatic payments.**

---

# 2. The Core Insight

Traditional automatic payment authorization is essentially:

> "This merchant may charge me automatically, up to some predefined limit."

Agentic payment authorization needs to become:

> "This agent may make decisions on my behalf, but only within these conditions."

The distinction is important.

### Traditional

```text
Maximum automatic payment: €100

Payment ≤ €100
        ↓
      PAY
```

### Agentic

```text
Payment request
      ↓
Does it fit the consumer's permission?
      ↓
AI evaluates context
      ↓
 ┌──────────┬──────────┬──────────┐
 │ APPROVE  │  HOLD    │  REJECT  │
 └──────────┴──────────┴──────────┘
```

The AI can make decisions.

**It cannot expand its own authority.**

That is the fundamental safety principle.

---

# 3. Why This Matters Now

Agentic commerce is moving the payment decision from:

> human → PayPal → merchant

towards:

> human → AI agent → PayPal → merchant

That creates a missing layer.

The consumer needs to be able to delegate authority without delegating unrestricted control of their money.

The project therefore asks:

> **What should the consumer authorization layer for agentic payments look like?**

This is deliberately broader than subscriptions.

Subscriptions, automatic payments, shopping agents, household agents, expense agents and autonomous purchasing are all applications of the same underlying primitive:

**payment permission.**

---

# 4. What We Are Actually Building

We build four layers.

```text
                 CONSUMER
                    │
                    │ human intent
                    ▼
              ┌────────────┐
              │     AI     │
              │ interprets │
              │   intent   │
              └─────┬──────┘
                    │
                    ▼
        ┌─────────────────────────┐
        │ PAYMENT AUTHORIZATION   │
        │ API / POLICY ENGINE     │
        │                         │
        │ hard limits             │
        │ merchant scope          │
        │ frequency               │
        │ amount variation        │
        │ expiration              │
        │ agent authority         │
        └────────────┬────────────┘
                     │
                     ▼
             PAYPAL SANDBOX
```

## Layer 1 — Real PayPal

Use PayPal Sandbox wherever functionality exists.

Examples:

- transactions
- payments
- orders
- subscriptions
- transaction search
- relevant PayPal identifiers
- webhooks
- cancellation functionality where supported

This proves that the project is genuinely integrated with PayPal.

## Layer 2 — Proposed Consumer API

We implement the missing consumer-oriented abstraction ourselves.

This is a **real, working API prototype**, not a static mockup.

The UI explicitly identifies these capabilities as:

> **PROPOSED PAYPAL API**

We do not pretend that these endpoints currently exist in PayPal's public API.

## Layer 3 — AI

AI interprets human intent and transaction context.

Examples:

> "Anything recurring above €20 needs me to approve it."

> "Handle my electricity bill automatically, but ask me if it suddenly becomes much higher."

> "Let this shopping agent buy things for me, but never create a new recurring payment."

AI converts these statements into structured policy.

## Layer 4 — Deterministic Policy Engine

The policy engine enforces the resulting authority.

The LLM never directly controls money.

> **The model proposes. Code decides.**

---

# 5. The Proposed API

The API should be deliberately small.

We do not need to invent an entire PayPal replacement.

We demonstrate a handful of primitives that establish the concept.

## 5.1 Discover payment permissions

```http
GET /v1/me/payment-permissions
```

Answers:

> "What entities currently have permission to take money from me?"

A permission can represent:

- subscription
- recurring payment
- pre-approved payment
- variable recurring payment
- one-time delegated payment
- agent authorization

---

## 5.2 Inspect a permission

```http
GET /v1/me/payment-permissions/{id}
```

Returns information such as:

```json
{
  "permission_id": "pp_12345",
  "merchant": "merchant_07",
  "status": "active",
  "type": "variable_recurring",
  "created": "2023-06-28",
  "last_payment": {
    "amount": 139.84,
    "currency": "EUR"
  },
  "policy": {
    "max_amount": 50,
    "recurring": "require_approval",
    "amount_increase": "require_approval"
  }
}
```

---

## 5.3 Cancel/revoke a permission

```http
POST /v1/me/payment-permissions/{id}/revoke
```

This is particularly useful for the demo because PayPal already exposes cancellation concepts in parts of its payment infrastructure and the consumer UI clearly has the ability to cancel automatic payments.

Our API demonstrates what a clean consumer-facing developer abstraction could look like.

---

## 5.4 Define a policy

```http
POST /v1/me/payment-permissions/{id}/policy
```

Example:

```json
{
  "max_amount": 50,
  "currency": "EUR",
  "recurring": "require_approval",
  "amount_increase": "require_approval",
  "new_merchant": "block"
}
```

---

## 5.5 Delegate authority to an agent

```http
POST /v1/me/payment-permissions/{id}/delegate
```

Example:

```json
{
  "agent": "household-payment-agent",
  "authority": "approve",
  "conditions": {
    "max_amount": 150,
    "recurring": true,
    "amount_change": "<20%"
  }
}
```

The agent receives **authority**, not account access.

---

## 5.6 Submit a decision

```http
POST /v1/me/payment-permissions/{id}/decision
```

Example:

```json
{
  "decision": "approve",
  "confidence": 0.97,
  "reason": "Amount and merchant behaviour match established payment pattern."
}
```

Or:

```json
{
  "decision": "escalate",
  "confidence": 0.61,
  "reason": "Payment is 3.8x higher than the established payment range."
}
```

The policy engine still makes the final authorization decision.

---

# 6. The AI's Role

AI should be **heavily used but largely invisible**.

This is intentional.

We should avoid building:

> "ChatGPT for PayPal."

Instead, AI operates behind the interface.

## Example

The user says:

> "Keep my automatic payments safe. Anything recurring over €20 needs me."

AI translates this into:

```json
{
  "recurring": true,
  "threshold": 20,
  "action": "require_approval"
}
```

The deterministic policy engine enforces it.

The consumer does not need to understand that an LLM was involved.

---

# 7. AI Can Also Determine Appropriate Limits

This is one of the strongest uses of AI in the project.

A user may say:

> "Handle my electricity bill automatically."

They should not have to calculate an appropriate ceiling.

The system can inspect historical payments:

```text
€91.20
€103.40
€98.70
€112.30
€107.90
€119.20
€126.40
```

AI proposes:

> **Suggested automatic-payment limit: €145**

Reason:

> Your recent payments range from €91–€126. €145 provides room for normal variation while sending unusually large payments for approval.

The user accepts.

Now the policy is deterministic.

AI helped create the policy, but does not own it.

---

# 8. AI-Assisted Approval

The API can also support delegated decisions.

Suppose a payment arrives:

```text
ELECTRICITY PROVIDER

€141.20
```

Historical range:

```text
€91–€126
```

Hard limit:

```text
€150
```

AI:

```text
CONFIDENCE: 96%

Likely normal seasonal variation.
Same merchant.
Same payment relationship.
Within configured hard limit.
```

Policy:

```text
IF confidence > 95%
AND amount < €150
→ APPROVE
```

Payment proceeds.

Now change the request:

```text
€487.00
```

AI:

```text
CONFIDENCE: 63%

Amount is 3.8× normal.
```

Result:

```text
PAYMENT HELD

User approval required.
```

This demonstrates **controlled autonomy**, not unrestricted autonomy.

---

# 9. The Subscription / Automatic Payment Demo

The first application should be deliberately narrow.

It demonstrates the API using a familiar consumer problem:

> **Understand and protect automatic payment permissions.**

Do not position the product as an anti-subscription service.

That would make the project unnecessarily narrow and potentially antagonistic toward merchants.

Instead:

> **Agentic payments require consumer visibility and control.**

Automatic payments are simply an excellent demonstration of why.

---

# 10. Demo Data

The user's real PayPal history is valuable as a reference for designing the data model.

It demonstrates several important patterns:

### Stable recurring

```text
Merchant A
€3.14
monthly
same payment permission
```

### Stable recurring with another amount

```text
Merchant B
€8.49
monthly
same permission
```

### Variable recurring

```text
Merchant C

€58.50
       ↓
€139.84

same payment permission
```

### Dormant permission

```text
Permission: ACTIVE

Last payment:
18 months ago
```

### One-off transaction with continuing authorization

This is particularly interesting because a consumer can make a one-off purchase and subsequently have an active payment relationship remaining.

The project should not assert why this happens or accuse merchants of exploiting it.

Instead:

> **A payment authorization can outlive the purchase that created it.**

That is enough.

---

# 11. Anonymization

Never use actual merchant names or personal information in the final demo.

Use generated identifiers:

```text
Merchant A
Merchant B
Merchant C
Merchant D
```

and realistic but synthetic descriptions:

```text
Digital service
Travel provider
Software provider
Media service
Online retailer
Cloud service
```

The anonymized dataset should preserve the **behavioural patterns**, not the identity.

---

# 12. Reconstructing Payment Permissions

Where real PayPal transaction data exposes sufficient information, use it.

Conceptually:

```text
PayPal transaction
       ↓
transaction type
       ↓
payment reference
       ↓
authorization ID
       ↓
transaction history
       ↓
behavioural profile
       ↓
payment permission
```

The system should distinguish:

- one-time payments
- recurring behaviour
- pre-approved payment relationships
- subscriptions
- variable amounts
- dormant permissions
- unusual amount changes

This is an important part of the technical implementation.

We are not simply asking an LLM:

> "Does this look like a subscription?"

We first extract deterministic evidence.

Then AI interprets the behaviour.

---

# 13. Real vs Proposed API

This distinction must be visible throughout the application.

Use a simple visual legend:

```text
● PAYPAL
Live PayPal Sandbox integration

◇ PROPOSED
Consumer API proposed by this project

◆ AI
AI interpretation

■ POLICY
Deterministic enforcement
```

For example:

```text
● PayPal Sandbox
164 transactions imported

        ↓

◇ Consumer Payment API
23 payment permissions reconstructed

        ↓

◆ AI
6 permissions require attention

        ↓

■ Policy Engine
2 payments require approval
```

This is one of the project's strengths.

We are not hiding the gap.

We are demonstrating it.

---

# 14. The Most Important Technical Principle

## AI cannot expand authority.

If the consumer says:

> "Automatic payments up to €50."

the AI cannot decide:

> "This €300 payment is probably legitimate, so I'll allow it."

The hard policy wins.

Likewise, if an agent receives:

```text
authority:
    max = €50
```

it cannot change itself to:

```text
max = €500
```

The authority boundary exists outside the model.

This gives the project a strong security architecture:

```text
             HUMAN INTENT
                   │
                   ▼
                  AI
                   │
            policy proposal
                   │
                   ▼
        ┌──────────────────┐
        │ POLICY ENGINE    │
        │                  │
        │ deterministic    │
        │ enforcement      │
        └────────┬─────────┘
                 │
          bounded authority
                 │
                 ▼
            PAYPAL API
```

---

# 15. Why the API Is More Important Than the Demo Application

This should be stated explicitly in the presentation.

The subscription/autopay application is only an example.

The real contribution is:

> **A consumer authorization layer for agentic payments.**

Once that exists, many different agents can use it.

### Shopping agent

> "Buy this if it stays below €80."

### Household agent

> "Handle electricity and internet bills automatically."

### Travel agent

> "You can spend up to €2,000 on this trip, but no new recurring services."

### Family agent

> "Allow children's purchases up to €20 without asking."

### Subscription guard

> "Recurring payments above €20 require approval."

### Business agent

> "Approve normal supplier invoices, but escalate anything outside historical behaviour."

The API is therefore the reusable infrastructure.

---

# 16. The MCP Connection

This is where the project can connect directly to the hackathon's AI/agent theme.

MCP should **not** be allowed direct unrestricted access to PayPal.

Instead:

```text
MCP Agent
    │
    ▼
Consumer Payment API
    │
    ├── permission checks
    ├── policy checks
    ├── authority checks
    ├── amount limits
    ├── merchant scope
    ├── recurrence rules
    └── escalation
    │
    ▼
PayPal
```

The MCP server becomes a controlled interface to payment capabilities.

For example, an agent could receive tools such as:

```text
list_payment_permissions()
inspect_payment_permission()
request_payment()
approve_payment()
revoke_payment_permission()
```

But every tool invocation passes through the authorization layer.

This is much safer than:

```text
MCP
 ↓
PayPal credentials
 ↓
do whatever the agent wants
```

The proposed API therefore becomes a **safety boundary for agentic financial MCP**.

---

# 17. Why This Is Not "Just an API"

The API is the novel primitive.

AI makes the primitive useful.

Without the API, every agent developer would need to invent their own:

- payment permissions
- limits
- delegation model
- escalation
- approval logic
- consumer authorization
- audit trail
- safety controls

With the API, these become reusable infrastructure.

The hackathon application demonstrates one implementation.

---

# 18. The Demo Flow

## 0:00–0:20 — The Problem

Show:

```text
PAYPAL

ACTIVE PAYMENT PERMISSIONS

Merchant A       ACTIVE
Merchant B       ACTIVE
Merchant C       ACTIVE
Merchant D       ACTIVE
...
```

Then:

> "Today, payment permissions are mostly designed for humans."

> "Tomorrow, agents will also need them."

---

## 0:20–0:45 — Connect PayPal

Connect to the PayPal Sandbox.

Import real sandbox transaction data.

Show:

```text
● REAL PAYPAL DATA

Transactions: 164
Payment relationships: 23
```

---

## 0:45–1:15 — AI Understands

AI identifies behavioural patterns.

```text
23 payment permissions

17 normal
4 unusual
2 require attention
```

No chatbot.

No AI avatar.

Just results.

---

## 1:15–1:40 — User Creates a Policy

User enters:

> "Anything recurring over €20 needs my approval."

AI converts this into a structured policy.

```text
◆ AI

Recurring payments
Maximum autonomous amount: €20
Above threshold: approval required
```

Then:

```text
■ POLICY

ACTIVE
```

---

## 1:40–2:05 — The Agent Acts

A payment arrives:

```text
Merchant C

€18.90 recurring
```

AI:

```text
96% confidence
Matches established behaviour
```

Policy:

```text
ALLOW
```

Payment proceeds.

Then:

```text
Merchant C

€89.90 recurring
```

Policy:

```text
HOLD
```

---

## 2:05–2:30 — User Intervention

Show:

```text
PAYMENT HELD

€89.90

Reason:
Above your automatic-payment limit.

Agent confidence:
78%

[ APPROVE ]   [ REJECT ]
```

The agent cannot bypass the boundary.

---

## 2:30–2:50 — Reveal the API

Show the architecture:

```text
REAL PAYPAL
      ↓
PROPOSED CONSUMER API
      ↓
AI
      ↓
POLICY ENGINE
      ↓
AGENT
```

Then show an actual API call.

```http
POST /v1/me/payment-permissions/123/decision
```

---

## 2:50–3:00 — Final Statement

> **"PayPal already knows how to move your money."**

> **"We built the consumer authorization layer that tells agents what that money is allowed to do."**

---

# 19. Judging Criteria

| Criterion                        | What we demonstrate                                                                             |
| -------------------------------- | ----------------------------------------------------------------------------------------------- |
| **Technological Implementation** | Real PayPal Sandbox + working API + AI + deterministic policy engine + optional MCP integration |
| **Design**                       | Extremely simple consumer experience; AI largely invisible                                      |
| **Impact**                       | Safer transition from human-controlled payments to agent-controlled payments                    |
| **Innovation**                   | Consumer payment permissions as a programmable primitive                                        |
| **Presentation**                 | Real payment → AI interpretation → policy → autonomous action / escalation                      |

---

# 20. What We Should NOT Build

Avoid:

- generic AI financial assistant
- chatbot interface
- shopping recommendation engine
- generic subscription tracker
- "AI saves you money"
- financial advisor
- huge dashboard
- fake PayPal UI
- fake PayPal APIs presented as existing
- LLM directly making payment decisions
- complicated autonomous wallet

The project should feel like **infrastructure disguised as a tiny consumer product**.

---

# 21. What We Should Build

### Minimum viable technical prototype

1. PayPal Sandbox integration
2. Transaction retrieval
3. Synthetic/anonymized payment-permission dataset
4. Payment-permission data model
5. Proposed Consumer API
6. Policy engine
7. AI intent → policy translation
8. AI transaction/behaviour analysis
9. Approval / escalation flow
10. One working agentic payment scenario
11. Clear real-vs-proposed API indicators

### Stretch goals

12. MCP server exposing the payment-permission API
13. Agent delegation
14. Confidence-based autonomous approval
15. AI-generated payment limits from history
16. Permission revocation
17. Webhook-driven payment events
18. Audit trail
19. Multiple agents using the same authorization layer

---

# 22. Product Architecture

```text
                         ┌───────────────────┐
                         │      CONSUMER     │
                         └─────────┬─────────┘
                                   │
                           natural language
                                   │
                                   ▼
                         ┌───────────────────┐
                         │       AI          │
                         │                   │
                         │ intent            │
                         │ classification    │
                         │ anomaly analysis  │
                         │ recommendation    │
                         └─────────┬─────────┘
                                   │
                              structured
                                policy
                                   │
                                   ▼
              ┌────────────────────────────────────┐
              │       CONSUMER PAYMENT API          │
              │                                    │
              │ permissions                         │
              │ delegation                          │
              │ policies                            │
              │ decisions                           │
              │ approval                            │
              │ revocation                          │
              └────────────────┬───────────────────┘
                               │
                        deterministic
                           enforcement
                               │
                               ▼
                    ┌──────────────────────┐
                    │     PAYPAL SANDBOX  │
                    │                      │
                    │ transactions         │
                    │ payments             │
                    │ subscriptions        │
                    │ webhooks             │
                    └──────────────────────┘
```

---

# 23. The Core Design Philosophy

Three rules should govern the entire implementation.

### 1. AI interprets.

AI is excellent at understanding ambiguous human intent and messy financial behaviour.

### 2. Code authorizes.

Hard limits, scopes, expiration and authority boundaries must be deterministic.

### 3. Humans resolve uncertainty.

If the agent cannot confidently determine whether a payment is permitted, it stops and asks.

```text
HIGH CONFIDENCE
       +
WITHIN AUTHORITY
       ↓
     ACT

LOW CONFIDENCE
       ↓
     ASK

OUTSIDE AUTHORITY
       ↓
     BLOCK
```

---

# 24. The Bigger Vision

The hackathon prototype is not fundamentally a subscription-management application.

It is a demonstration of a future payment architecture.

Today:

```text
Human
  ↓
PayPal
```

Emerging:

```text
Human
  ↓
Agent
  ↓
PayPal
```

Proposed:

```text
Human
  ↓
Payment Authority
  ↓
Agent
  ↓
Policy
  ↓
PayPal
```

The payment authority becomes the trust boundary.

That is the missing layer we are proposing.

---

# 25. One-Sentence Pitch

> **We built a consumer payment authorization API that lets AI agents act autonomously with bounded financial authority, while giving consumers deterministic control over what their money is allowed to do.**

## Shorter version

> **AI can act on your behalf without getting a blank cheque.**

## Presentation thesis

> **The future of payments is not just agentic. It needs delegated authority.**

## Final line

> **PayPal knows how to move your money. We built the layer that tells agents what they're allowed to do with it.**
