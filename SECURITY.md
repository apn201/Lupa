# Security policy

## What this is

A hackathon prototype that runs against the PayPal **sandbox** only. No real money moves, and
`lupa/config.py` refuses to start with a non-sandbox PayPal URL.

**Supported versions: `main`, and only `main`.**

## What the keys can and cannot do

- `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` belong to a sandbox REST app. They can create sandbox
  orders, authorize, capture and void them, and create, cancel and suspend sandbox subscriptions on
  the sandbox business account. They cannot touch a live account.
- `LUPA_TEST_CARD_NUMBER` is a sandbox test card from the Developer Dashboard generator.
- `LLM_API_KEY` reaches an OpenAI-compatible chat endpoint. The model never sees PayPal credentials,
  never calls PayPal and cannot approve a payment. Calls are capped per hour, per day and by spend,
  and fail closed (`lupa/ai/llm.py`).
- Agents reach Lupa through the proposed API only, identified by the `X-Lupa-Agent` header. In this
  prototype that header is not authenticated; a real deployment needs per-agent credentials.

## Data

The real PayPal export and settings list never enter this repository. They live in `private/`,
which is gitignored, and are anonymized by `scripts/anonymize_export.py` (HMAC ids, shifted dates,
aliases instead of names). `tools/check_secrets.py` scans the full git history and runs in CI.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: the **Security** tab of this repository, then
**Report a vulnerability**. One person maintains this around a day job: acknowledgement within
5 working days, a first assessment within 14 days.
