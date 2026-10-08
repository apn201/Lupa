// Lupa UI. Vanilla JS, no build step. Every number shown comes from the API (the ledger).
const API = "/proposed/v1/me";
const MARK = { "●": "m-paypal", "◇": "m-proposed", "◆": "m-ai", "■": "m-policy" };
const $ = (s, el = document) => el.querySelector(s);

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function money(cents, cur = "EUR") {
  if (cents === null || cents === undefined) return "–";
  const s = cents < 0 ? "-" : "";
  const a = Math.abs(cents);
  return `${s}${Math.floor(a / 100)}.${String(a % 100).padStart(2, "0")} ${cur}`;
}
function toCents(text) {
  const n = Number(String(text).replace(",", "."));
  return Number.isFinite(n) ? Math.round(n * 100) : NaN;
}
// The ledger stores UTC; show the viewer's local time.
const pad = n => String(n).padStart(2, "0");
function day(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  return isNaN(d) ? iso.slice(0, 10) : `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function stamp(iso) {
  const d = new Date(iso);
  return isNaN(d) ? iso : `${day(iso)} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
function mark(m) { return m ? `<b class="m ${MARK[m] || ""}" title="${esc(m)}">${esc(m)}</b>` : ""; }
const KIND = {
  fixed_recurring: "fixed recurring", variable_recurring: "variable recurring",
  one_time_authority: "one-time authority", agent_authority: "agent authority", unknown: "unknown",
};
const RULE3 = ["allow", "require_approval", "block"];
const ORIGIN = { import_csv: "from export", paypal_sub: "live sandbox", paypal_pap: "live sandbox",
                 paypal_order: "live sandbox", lupa_delegation: "agent authority in Lupa" };

async function call(method, path, body, headers = {}) {
  const res = await fetch(path, {
    method, headers: { "Content-Type": "application/json", ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    const e = json.error || (json.detail && json.detail.code ? json.detail : null) || {};
    throw new Error(e.message || `HTTP ${res.status}`);
  }
  return json;
}

// ------------------------------------------------------------------ screens
const screens = ["permissions", "intent", "queue", "trace"];
function show(name) {
  $("#detail").hidden = true;
  for (const s of screens) $(`#${s}`).hidden = s !== name;
  for (const b of document.querySelectorAll(".tabs button")) b.setAttribute("aria-selected", b.dataset.screen === name);
  history.replaceState(null, "", `#${name}`);
  ({ permissions: loadPermissions, intent: loadIntent, queue: loadQueue, trace: loadTrace })[name]();
}
document.querySelectorAll(".tabs button").forEach(b => b.addEventListener("click", () => show(b.dataset.screen)));

// -------------------------------------------------------------- permissions
let permissions = [];
async function loadPermissions() {
  const { data } = await call("GET", `${API}/payment-permissions`);
  permissions = data.permissions;
  $("#headline").textContent = data.headline.text;
  const groups = {};
  for (const p of permissions) (groups[p.status] ||= []).push(p);
  const order = ["active", "suspended", "dormant", "revoked", "expired"];
  $("#perm-list").innerHTML = order.filter(s => groups[s]).map(s => `
    <h2>${esc(s)} · ${groups[s].length}</h2>
    ${groups[s].map(rowHtml).join("")}`).join("");
  document.querySelectorAll("#perm-list .row").forEach(r => r.addEventListener("click", () => openDetail(r.dataset.id)));
  refreshQueueCount();
}
function rowHtml(p) {
  const chips = p.attention_sentences.map(a => `<span class="chip warn" title="${esc(a.text)}">${esc(a.code)}</span>`).join("");
  return `<button class="row" data-id="${esc(p.id)}">
    <span class="name">${mark(p.marker)} ${esc(p.merchant_alias)}</span>
    <span class="amt">${money(p.last_amount, p.currency)}</span>
    <span class="meta">${esc(p.merchant_category)} · ${esc(KIND[p.kind] || p.kind)} · ${esc(ORIGIN[p.source] || p.source)}</span>
    <span class="meta amt">${day(p.last_payment_at)}</span>
    ${chips ? `<span class="chips">${chips}</span>` : ""}
  </button>`;
}

// ------------------------------------------------------------------ detail
let current = null;
async function openDetail(id) {
  const { data } = await call("GET", `${API}/payment-permissions/${id}`);
  current = data;
  const p = data, prof = p.profile || {}, pol = p.policy || {};
  const cur = p.currency;
  const revokeNote = p.source === "paypal_sub"
    ? "Cancels the subscription in the PayPal sandbox."
    : p.source === "lupa_delegation" ? "Ends this agent authority in Lupa."
    : "PayPal has no buyer-side API for this agreement. Lupa will block it; cancel it in your PayPal settings too.";
  $("#detail-content").innerHTML = `
    <h1>${mark(p.marker)} ${esc(p.merchant_alias)}</h1>
    <p class="note">${esc(p.merchant_category)} · ${esc(KIND[p.kind] || p.kind)} · ${esc(p.status)} · ${esc(p.source)} ${esc(p.external_ref)}</p>
    ${p.attention_sentences.length ? `<div class="card"><b>${mark("■")} Attention</b><ul class="sentences">
      ${p.attention_sentences.map(a => `<li>${esc(a.text)}</li>`).join("")}</ul></div>` : ""}
    ${p.suggestion ? `<div class="card">${mark("◆")} Looks like ${esc(KIND[p.suggestion.kind] || p.suggestion.kind)}.</div>` : ""}
    <h2>Profile</h2>
    <dl class="kv">
      <dt>Payments</dt><dd>${prof.n_payments ?? 0}</dd>
      <dt>Range</dt><dd>${money(prof.amount_min, cur)} – ${money(prof.amount_max, cur)}</dd>
      <dt>Median</dt><dd>${money(prof.amount_median, cur)}</dd>
      <dt>Interval</dt><dd>${prof.interval_days_median ?? "–"} days</dd>
      <dt>Since last</dt><dd>${prof.months_since_last ?? "–"} months</dd>
    </dl>
    <h2>Policy ${mark("■")} ${p.policy_is_default ? "<span class='note'>(account default)</span>" : ""}</h2>
    <dl class="kv">
      <dt>Limit</dt><dd>${money(pol.max_amount, pol.currency)}</dd>
      <dt>Recurring</dt><dd>${esc(pol.recurring)}</dd>
      <dt>Increase</dt><dd>${esc(pol.amount_increase)} over ${esc(pol.increase_tolerance_pct)}%</dd>
      <dt>New merchant</dt><dd>${esc(pol.new_merchant)}</dd>
      <dt>Monthly cap</dt><dd>${pol.max_per_month ? money(pol.max_per_month, pol.currency) : "–"}</dd>
    </dl>
    <div class="actions">
      <button class="btn" id="btn-limit" ${prof.n_payments ? "" : "disabled"}>Suggest a limit</button>
      <button class="btn" id="btn-policy">Set policy</button>
      <button class="btn" id="btn-delegate">Delegate</button>
      <button class="btn" id="btn-pay">Request a payment</button>
      ${p.status === "active" ? `<button class="btn danger" id="btn-revoke">Revoke</button>` : ""}
    </div>
    <p class="note">${p.status === "active" ? esc(revokeNote) : ""}</p>
    <div id="detail-panel"></div>
    ${p.delegations.length ? `<h2>Delegations</h2>${p.delegations.map(d => `<div class="card">
      ${esc(d.agent_id)} may <b>${esc(d.authority)}</b> up to ${money(d.max_amount, cur)}, recurring ${d.recurring_allowed ? "allowed" : "not allowed"},
      until ${day(d.expires_at)} ${d.revoked_at ? "<span class='error'>revoked</span>" : ""}</div>`).join("")}` : ""}
    ${p.requests.length ? `<h2>Requests</h2>${p.requests.map(requestCard).join("")}` : ""}
    <h2>Payments ${mark(p.marker)}</h2>
    <table class="payments">${p.payments.slice().reverse().map(x => `<tr><td>${day(x.at)}</td><td>${esc(x.source)}</td><td>${money(x.amount, x.currency)}</td></tr>`).join("") || "<tr><td>None in the data.</td></tr>"}</table>`;
  $("#detail").hidden = false;
  $("#btn-limit")?.addEventListener("click", suggestLimit);
  $("#btn-policy").addEventListener("click", () => policyForm(pol));
  $("#btn-delegate").addEventListener("click", delegateForm);
  $("#btn-pay").addEventListener("click", payForm);
  $("#btn-revoke")?.addEventListener("click", revoke);
}
$("#detail-close").addEventListener("click", () => { $("#detail").hidden = true; loadPermissions(); });
$("#detail").addEventListener("click", e => { if (e.target.id === "detail") { $("#detail").hidden = true; loadPermissions(); } });
document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("#detail").hidden) { $("#detail").hidden = true; loadPermissions(); } });

function panel(html) { $("#detail-panel").innerHTML = `<div class="card">${html}</div>`; }
function fail(e) { panel(`<span class="error">${esc(e.message)}</span>`); }

async function suggestLimit() {
  try {
    const { data } = await call("GET", `${API}/payment-permissions/${current.id}/suggested-limit`);
    panel(`${mark(data.marker)} ${esc(data.sentence)}
      <p class="note">Candidates ${data.candidates.map(c => money(c, current.currency)).join(", ")}${data.reason_code ? ` · ${esc(data.reason_code)}` : " · AI unavailable, the first candidate was used"}</p>
      <div class="actions"><button class="btn primary" id="use-limit">Use ${money(data.limit, current.currency)}</button></div>`);
    $("#use-limit").addEventListener("click", () => policyForm({ ...(current.policy || {}), max_amount: data.limit }));
  } catch (e) { fail(e); }
}

function selectHtml(name, value) {
  return `<select name="${name}">${RULE3.map(v => `<option ${v === value ? "selected" : ""}>${v}</option>`).join("")}</select>`;
}
function policyForm(pol) {
  panel(`<form class="grid" id="policy-form">
    <label>Limit (${esc(current.currency)})<input name="max_amount" inputmode="decimal" value="${pol.max_amount ? (pol.max_amount / 100).toFixed(2) : ""}" required></label>
    <label>Monthly cap<input name="max_per_month" inputmode="decimal" value="${pol.max_per_month ? (pol.max_per_month / 100).toFixed(2) : ""}"></label>
    <label>Recurring${selectHtml("recurring", pol.recurring || "allow")}</label>
    <label>Amount increase${selectHtml("amount_increase", pol.amount_increase || "require_approval")}</label>
    <label>Tolerance %<input name="increase_tolerance_pct" inputmode="numeric" value="${pol.increase_tolerance_pct ?? 20}"></label>
    <label>New merchant${selectHtml("new_merchant", pol.new_merchant || "require_approval")}</label>
    <div class="actions full"><button class="btn primary">Apply ${mark("■")}</button></div></form>`);
  $("#policy-form").addEventListener("submit", async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = {
      max_amount: toCents(f.get("max_amount")), currency: current.currency,
      recurring: f.get("recurring"), amount_increase: f.get("amount_increase"), new_merchant: f.get("new_merchant"),
      increase_tolerance_pct: Number(f.get("increase_tolerance_pct") || 20),
      max_per_month: f.get("max_per_month") ? toCents(f.get("max_per_month")) : null,
    };
    try { await call("PUT", `${API}/payment-permissions/${current.id}/policy`, body); openDetail(current.id); }
    catch (err) { fail(err); }
  });
}

function delegateForm() {
  const week = new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10);
  panel(`<form class="grid" id="dlg-form">
    <label>Agent id<input name="agent_id" value="shopping-agent" required></label>
    <label>Authority<select name="authority"><option>propose</option><option selected>approve</option></select></label>
    <label>Max per payment (${esc(current.currency)})<input name="max_amount" inputmode="decimal" value="80.00" required></label>
    <label>Change allowed %<input name="amount_change_pct" inputmode="numeric" value="20"></label>
    <label>Min confidence<input name="min_confidence" inputmode="decimal" value="0.95"></label>
    <label>Until<input name="expires" type="date" value="${week}"></label>
    <label class="full"><span><input type="checkbox" name="recurring_allowed" style="width:auto"> May start recurring payments</span></label>
    <div class="actions full"><button class="btn primary">Delegate ${mark("■")}</button></div></form>`);
  $("#dlg-form").addEventListener("submit", async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await call("POST", `${API}/payment-permissions/${current.id}/delegate`, {
        agent_id: f.get("agent_id"), authority: f.get("authority"), max_amount: toCents(f.get("max_amount")),
        amount_change_pct: Number(f.get("amount_change_pct") || 20), min_confidence: Number(f.get("min_confidence") || 0.95),
        recurring_allowed: f.get("recurring_allowed") === "on", expires_at: `${f.get("expires")}T23:59:59Z`,
      });
      openDetail(current.id);
    } catch (err) { fail(err); }
  });
}

function payForm() {
  panel(`<p class="note">Simulate a merchant or an agent asking to be paid through this permission.</p>
    <form class="grid" id="pay-form">
    <label>Amount (${esc(current.currency)})<input name="amount" inputmode="decimal" value="${current.last_amount ? (current.last_amount / 100).toFixed(2) : "10.00"}" required></label>
    <label>Merchant<input name="merchant_alias" value="${esc(current.merchant_alias)}"></label>
    <label>Agent id (optional)<input name="agent" value=""></label>
    <label>Agent confidence (optional)<input name="confidence" inputmode="decimal" value=""></label>
    <label class="full"><span><input type="checkbox" name="is_recurring" style="width:auto" ${current.kind.includes("recurring") ? "checked" : ""}> Recurring</span></label>
    <div class="actions full"><button class="btn primary">Send request ${mark("◇")}</button></div></form>
    <div id="pay-result"></div>`);
  $("#pay-form").addEventListener("submit", async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = { amount: toCents(f.get("amount")), merchant_alias: f.get("merchant_alias"), is_recurring: f.get("is_recurring") === "on" };
    if (f.get("confidence")) body.assessment = { decision: "approve", confidence: Number(f.get("confidence")) };
    const headers = f.get("agent") ? { "X-Lupa-Agent": f.get("agent") } : {};
    try {
      const res = await call("POST", `${API}/payment-permissions/${current.id}/requests`, body, headers);
      $("#pay-result").innerHTML = requestCard(res.data.request, res.paypal);
      refreshQueueCount();
    } catch (err) { $("#pay-result").innerHTML = `<p class="error">${esc(err.message)}</p>`; }
  });
}

async function revoke() {
  if (!confirm(`Revoke ${current.merchant_alias}?`)) return;
  try {
    const { data, paypal } = await call("POST", `${API}/payment-permissions/${current.id}/revoke`);
    await openDetail(current.id);
    panel(data.paypal_action === "cancelled"
      ? `${mark("●")} Subscription cancelled in the PayPal sandbox. ${paypal ? paypal.calls.map(c => `<code>${esc(c.method)} ${esc(c.path)}</code>`).join(" ") : ""}`
      : `${mark("◇")} Revoked in Lupa. ${esc(data.note || "")} <a href="${esc(data.settings_link || "#")}" target="_blank" rel="noopener">PayPal settings</a>`);
  } catch (e) { fail(e); }
}

// --------------------------------------------------------- request cards
function requestCard(r, paypal) {
  const d = r.decision || {};
  const cur = r.currency;
  const ai = d.ai_verdict ? `${mark("◆")} ${esc(d.ai_verdict)} · confidence ${Number(d.ai_confidence).toFixed(2)}` : `${mark("◆")} no assessment`;
  const pp = [];
  if (r.paypal_authorization_id) pp.push(`authorization <code>${esc(r.paypal_authorization_id)}</code>`);
  if (paypal) for (const c of paypal.calls) pp.push(`<code>${esc(c.method)} ${esc(c.path)}</code> ${c.status}${c.paypal_id ? ` → <code>${esc(c.paypal_id)}</code>` : ""}`);
  return `<div class="card">
    <div><span class="verdict v-${esc(d.final)}">${mark("■")} ${esc(d.final || "–")}</span>
      · ${money(r.amount, cur)} · ${esc(r.merchant_alias)} ${r.is_recurring ? "· recurring" : ""} ${r.agent_id ? `· agent ${esc(r.agent_id)}` : ""}
      <span class="note">· ${esc(r.state)}</span></div>
    <ul class="sentences">${(d.sentences || []).map(s => `<li>${esc(s)}</li>`).join("") || "<li>Within your policy.</li>"}</ul>
    <div class="note">${ai}${d.rule_hits && d.rule_hits.length ? ` · rules ${d.rule_hits.map(h => esc(h.rule)).join(", ")}` : ""}</div>
    ${pp.length ? `<div class="note">${mark("●")} ${pp.join(" · ")}</div>` : ""}
  </div>`;
}

// -------------------------------------------------------------------- intent
async function loadIntent() { $("#intent-text").focus(); }
$("#intent-form").addEventListener("submit", async e => {
  e.preventDefault();
  const text = $("#intent-text").value.trim() || $("#intent-text").placeholder;
  $("#intent-result").innerHTML = `<p class="note">Drafting…</p>`;
  try {
    const { data } = await call("POST", `${API}/intent`, { text });
    const p = data.draft;
    $("#intent-result").innerHTML = `<div class="card">
      <b>${mark("◆")} Draft</b>
      <ul class="sentences">${data.sentences.map(s => `<li>${esc(s)}</li>`).join("") || "<li>No change from your current default.</li>"}</ul>
      <h3>${mark("■")} Policy</h3>
      <dl class="kv">
        <dt>Limit</dt><dd>${money(p.max_amount, p.currency)}</dd>
        <dt>Recurring</dt><dd>${esc(p.recurring)}</dd>
        <dt>Increase</dt><dd>${esc(p.amount_increase)} over ${esc(p.increase_tolerance_pct)}%</dd>
        <dt>New merchant</dt><dd>${esc(p.new_merchant)}</dd>
        <dt>Monthly cap</dt><dd>${p.max_per_month ? money(p.max_per_month, p.currency) : "–"}</dd>
      </dl>
      <label class="note">Apply to <select id="intent-target"><option value="">Account default</option>
        ${permissions.filter(x => x.status === "active").map(x => `<option value="${esc(x.id)}">${esc(x.merchant_alias)}</option>`).join("")}</select></label>
      <div class="actions"><button class="btn primary" id="intent-apply">Apply</button><button class="btn" id="intent-discard">Discard</button></div>
      <p class="note">Nothing is stored until you apply. ${esc(data.model)} · ${esc(data.prompt_version)}</p></div>`;
    $("#intent-discard").addEventListener("click", () => { $("#intent-result").innerHTML = ""; });
    $("#intent-apply").addEventListener("click", async () => {
      const target = $("#intent-target").value;
      const path = target ? `${API}/payment-permissions/${target}/policy` : `${API}/policies/default`;
      await call("PUT", path, { ...p, created_by: "ai_draft_accepted", intent_text: text });
      $("#intent-result").innerHTML = `<div class="card">${mark("■")} <b>Policy active.</b></div>`;
    });
  } catch (err) {
    $("#intent-result").innerHTML = `<div class="card error">${esc(err.message)}</div>`;
  }
});

// --------------------------------------------------------------------- queue
async function refreshQueueCount() {
  try {
    const { data } = await call("GET", `${API}/requests?state=held`);
    const c = $("#queue-count");
    c.hidden = !data.length;
    c.textContent = data.length;
  } catch { /* the count is a convenience */ }
}
async function loadQueue() {
  const { data } = await call("GET", `${API}/requests?state=held`);
  $("#queue-list").innerHTML = data.length ? data.map(r => `<div data-id="${esc(r.id)}">${requestCard(r)}
      <div class="actions" style="margin:-4px 0 14px"><button class="btn primary" data-act="approve">Approve</button>
      <button class="btn danger" data-act="reject">Reject</button></div><div class="result"></div></div>`).join("")
    : `<p class="note">Nothing is waiting.</p>`;
  document.querySelectorAll("#queue-list [data-act]").forEach(b => b.addEventListener("click", async () => {
    const box = b.closest("[data-id]");
    try {
      const res = await call("POST", `${API}/requests/${box.dataset.id}/resolve`, { action: b.dataset.act });
      box.innerHTML = requestCard(res.data.request, res.paypal);
      refreshQueueCount();
    } catch (e) { box.querySelector(".result").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  }));
  refreshQueueCount();
}

// --------------------------------------------------------------------- trace
function summary(p) {
  const keep = Object.entries(p || {}).filter(([k, v]) => v !== null && v !== undefined && k !== "calls" && k !== "policy");
  return keep.map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ");
}
async function loadTrace() {
  const { data } = await call("GET", `${API}/events?limit=200`);
  $("#trace-list").innerHTML = data.map(e => `<li><span class="dot">${mark(e.marker)}</span>
    <span class="kind">${esc(e.kind)}</span><span class="when">${esc(stamp(e.at))}</span>
    <div class="payload">${esc(e.ref_id || "")} ${esc(summary(e.payload))}</div></li>`).join("");
}

window.addEventListener("hashchange", () => {
  const h = location.hash.slice(1);
  if (screens.includes(h)) show(h);
});
const start = (location.hash || "").slice(1);
show(screens.includes(start) ? start : "permissions");
