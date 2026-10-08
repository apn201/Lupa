# PayPal API reference for Lupa

Extracted 2026-10-08 from PayPal's published OpenAPI schemas (transaction-search v1, orders v2, payments v2, subscriptions v1), the webhook event list, the transaction event code table, the sandbox accounts page and the Agent Toolkit README. Field names and enums below come from the schema files. Anything marked "verify" was not confirmed from an official source.

Base URL, sandbox: `https://api-m.sandbox.paypal.com`. Live: `https://api-m.paypal.com` (verify).

## 1. Authentication

`POST /v1/oauth2/token`, HTTP Basic with `CLIENT_ID:CLIENT_SECRET`, header `Content-Type: application/x-www-form-urlencoded`, body `grant_type=client_credentials`.

```
curl -X POST https://api-m.sandbox.paypal.com/v1/oauth2/token \
  -u "$PAYPAL_CLIENT_ID:$PAYPAL_CLIENT_SECRET" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials"
```

Response: `access_token`, `token_type` (`Bearer`), `expires_in` (seconds, sample shows 31668), `scope`, `app_id`, `nonce`. Send as `Authorization: Bearer <token>`. Refresh when `expires_in` runs out. Sandbox tokens last 3-8 hours per the toolkit README.

Credentials: Developer Dashboard, Apps & Credentials, Sandbox tab, create or open a REST app, copy client ID and secret. Transaction Search must be enabled under the app's Features (verify the exact label). Advanced card payments and Vault are separate features there too.

## 2. Transaction Search API

`GET /v1/reporting/transactions`. Lists the account's transactions for the previous three years. Executed transactions appear after up to three hours. This is the merchant account's view; third-party use needs the partner network.

Query parameters:
- `start_date`, `end_date` (required, RFC 3339 with seconds, e.g. `2026-04-01T00:00:00-0000`). Keep each query inside 31 days (verify; the integration guide states a per-call range limit).
- `fields`: `transaction_info` (default) or comma list including `payer_info`, `shipping_info`, `cart_info`, `store_info`, `auction_info`, `incentive_info`, or `all`.
- `transaction_type`: event code filter, e.g. `T0002`.
- `transaction_status`: `D` denied, `P` pending, `S` success, `V` reversed.
- `transaction_amount`: range `"10 TO 100"`.
- `transaction_currency`, `transaction_id`, `payment_instrument_type` (`CREDITCARD`, `DEBITCARD`), `store_id`, `terminal_id`.
- `balance_affecting_records_only`: `Y` (default) or `N`.
- `page_size` (default 100), `page` (default 1).
- Header `PayPal-Enforce-ISO8601-Format: true` for ISO dates.
- If any optional filter is given, `ending_balance` is empty.

Response: `transaction_details[]`, `account_number`, `start_date`, `end_date`, `last_refreshed_datetime`, `page`, `total_items`, `total_pages`, `links`.

`transaction_details[].transaction_info`:
- `transaction_id`
- `paypal_account_id` (the counterparty)
- `paypal_reference_id` ("a related, pre-existing transaction or event")
- `paypal_reference_id_type`: enum `ODR` (order), `TXN` (transaction), `SUB` (subscription), `PAP` (pre-approved payment)
- `transaction_event_code` (T-code, below)
- `transaction_initiation_date`, `transaction_updated_date`
- `transaction_amount`, `fee_amount`, `shipping_amount`, `sales_tax_amount`, `tip_amount`, and the other `money` fields: `{currency_code, value}` with value as a string
- `transaction_status`: `D`, `P`, `S`, `V`
- `transaction_subject`, `transaction_note`
- `invoice_id`, `custom_field`
- `ending_balance`, `available_balance`
- `protection_eligibility`: `01` eligible, `02` not, `03` partial
- `instrument_type`, `instrument_sub_type`

`payer_info`: `account_id`, `email_address`, `payer_name {given_name, surname, alternate_full_name}`, `address_status`, `payer_status`, `country_code`, `address`.

`cart_info.item_details[]`: `item_code`, `item_name`, `item_description`, `item_quantity`, `item_unit_price`, `item_amount`, `total_item_amount`, `invoice_number`.

Other endpoints: `GET /v1/reporting/balances`, `GET /v1/reporting/get-balance-net-summary`, `GET /v1/reporting/get-daily-summary`.

Mapping to the consumer CSV export (Activity Download): CSV `Type` "PreApproved Payment Bill User Payment" with `Reference Txn ID` starting `B-` corresponds to event code `T0003` with reference type `PAP`. "Express Checkout Payment" is `T0006`. "General Card Deposit" and "General Currency Conversion" are funding and conversion rows, not purchases. Verify the T0003/PAP pairing in the spike against seeded data.

### Transaction event codes, the ones that matter here

| Code | Meaning |
|---|---|
| T0000 | General payment |
| T0002 | Subscription payment |
| T0003 | Preapproved (pre-authorized) recurring bill payment |
| T0006 | Express Checkout payment |
| T0007 | Website payment (standard checkout) |
| T0011 | Mobile payment |
| T0013 | Donation |
| T0005 | Credit card payment |
| T0700 | General credit card deposit (funding) |
| T0300 | Bank deposit to PayPal (funding) |
| T1107 | Payment refund |
| T1106 | Payment reversal (PayPal initiated) |
| T1100 | General reversal |
| T0400 | General bank withdrawal |
| T2000 | Intra-account transfer (includes currency conversion rows, verify) |
| T01xx | Fees |

## 3. Orders API v2 (one-off and delegated payments)

`POST /v2/checkout/orders`. Headers: `Authorization`, `Content-Type: application/json`, `PayPal-Request-Id` (idempotency key, use the Lupa request id), `Prefer: return=representation`.

Request:
- `intent`: `CAPTURE` or `AUTHORIZE`
- `purchase_units[]`: `reference_id`, `amount {currency_code, value}` (optionally `breakdown`), `payee {email_address | merchant_id}`, `description` (127 chars shown), `custom_id`, `invoice_id`
- `payment_source.card`: `number`, `expiry` (`YYYY-MM`), `name`, `security_code`, `billing_address`. The schema notes that passing raw card data needs PCI SAQ D in production; the sandbox allows test cards (verify in the spike, and whether the app needs the advanced card feature enabled).
- `payment_source.paypal`: `email_address`, `experience_context {return_url, cancel_url, user_action: CONTINUE|PAY_NOW, shipping_preference: NO_SHIPPING}`, or `vault_id` for a stored wallet.

Minimal AUTHORIZE with a test card:
```json
{
  "intent": "AUTHORIZE",
  "purchase_units": [{
    "reference_id": "lupa-req-0001",
    "custom_id": "lupa-req-0001",
    "description": "Merchant C recurring",
    "amount": {"currency_code": "EUR", "value": "18.90"}
  }],
  "payment_source": {"card": {
    "number": "4111111111111111", "expiry": "2030-12", "name": "Test Buyer",
    "billing_address": {"address_line_1": "1 Test St", "admin_area_2": "Helsinki", "postal_code": "00100", "country_code": "FI"}
  }}
}
```
Test card numbers: use the card generator in the Developer Dashboard (Sandbox, Accounts, or the Credit Card Generator page). 4111 1111 1111 1111 is the usual Visa test number (verify).

Response: `id`, `status` enum `CREATED, SAVED, APPROVED, VOIDED, COMPLETED, PAYER_ACTION_REQUIRED`, `links[] {href, rel, method}`. For a wallet source the buyer must open the `approve` or `payer-action` link and log in as the sandbox personal account. A card source with the needed feature skips that.

`POST /v2/checkout/orders/{id}/authorize`: creates the authorization. Response carries `purchase_units[].payments.authorizations[]` with `id`, `status`, `amount`, `expiration_time`.

`POST /v2/checkout/orders/{id}/capture`: for CAPTURE-intent orders, response carries `purchase_units[].payments.captures[]`.

`GET /v2/checkout/orders/{id}`: order details.

## 4. Payments API v2 (authorizations)

`GET /v2/payments/authorizations/{authorization_id}`: `id`, `status` enum `CREATED, CAPTURED, DENIED, PARTIALLY_CAPTURED, VOIDED, PENDING`, `status_details.reason` (`PENDING_REVIEW`, `DECLINED_BY_RISK_FRAUD_FILTERS`), `amount`, `invoice_id`, `custom_id`, `expiration_time`, `seller_protection`, `create_time`, `update_time`.

`POST /v2/payments/authorizations/{id}/capture`: body `amount {currency_code, value}` (may be lower than authorized), `final_capture` (true closes the authorization), `invoice_id`, `note_to_payer`, `soft_descriptor`. Response: capture `id`, `status` enum `COMPLETED, DECLINED, PARTIALLY_REFUNDED, PENDING, REFUNDED, FAILED`, `amount`, `final_capture`.

`POST /v2/payments/authorizations/{id}/void`: no body needed. Response 200 with the authorization, `status: VOIDED` (204 is also documented, handle both). Cannot void a fully captured authorization.

`POST /v2/payments/authorizations/{id}/reauthorize`: honor period is 3 days, validity 29 days, and after 30 days a new authorization is needed. Reauthorize allowed from day 4 to day 29. Lupa does not rely on PayPal's expiry; it voids on its own schedule.

Negative testing: the sandbox supports a `PayPal-Mock-Response` header on some calls to force declines (verify which calls). Useful for the DENIED path in tests.

## 5. Subscriptions API v1 (recurring permissions)

A plan needs a product first: `POST /v1/catalogs/products` with `name`, `type` (`PHYSICAL`, `DIGITAL`, `SERVICE`), returns `id` (verify field names, this endpoint was not pulled from a schema).

`POST /v1/billing/plans`: `product_id`, `name`, `status` (`CREATED` or `ACTIVE`), `billing_cycles[] {frequency {interval_unit: DAY|WEEK|MONTH|YEAR, interval_count}, tenure_type: REGULAR|TRIAL, sequence, total_cycles (0 = infinite for REGULAR), pricing_scheme {fixed_price {currency_code, value}}}`, `payment_preferences {auto_bill_outstanding, setup_fee_failure_action: CONTINUE|CANCEL, payment_failure_threshold}`. At most one REGULAR cycle. Response 200 or 201 with plan `id`.

`POST /v1/billing/subscriptions`: `plan_id`, `start_time`, `quantity`, `subscriber {email_address, name}`, `custom_id`, `application_context {return_url, cancel_url, user_action: CONTINUE|SUBSCRIBE_NOW}`. Response: `id` (`I-...`), `status` `APPROVAL_PENDING`, `links[]` with `rel: approve`. The buyer must open the approve link and consent as the sandbox personal account. No API shortcut for that step.

`GET /v1/billing/subscriptions/{id}`: `status` enum `APPROVAL_PENDING, APPROVED, ACTIVE, SUSPENDED, CANCELLED, EXPIRED`, `status_update_time`, `plan_id`, `start_time`, `quantity`, `subscriber`, `custom_id`, `create_time`, `billing_info {outstanding_balance, last_payment {amount, time}, next_billing_time, failed_payments_count, cycle_executions[]}`. Query `fields=plan,last_failed_payment` for more.

`GET /v1/billing/subscriptions/{id}/transactions?start_time=...&end_time=...`: `transactions[] {id, status, amount_with_breakdown {gross_amount, fee_amount, net_amount}, payer_email, time}`.

`POST /v1/billing/subscriptions/{id}/cancel`: body `{"reason": "..."}`, response 204.
`POST /v1/billing/subscriptions/{id}/suspend`: body `{"reason": "..."}`, response 204.
`POST /v1/billing/subscriptions/{id}/activate`: reactivates a suspended one.
`POST /v1/billing/subscriptions/{id}/revise`: `plan_id`, `quantity`, `application_context`. Changing plan may need buyer approval again (links in response).
`GET /v1/billing/plans`, `GET /v1/billing/plans/{id}`, `POST /v1/billing/plans/{id}/update-pricing-schemes` (price change for a plan; the subscription then bills the new price, which is the "silent price increase" scenario).

These endpoints are called by the merchant that owns the plan. In the sandbox Lupa's business account is that merchant, so cancel and suspend are real calls. On a live personal account the buyer has no such API.

## 6. Webhooks

Register a webhook in the Developer Dashboard (app, Webhooks) or via `POST /v1/notifications/webhooks` with `url` and `event_types[]`. Needs a public HTTPS URL. Verify signatures with `POST /v1/notifications/verify-webhook-signature` (headers `PAYPAL-TRANSMISSION-ID`, `PAYPAL-TRANSMISSION-TIME`, `PAYPAL-CERT-URL`, `PAYPAL-AUTH-ALGO`, `PAYPAL-TRANSMISSION-SIG`, plus `webhook_id` and the event body). Verify the exact field names from the Webhooks API page before coding.

Events that matter:
- `PAYMENT.AUTHORIZATION.CREATED`, `PAYMENT.AUTHORIZATION.VOIDED`
- `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.PENDING`, `PAYMENT.CAPTURE.DECLINED`, `PAYMENT.CAPTURE.REFUNDED`, `PAYMENT.CAPTURE.REVERSED`
- `PAYMENT.SALE.COMPLETED` (subscription charges arrive as sales), `PAYMENT.SALE.PENDING`, `PAYMENT.SALE.DENIED`, `PAYMENT.SALE.REFUNDED`, `PAYMENT.SALE.REVERSED`
- `BILLING.SUBSCRIPTION.CREATED`, `ACTIVATED`, `UPDATED`, `EXPIRED`, `CANCELLED`, `SUSPENDED`, `PAYMENT.FAILED`
- `BILLING.PLAN.CREATED`, `UPDATED`, `ACTIVATED`, `PRICING-CHANGE.ACTIVATED`, `DEACTIVATED`

Simulate events without a public URL: Developer Dashboard, Webhooks simulator (verify it still exists), or post a recorded event body to the local receiver in tests.

## 7. PayPal Agent Toolkit and MCP

- `npm install @paypal/agent-toolkit`, Node 18+. TypeScript only; works with Vercel AI SDK tools and as an MCP server. No Python package.
- Env: `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` or `PAYPAL_ACCESS_TOKEN`, `PAYPAL_ENVIRONMENT=SANDBOX`.
- Code: `new PayPalAgentToolkit({clientId, clientSecret, configuration: {context: {sandbox: true}, actions: {orders: {create: true, get: true}, subscriptions: {...}}}})`, then `getTools()`.
- Tools: invoices (20), payments (`create_order`, `get_order`, `pay_order`, `create_refund`, `get_refund`), disputes (3), shipment tracking (3), catalog (`create_product`, `list_products`, `show_product_details`), subscriptions (`create_subscription_plan`, `list_subscription_plans`, `show_subscription_plan_details`, `create_subscription`, `show_subscription_details`, `update_subscription`, `cancel_subscription`), reporting (`list_transactions`, `get_merchant_insights`).
- No authorize, capture or void tool. Those go to the REST API directly.
- Built for business accounts. It gives an agent the merchant's whole credential. That is the thing Lupa's MCP layer sits in front of.

## 8. Sandbox accounts

- Signing up as a developer creates one business and one personal sandbox account (`sb-xxx@business.example.com`, `sb-xxx@personal.example.com`).
- More accounts: Developer Dashboard, Sandbox, Accounts, Create Account (Personal or Business, pick country Finland for EUR). Clone an account to copy its balance.
- Log in at `https://www.sandbox.paypal.com` with the sandbox email and password to act as the buyer (approve subscriptions, view the buyer's own automatic payments page).
- New accounts get a default balance. Edit it when cloning.
- Several business accounts can play several merchants. Each needs its own REST app if its credentials are used; one app is enough if Lupa plays one merchant.

## 9. Facts to verify in the spike

1. Card `payment_source` on a sandbox order without a browser approval step, and which app feature it needs.
2. Transaction Search enabled on the app, and the reference type values seen for a subscription charge (expect `SUB`) and a one-off order (expect `ODR` or `TXN`).
3. The 3-hour delay in practice.
4. Partial capture with `final_capture: true`, then status `CAPTURED`; void on an untouched authorization, status `VOIDED`.
5. Subscription approve link flow with the sandbox personal account, then `status: ACTIVE`.
6. Whether the webhook simulator exists and whether a tunnel (cloudflared, ngrok) is worth the time. Polling is the fallback.
