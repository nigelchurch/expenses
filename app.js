'use strict';
/* Expenses PWA — plain JS, talks to Supabase Auth + REST directly (no library). */

const CFG = window.APP_CONFIG;
const BASE = CFG.SUPABASE_URL.replace(/\/+$/, '');
const KEY = CFG.SUPABASE_ANON_KEY;
const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const PAGE_TITLES = { add: 'Add expenses', history: 'History', filter: 'Filter', budget: 'Budget', import: 'Import history' };

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/* ---------- storage (wrapped: storage can throw in odd contexts) ---------- */
const store = {
  get(k, def) { try { const v = localStorage.getItem('exp.' + k); return v == null ? def : JSON.parse(v); } catch { return def; } },
  set(k, v) { try { localStorage.setItem('exp.' + k, JSON.stringify(v)); } catch { /* ignore */ } },
  del(k) { try { localStorage.removeItem('exp.' + k); } catch { /* ignore */ } },
};

/* ---------- formatting ---------- */
// "2026-11-01" -> "1 NOV 26"  (Excel recognises this as a date when pasted)
function fmtDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return `${d} ${MONTHS[m - 1]} ${String(y).slice(-2)}`;
}
function fmtMonthHeading(iso) {
  const [y, m] = iso.split('-').map(Number);
  return `${MONTH_NAMES[m - 1]} ${y}`;
}
// Money in is stored negative. On screen it shows without the minus, in green (amtHtml); exports keep the minus.
function fmtAmount(n) {
  return CFG.CURRENCY + Math.abs(n).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
const amtHtml = n => `<span class="${n < 0 ? 'inc' : ''}">${fmtAmount(n)}</span>`;
function currentMonthIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
}
// "12.50", "-3", "1,234.56", "£12", "12,5" -> number, or NaN
function parseAmount(s) {
  let t = String(s ?? '').trim().replace(/[£€$\s]/g, '');
  if (/^\(.*\)$/.test(t)) t = '-' + t.slice(1, -1); // (12.00) accounting negative
  if (t.includes(',') && !t.includes('.') && /,\d{1,2}$/.test(t)) t = t.replace(',', '.');
  else t = t.replace(/,/g, '');
  if (!/^[+-]?\d*\.?\d+$/.test(t)) return NaN;
  return Math.round(parseFloat(t) * 100) / 100;
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  return hexToUuid(b);
}
function hexToUuid(bytes) {
  const b = Array.from(bytes.slice(0, 16));
  b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
  const h = b.map(x => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}
async function stableUuid(text) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return hexToUuid(new Uint8Array(buf));
}

/* ---------- auth ---------- */
class OfflineError extends Error {}
class AuthError extends Error {}

let session = store.get('session', null);

async function authRequest(grant, body) {
  let res;
  try {
    res = await fetch(`${BASE}/auth/v1/token?grant_type=${grant}`, {
      method: 'POST',
      headers: { apikey: KEY, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch { throw new OfflineError('No connection'); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new AuthError(data.error_description || data.msg || data.message || `Sign-in failed (${res.status})`);
  return data;
}
function saveSession(data, name) {
  session = {
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    expires_at: data.expires_at || Math.floor(Date.now() / 1000) + (data.expires_in || 3600),
    name,
  };
  store.set('session', session);
}
async function login(name, password) {
  const email = `${name.trim().toLowerCase()}@${CFG.USER_DOMAIN}`;
  const data = await authRequest('password', { email, password });
  saveSession(data, name.trim());
}
let refreshing = null;
async function refreshSession() {
  if (!refreshing) {
    refreshing = authRequest('refresh_token', { refresh_token: session.refresh_token })
      .then(d => saveSession(d, session.name))
      .finally(() => { refreshing = null; });
  }
  return refreshing;
}
async function accessToken() {
  if (!session) throw new AuthError('Not signed in');
  if (session.expires_at - 60 < Date.now() / 1000) await refreshSession();
  return session.access_token;
}
function logout() {
  const tok = session?.access_token;
  if (tok) fetch(`${BASE}/auth/v1/logout`, { method: 'POST', headers: { apikey: KEY, Authorization: `Bearer ${tok}` } }).catch(() => {});
  session = null;
  store.del('session');
  store.del('cache');
  showLogin();
}

/* ---------- REST ---------- */
async function api(path, { method = 'GET', headers = {}, body } = {}, retried = false) {
  const tok = await accessToken();
  let res;
  try {
    res = await fetch(`${BASE}/rest/v1/${path}`, {
      method,
      headers: { apikey: KEY, Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json', ...headers },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch { throw new OfflineError('No connection'); }
  if (res.status === 401 && !retried) {
    await refreshSession();
    return api(path, { method, headers, body }, true);
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.message || `Server error ${res.status}`);
  }
  return res;
}

/* ---------- outbox (expenses waiting to upload) ---------- */
let outbox = store.get('outbox', []);
let flushing = null;

function queue(rows) {
  outbox.push(...rows);
  store.set('outbox', outbox);
  updateBanner();
}
async function flushOutbox() {
  if (flushing) return flushing;
  flushing = (async () => {
    let sent = 0;
    while (outbox.length) {
      const chunk = outbox.slice(0, 500);
      await api('expenses?on_conflict=client_id', {
        method: 'POST',
        headers: { Prefer: 'resolution=ignore-duplicates,return=minimal' },
        body: chunk.map(({ month, category, amount, comment, created_by, client_id }) =>
          ({ month, category, amount, comment, created_by, client_id })),
      });
      const done = new Set(chunk.map(r => r.client_id));
      outbox = outbox.filter(r => !done.has(r.client_id));
      store.set('outbox', outbox);
      sent += chunk.length;
    }
    return sent;
  })().finally(() => { flushing = null; updateBanner(); });
  return flushing;
}

/* ---------- server data cache ---------- */
let cache = store.get('cache', { rows: [], fetchedAt: null });

async function fetchAll() {
  const rows = [];
  const PAGE = 1000;
  for (let from = 0; ; from += PAGE) {
    const res = await api('expenses?select=id,month,category,amount,comment,created_by,created_at,client_id&order=month.desc,id.desc', {
      headers: { 'Range-Unit': 'items', Range: `${from}-${from + PAGE - 1}` },
    });
    const page = await res.json();
    rows.push(...page);
    if (page.length < PAGE) break;
  }
  rows.forEach(r => { r.amount = Number(r.amount); });
  cache = { rows, fetchedAt: new Date().toISOString() };
  store.set('cache', cache);
}

// Server rows plus anything still waiting in the outbox, newest month first
function allRows() {
  const seen = new Set(cache.rows.map(r => r.client_id).filter(Boolean));
  const pending = outbox.filter(r => !seen.has(r.client_id)).map(r => ({ ...r, pending: true }));
  return [...pending, ...cache.rows].sort((a, b) => (a.month < b.month ? 1 : a.month > b.month ? -1 : 0));
}

let syncing = false;
async function sync({ quiet = true } = {}) {
  if (!session || syncing) return;
  syncing = true;
  try {
    if (outbox.length) await flushOutbox();
    await fetchAll();
    setNet(true);
  } catch (e) {
    if (e instanceof OfflineError) setNet(false);
    if (e instanceof AuthError) { logout(); $('#login-error').textContent = 'Please sign in again.'; return; }
    if (!quiet) toast(e instanceof OfflineError ? 'Offline — showing saved copy' : e.message);
  } finally {
    syncing = false;
    renderCurrent();
  }
}

/* ---------- UI: screens & navigation ---------- */
let currentPage = 'add';

function showLogin() {
  $('#app').hidden = true;
  $('#login').hidden = false;
  $('#login-pass').value = '';
  if (!/^https:\/\/.+/.test(BASE) || BASE.includes('YOUR-PROJECT')) {
    $('#login-error').textContent = 'App not set up yet: fill in config.js.';
  }
}
function showApp() {
  $('#login').hidden = true;
  $('#app').hidden = false;
  $('#user-name').textContent = session.name;
  updateBanner();
  updateNet();
  showPage(currentPage);
  sync();
}
function showPage(page) {
  currentPage = page;
  for (const p of ['add', 'history', 'filter', 'budget', 'import']) $(`#page-${p}`).hidden = p !== page;
  $$('.tabs button').forEach(b => b.classList.toggle('active', b.dataset.page === page));
  $('#page-title').textContent = PAGE_TITLES[page];
  $('#menu').hidden = true;
  renderCurrent();
  window.scrollTo(0, 0);
}
function renderCurrent() {
  if (currentPage === 'history') renderHistory();
  if (currentPage === 'filter') renderFilter();
  if (currentPage === 'budget') renderBudget();
  if (currentPage === 'add') updateCatLabels(form());
}

/* ---------- Budget ---------- */
// spent[month][category] = total, from server rows + rows waiting to upload
function spending() {
  const s = {};
  for (const r of allRows()) {
    const m = (s[r.month] ||= {});
    m[r.category] = (m[r.category] || 0) + r.amount;
  }
  return s;
}
const pctOf = (spent, budget) => Math.round((spent / budget) * 100);
// Show "Groceries (food) · 70%" in a line's drop-down, for that line's month
function updateCatLabels(node, spent = spending()) {
  const month = `${$('.l-month', node).value}-01`;
  const used = spent[month] || {};
  for (const o of $('.l-cat', node).options) {
    const b = CFG.BUDGETS[o.value];
    o.textContent = b ? `${o.value} · ${pctOf(used[o.value] || 0, b)}%` : o.value;
  }
}
let budgetMonth = currentMonthIso();
function shiftMonth(iso, n) {
  const [y, m] = iso.split('-').map(Number);
  const d = new Date(y, m - 1 + n, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
}
function renderBudget() {
  const used = spending()[budgetMonth] || {};
  $('#b-month').textContent = fmtMonthHeading(budgetMonth);
  $('#b-next').disabled = budgetMonth >= currentMonthIso();
  let totSpent = 0, totBudget = 0, html = '';
  for (const cat of CFG.CATEGORIES.filter(c => CFG.BUDGETS[c])) {
    const budget = CFG.BUDGETS[cat], spent = used[cat] || 0, pct = pctOf(spent, budget);
    totSpent += spent; totBudget += budget;
    const over = spent > budget;
    const state = over ? 'over' : pct >= 80 ? 'warn' : '';
    const left = budget - spent;
    html += `<div class="b-row ${state}" title="${esc(cat)}: ${fmtAmount(spent)} of ${fmtAmount(budget)}">
      <div class="b-top"><span>${esc(cat)}</span><span class="b-pct">${over ? '▲ ' : ''}${pct}%</span></div>
      <div class="b-track"><div class="b-fill" style="width:${Math.max(0, Math.min(pct, 100))}%"></div></div>
      <div class="b-sub">${amtHtml(spent)} of ${fmtAmount(budget)} · ${left >= 0 ? `${fmtAmount(left)} left` : `over by ${fmtAmount(-left)}`}</div>
    </div>`;
  }
  $('#b-list').innerHTML = html;
  $('#b-total').textContent = `Budgeted categories: ${fmtAmount(totSpent)} of ${fmtAmount(totBudget)} (${pctOf(totSpent, totBudget)}%)`;
  const others = Object.entries(used).filter(([c]) => !CFG.BUDGETS[c]);
  $('#b-other').innerHTML = others.length
    ? `<h3>No budget set</h3><div id="f-list">${others.map(([c, v]) => rowHtml({ category: c, amount: v, comment: '' }).replace('role="button" tabindex="0"', '')).join('')}</div>`
    : '';
}
function updateBanner() {
  const b = $('#outbox-banner');
  b.hidden = !outbox.length;
  b.textContent = `${outbox.length} expense${outbox.length === 1 ? '' : 's'} saved on this phone, waiting to upload.`;
}
// Status comes from real request results where possible; navigator.onLine is only a hint
let netOk = navigator.onLine;
function setNet(ok) { netOk = ok; updateNet(); }
function updateNet() {
  $('#net-status').textContent = netOk && navigator.onLine ? 'Online' : 'Offline';
}
let toastTimer;
function toast(msg) {
  const m = $('#add-msg');
  if (currentPage === 'add') { m.textContent = msg; clearTimeout(toastTimer); toastTimer = setTimeout(() => { m.textContent = ''; }, 6000); }
  else $('#history-info').textContent = msg;
}

/* ---------- Add page ---------- */
// One entry form at the top. "+ New line" moves the entry into a list below it (newest first);
// "Upload expenses" sends the list (plus whatever is still in the form).
let staged = []; // [{ id, month: '2026-11', category, amount: '54.2', comment }]
const form = () => $('#entry');

function categoryOptions(select, selected = '') {
  for (const c of CFG.CATEGORIES) {
    const o = document.createElement('option');
    o.value = o.textContent = c;
    if (c === selected) o.selected = true;
    select.append(o);
  }
}
function setForm(d = {}) {
  const f = form();
  $('.l-month', f).value = d.month || $('.l-month', f).value || currentMonthIso().slice(0, 7);
  $('.l-cat', f).value = d.category || CFG.DEFAULT_CATEGORY;
  const amt = String(d.amount ?? '').trim();
  setType($('.l-type', f), d.type || (amt.startsWith('-') ? 'income' : 'expense'));
  $('.l-amount', f).value = amt.replace(/^-/, '');
  $('.l-comment', f).value = d.comment ?? '';
  f.classList.remove('invalid');
  updateCatLabels(f);
}
function readForm() {
  const f = form();
  return {
    month: $('.l-month', f).value,
    category: $('.l-cat', f).value,
    type: $('.l-type', f).dataset.type,
    amount: $('.l-amount', f).value.trim(),
    comment: $('.l-comment', f).value.trim(),
  };
}
const isBlank = d => !d.amount && !d.comment; // category is always pre-filled, so it doesn't count
const isValid = d => /^\d{4}-\d{2}$/.test(d.month) && !!d.category && !Number.isNaN(parseAmount(d.amount));
function saveDraft() { store.set('draft', { form: readForm(), staged }); }

// Move the form's entry into the list. False (form marked red) if it isn't complete.
function stageForm() {
  const d = readForm();
  if (isBlank(d)) return true;
  if (!isValid(d)) {
    form().classList.add('invalid');
    toast('Month, category and amount are needed.');
    return false;
  }
  staged.unshift({ id: uuid(), ...d, amount: String(signed(d.type, parseAmount(d.amount))) });
  setForm({ month: d.month });
  renderStaged();
  saveDraft();
  return true;
}
function renderStaged() {
  const total = staged.reduce((t, d) => t + parseAmount(d.amount), 0);
  $('#staged-head').hidden = !staged.length;
  $('#staged-head').innerHTML = `Ready to upload: ${staged.length} · ${amtHtml(total)}`;
  $('#staged').innerHTML = staged.map(d => {
    const amt = parseAmount(d.amount);
    return `<div class="staged" data-id="${d.id}">
      <div class="s-main"><span>${esc(d.category)}</span><span class="s-amt">${amtHtml(amt)}</span></div>
      <div class="s-sub">${fmtDate(`${d.month}-01`)}${d.comment ? ` · ${esc(d.comment)}` : ''}</div>
      <button type="button" class="s-edit small-btn">Edit</button>
    </div>`;
  }).join('');
}
// Put a listed entry back into the form (anything already in the form goes to the list first)
function editStaged(id) {
  if (!stageForm()) return;
  const i = staged.findIndex(d => d.id === id);
  if (i < 0) return;
  const [d] = staged.splice(i, 1);
  setForm(d);
  renderStaged();
  saveDraft();
  window.scrollTo(0, 0);
}
// Income / Expense button: expense is the default; income is stored as a negative amount
function setType(btn, type) {
  btn.dataset.type = type;
  btn.textContent = type === 'income' ? 'Income' : 'Expense';
  btn.classList.toggle('income', type === 'income');
  btn.setAttribute('aria-pressed', String(type === 'income'));
}
const toggleType = btn => setType(btn, btn.dataset.type === 'income' ? 'expense' : 'income');
const signed = (type, n) => (type === 'income' ? -Math.abs(n) : Math.abs(n));
async function uploadLines() {
  if (!stageForm()) return;
  if (!staged.length) { toast('Nothing to upload yet.'); return; }
  const rows = staged.slice().reverse().map(d => ({
    month: `${d.month}-01`, category: d.category, amount: parseAmount(d.amount), comment: d.comment,
    created_by: session.name, client_id: d.id,
  }));
  queue(rows);
  staged = [];
  renderStaged();
  saveDraft();
  $('#upload').disabled = true;
  try {
    await flushOutbox();
    setNet(true);
    toast(`${rows.length} expense${rows.length === 1 ? '' : 's'} uploaded ✓`);
    sync();
  } catch (e) {
    if (e instanceof AuthError) { logout(); return; }
    if (e instanceof OfflineError) setNet(false);
    toast(e instanceof OfflineError
      ? `No connection — ${rows.length} saved on this phone and will upload automatically.`
      : `Saved on this phone; upload failed: ${e.message}`);
  } finally {
    $('#upload').disabled = false;
  }
}

/* ---------- History page ---------- */
const rowKey = r => (r.pending ? `cid:${r.client_id}` : `id:${r.id}`);
function rowHtml(r, showDate = false) {
  const sub = [showDate ? fmtDate(r.month) : '', r.comment].filter(Boolean).map(esc).join(' · ');
  return `<div class="row${r.pending ? ' pending' : ''}" data-key="${esc(rowKey(r))}" role="button" tabindex="0">
    <span class="r-cat">${esc(r.category)}</span>
    <span class="r-amt">${amtHtml(r.amount)}</span>
    ${sub ? `<span class="r-sub">${sub}</span>` : ''}
  </div>`;
}
// Month rows are only built when a month is opened (thousands of rows otherwise)
let historyGroups = new Map();
function fillMonth(details) {
  const box = $('.rows', details);
  if (details.open && !box.childElementCount) box.innerHTML = (historyGroups.get(details.dataset.month) || []).map(r => rowHtml(r)).join('');
}
function renderHistory() {
  const rows = allRows();
  historyGroups = new Map();
  for (const r of rows) {
    if (!historyGroups.has(r.month)) historyGroups.set(r.month, []);
    historyGroups.get(r.month).push(r);
  }
  const cur = currentMonthIso();
  const openNow = new Set($$('#history-list details[open]').map(d => d.dataset.month));
  const firstRender = !$('#history-list details');
  let html = '';
  for (const [month, items] of historyGroups) {
    const total = items.reduce((s, r) => s + r.amount, 0);
    const open = firstRender ? month === cur : (openNow.has(month) || (month === cur && !$(`#history-list details[data-month="${month}"]`)));
    html += `<details class="month" data-month="${month}"${open ? ' open' : ''}>
      <summary><span class="m-name">${fmtMonthHeading(month)}</span>
        <span class="m-meta">${items.length} · ${amtHtml(total)}</span></summary>
      <div class="rows"></div>
    </details>`;
  }
  $('#history-list').innerHTML = html || '<p class="muted">No expenses yet.</p>';
  $$('#history-list details[open]').forEach(fillMonth);
  $('#history-info').textContent = cache.fetchedAt
    ? `${rows.length} expenses · last synced ${new Date(cache.fetchedAt).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })}`
    : (navigator.onLine ? 'Loading…' : 'Offline — nothing saved on this phone yet.');
}

/* ---------- Filter page ---------- */
function renderFilter() {
  const rows = allRows();
  const fCat = $('#f-cat'), fMonth = $('#f-month');
  const selCat = fCat.value, selMonth = fMonth.value;

  const cats = [...new Set([...CFG.CATEGORIES, ...rows.map(r => r.category)])];
  fCat.innerHTML = '<option value="">All categories</option>' + cats.map(c => `<option${c === selCat ? ' selected' : ''}>${esc(c)}</option>`).join('');
  const months = [...new Set(rows.map(r => r.month))];
  fMonth.innerHTML = '<option value="">All months</option>' + months.map(m => `<option value="${m}"${m === selMonth ? ' selected' : ''}>${fmtMonthHeading(m)}</option>`).join('');

  const hits = filteredRows();
  const total = hits.reduce((s, r) => s + r.amount, 0);
  $('#f-summary').innerHTML = `${hits.length} item${hits.length === 1 ? '' : 's'} · total ${amtHtml(total)}`;
  $('#f-list').innerHTML = hits.slice(0, FILTER_SHOW).map(r => rowHtml(r, true)).join('');
  $('#f-more').hidden = hits.length <= FILTER_SHOW;
  $('#f-more').textContent = `Showing the newest ${FILTER_SHOW} of ${hits.length}. Narrow the filters to see more — the total and Copy for Excel include all ${hits.length}.`;
  $('#f-copy').disabled = !hits.length;
}
const FILTER_SHOW = 300;

/* ---------- Edit / delete ---------- */
let editing = null;
function openEditor(key) {
  const r = allRows().find(x => rowKey(x) === key);
  if (!r) return;
  editing = r;
  const sel = $('#e-cat');
  sel.innerHTML = '';
  categoryOptions(sel, r.category);
  if (!CFG.CATEGORIES.includes(r.category)) {
    const o = document.createElement('option'); o.value = o.textContent = r.category; o.selected = true; sel.prepend(o);
  }
  $('#e-month').value = r.month.slice(0, 7);
  setType($('#e-type'), r.amount < 0 ? 'income' : 'expense');
  $('#e-amount').value = Math.abs(r.amount).toFixed(2);
  $('#e-comment').value = r.comment || '';
  $('#e-msg').textContent = r.pending ? 'Not uploaded yet — changes stay on this phone until it uploads.' : '';
  $('#edit-dlg').showModal();
}
async function saveEdit(del = false) {
  const r = editing;
  const amount = signed($('#e-type').dataset.type, parseAmount($('#e-amount').value));
  const month = $('#e-month').value;
  if (!del && (Number.isNaN(amount) || !/^\d{4}-\d{2}$/.test(month))) { $('#e-msg').textContent = 'Month and amount are needed.'; return; }
  if (del && !confirm(`Delete ${r.category} ${fmtAmount(r.amount)}?`)) return;
  const fields = { month: `${month}-01`, category: $('#e-cat').value, amount, comment: $('#e-comment').value.trim() };

  if (r.pending) {
    outbox = del ? outbox.filter(x => x.client_id !== r.client_id)
      : outbox.map(x => (x.client_id === r.client_id ? { ...x, ...fields } : x));
    store.set('outbox', outbox);
    updateBanner();
  } else {
    $$('#edit-dlg button').forEach(b => { b.disabled = true; });
    try {
      await api(`expenses?id=eq.${r.id}`, del
        ? { method: 'DELETE', headers: { Prefer: 'return=minimal' } }
        : { method: 'PATCH', headers: { Prefer: 'return=minimal' }, body: { ...fields, updated_at: new Date().toISOString() } });
      setNet(true);
      cache.rows = del ? cache.rows.filter(x => x.id !== r.id) : cache.rows.map(x => (x.id === r.id ? { ...x, ...fields } : x));
      store.set('cache', cache);
    } catch (e) {
      if (e instanceof AuthError) { $('#edit-dlg').close(); logout(); return; }
      if (e instanceof OfflineError) setNet(false);
      $('#e-msg').textContent = e instanceof OfflineError ? 'No connection — changing or deleting needs the internet. Try again when online.' : e.message;
      return;
    } finally {
      $$('#edit-dlg button').forEach(b => { b.disabled = false; });
    }
  }
  $('#edit-dlg').close();
  renderCurrent();
}
function filteredRows() {
  const c = $('#f-cat').value, m = $('#f-month').value;
  return allRows().filter(r => (!c || r.category === c) && (!m || r.month === m));
}
async function copyForExcel() {
  const clean = s => String(s ?? '').replace(/[\t\r\n]+/g, ' ');
  const tsv = ['Date\tCategory\tAmount\tComment',
    ...filteredRows().map(r => [fmtDate(r.month), clean(r.category), r.amount.toFixed(2), clean(r.comment)].join('\t'))].join('\r\n');
  try { await navigator.clipboard.writeText(tsv); $('#f-copy').textContent = 'Copied ✓'; }
  catch { $('#f-copy').textContent = 'Copy failed'; }
  setTimeout(() => { $('#f-copy').textContent = 'Copy for Excel'; }, 2500);
}

/* ---------- Import page ---------- */
const MONTH_LOOKUP = Object.fromEntries(MONTH_NAMES.flatMap((n, i) => [[n.toLowerCase(), i + 1], [n.slice(0, 3).toLowerCase(), i + 1]]));
MONTH_LOOKUP.sept = 9;

// Accepts: 1 Nov 26, 1-Nov-2026, Nov-26, November 2026, 01/11/2026, 2026-11-01, Excel serial (46327)
function parseMonth(s) {
  const t = String(s ?? '').trim();
  let y, m, mm;
  if ((mm = t.match(/^(\d{4})-(\d{1,2})(?:-\d{1,2})?/))) { y = +mm[1]; m = +mm[2]; }
  else if ((mm = t.match(/^\d{1,2}[/.](\d{1,2})[/.](\d{2,4})$/))) { m = +mm[1]; y = +mm[2]; }
  else if ((mm = t.match(/^(?:\d{1,2}[\s-]+)?([A-Za-z]+)[\s\-,']+(\d{2,4})$/))) { m = MONTH_LOOKUP[mm[1].toLowerCase()]; y = +mm[2]; }
  else if ((mm = t.match(/^\d{5}(\.\d+)?$/))) {
    const d = new Date(Date.UTC(1899, 11, 30) + Math.floor(+t) * 86400000);
    y = d.getUTCFullYear(); m = d.getUTCMonth() + 1;
  }
  if (!m || m < 1 || m > 12 || !y) return null;
  if (y < 100) y += 2000;
  return `${y}-${String(m).padStart(2, '0')}-01`;
}
let importRows = [];
async function checkImport() {
  const lines = $('#imp-text').value.split(/\r?\n/).filter(l => l.trim());
  const catMap = new Map(CFG.CATEGORIES.map(c => [c.toLowerCase(), c]));
  importRows = [];
  const report = [];
  let errors = 0;
  for (let i = 0; i < lines.length; i++) {
    const cells = lines[i].split('\t');
    const month = parseMonth(cells[0]);
    const amount = parseAmount(cells[2]);
    if (i === 0 && !month && Number.isNaN(amount)) continue; // header row
    const rawCat = (cells[1] || '').trim();
    const category = catMap.get(rawCat.toLowerCase()) || rawCat;
    const comment = cells.slice(3).join(' ').trim();
    const probs = [];
    if (!month) probs.push('date?');
    if (!category) probs.push('category missing');
    else if (!catMap.has(category.toLowerCase())) probs.push('new category');
    if (Number.isNaN(amount)) probs.push('amount?');
    const fatal = !month || !category || Number.isNaN(amount);
    if (fatal) errors++;
    if (probs.length) report.push(`<tr><td>${i + 1}</td><td class="${fatal ? 'bad' : ''}">${esc(probs.join(', '))}</td><td>${esc(lines[i])}</td></tr>`);
    if (!fatal) importRows.push({ month, category, amount, comment, created_by: session.name, client_id: await stableUuid(`${i}|${lines[i]}`) });
  }
  const newCats = [...new Set(importRows.map(r => r.category).filter(c => !catMap.has(c.toLowerCase())))];
  $('#imp-result').innerHTML =
    `<p><b>${importRows.length}</b> rows ready${errors ? `, <span class="bad"><b>${errors}</b> rows with errors (fix and Check again)</span>` : ''}.` +
    (newCats.length ? ` Categories not in the list (will be kept as-is): ${newCats.map(esc).join(', ')}.` : '') + '</p>' +
    (report.length ? `<table>${report.slice(0, 200).join('')}</table>` : '');
  $('#imp-go').disabled = !importRows.length || errors > 0;
}
async function runImport() {
  $('#imp-go').disabled = true;
  queue(importRows);
  const n = importRows.length;
  importRows = [];
  try {
    await flushOutbox();
    $('#imp-result').innerHTML = `<p><b>${n}</b> rows uploaded ✓ (uploading the same paste again will not create duplicates).</p>`;
    $('#imp-text').value = '';
    sync();
  } catch (e) {
    $('#imp-result').innerHTML = `<p class="bad">Saved on this phone, upload not finished: ${esc(e.message)}. It will retry automatically.</p>`;
  }
}

/* ---------- wiring ---------- */
function init() {
  $('#login-form').addEventListener('submit', async e => {
    e.preventDefault();
    const btn = $('#login-form button');
    btn.disabled = true;
    $('#login-error').textContent = '';
    try {
      await login($('#login-name').value, $('#login-pass').value);
      showApp();
    } catch (err) {
      $('#login-error').textContent = err instanceof OfflineError ? 'No connection — sign-in needs the internet.'
        : /invalid/i.test(err.message) ? 'Wrong name or password.' : err.message;
    } finally { btn.disabled = false; }
  });

  $$('.tabs button').forEach(b => b.addEventListener('click', () => showPage(b.dataset.page)));
  $('#menu-btn').addEventListener('click', e => { e.stopPropagation(); $('#menu').hidden = !$('#menu').hidden; });
  document.addEventListener('click', e => { if (!$('#menu').contains(e.target)) $('#menu').hidden = true; });
  $('#menu').addEventListener('click', e => {
    const a = e.target.closest('button')?.dataset.action;
    if (a === 'import') showPage('import');
    if (a === 'refresh') { $('#menu').hidden = true; sync({ quiet: false }); }
    if (a === 'logout') {
      if (outbox.length && !confirm(`${outbox.length} expenses have not uploaded yet. They stay on this phone and upload after the next sign-in. Sign out?`)) return;
      $('#menu').hidden = true;
      logout();
    }
  });

  const f = form();
  categoryOptions($('.l-cat', f), CFG.DEFAULT_CATEGORY);
  $('#add-line').addEventListener('click', stageForm);
  $('#upload').addEventListener('click', uploadLines);
  f.addEventListener('input', saveDraft);
  f.addEventListener('change', saveDraft);
  $('.l-month', f).addEventListener('change', () => updateCatLabels(f));
  $('.l-type', f).addEventListener('click', () => { toggleType($('.l-type', f)); saveDraft(); });
  $('.l-del', f).addEventListener('click', () => { setForm({ month: $('.l-month', f).value }); saveDraft(); });
  $('#staged').addEventListener('click', e => { const b = e.target.closest('.s-edit'); if (b) editStaged(b.closest('.staged').dataset.id); });
  $('#e-type').addEventListener('click', () => toggleType($('#e-type')));

  $('#f-cat').addEventListener('change', renderFilter);
  $('#f-month').addEventListener('change', renderFilter);
  $('#f-copy').addEventListener('click', copyForExcel);
  $('#b-prev').addEventListener('click', () => { budgetMonth = shiftMonth(budgetMonth, -1); renderBudget(); });
  $('#b-next').addEventListener('click', () => { budgetMonth = shiftMonth(budgetMonth, 1); renderBudget(); });

  $('#history-list').addEventListener('toggle', e => fillMonth(e.target), true);
  for (const list of ['#history-list', '#f-list']) {
    $(list).addEventListener('click', e => { const row = e.target.closest('.row'); if (row) openEditor(row.dataset.key); });
    $(list).addEventListener('keydown', e => { const row = e.target.closest('.row'); if (row && e.key === 'Enter') openEditor(row.dataset.key); });
  }
  $('#e-save').addEventListener('click', () => saveEdit(false));
  $('#e-del').addEventListener('click', () => saveEdit(true));
  $('#e-cancel').addEventListener('click', () => $('#edit-dlg').close());

  $('#imp-check').addEventListener('click', checkImport);
  $('#imp-text').addEventListener('input', () => { $('#imp-go').disabled = true; });
  $('#imp-go').addEventListener('click', runImport);

  window.addEventListener('online', () => { setNet(true); sync(); });
  window.addEventListener('offline', () => setNet(false));
  // Keep retrying anything waiting to upload (covers Wi-Fi without internet, missed 'online' events)
  setInterval(() => { if (session && outbox.length && document.visibilityState === 'visible') sync(); }, 20000);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') sync(); });

  // Restore the unsent list, and the form only if something was typed in (else it starts fresh on the default)
  const draft = store.get('draft', {});
  staged = Array.isArray(draft.staged) ? draft.staged : [];
  setForm(draft.form && !isBlank(draft.form) ? draft.form : {});
  renderStaged();

  if (session) showApp(); else showLogin();

  // On this PC (VS Code Live Server etc.) skip the offline cache so every refresh shows the latest files.
  // Add ?sw to the address to test offline/install behaviour locally.
  const localDev = ['localhost', '127.0.0.1'].includes(location.hostname) && !new URLSearchParams(location.search).has('sw');
  if (localDev && 'serviceWorker' in navigator) {
    navigator.serviceWorker.getRegistrations().then(rs => rs.forEach(r => r.unregister())).catch(() => {});
    if (window.caches) caches.keys().then(ks => ks.forEach(k => caches.delete(k))).catch(() => {});
  } else if ('serviceWorker' in navigator) {
    const hadController = !!navigator.serviceWorker.controller;
    navigator.serviceWorker.register('sw.js').catch(() => {});
    navigator.serviceWorker.addEventListener('controllerchange', () => { if (hadController) location.reload(); });
  }
}
init();
