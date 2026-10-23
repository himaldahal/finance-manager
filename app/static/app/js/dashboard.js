import { $, api, emptyState, errorState, formatMoney, formatNumber, h, icon, showError, toast, today } from './core.js';
import { monthLong } from './format.js';
import { budgetRow, catLabel } from './parts.js';
import { openTransactionDialog } from './tx-dialog.js';

function setStat(id, value, note, { tint, warn } = {}) {
  const card = document.getElementById(id);
  const valueNode = card.querySelector('.value');
  valueNode.textContent = value;
  valueNode.classList.remove('pos', 'neg');
  if (tint) valueNode.classList.add(tint);
  card.classList.toggle('warn', Boolean(warn));
  card.querySelector('.note').replaceChildren(...(Array.isArray(note) ? note : [note]));
}

function change(previous, pct, goodWhenUp) {
  if (pct === null || pct === undefined) return Number(previous) === 0 ? 'No data last month' : '';
  const up = pct > 0;
  const good = pct === 0 ? null : up === goodWhenUp;
  return [h('span', { class: good === null ? '' : good ? 'pos' : 'neg', text: `${up ? '+' : ''}${pct}%` }), ' vs last month'];
}

function stamp() {
  const now = new Date();
  $('#updated').textContent = `Updated ${now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

async function loadSummary() {
  const box = $('#summary-error');
  try {
    const data = await api('/api/summary/');
    box.hidden = true;
    $('#month-label').textContent = monthLong(data.month);
    const approx = secondary(data, data.balance);
    setStat('stat-balance', formatMoney(data.balance), data.overdrawn ? 'Overdrawn' : approx || 'Across all accounts',
      { tint: Number(data.balance) < 0 ? 'neg' : null, warn: data.overdrawn });
    setStat('stat-income', formatMoney(data.income), change(data.previous.income, data.changes.income, true));
    setStat('stat-expense', formatMoney(data.expense), change(data.previous.expense, data.changes.expense, false));
    const rate = data.savings_rate === null ? 'No income yet this month' : `Savings rate ${data.savings_rate}%`;
    setStat('stat-net', formatMoney(data.net), rate, { tint: Number(data.net) < 0 ? 'neg' : Number(data.net) > 0 ? 'pos' : null });
    stamp();
  } catch (error) {
    box.replaceChildren(errorState(error.message, loadSummary));
    box.hidden = false;
  }
}

async function loadRecent() {
  const host = $('#recent');
  try {
    const data = await api('/api/transactions/', { query: { page_size: 10 } });
    host.className = '';
    if (!data.transactions.length) {
      host.replaceChildren(emptyState('No transactions yet', 'Add your first one to see it here.',
        h('button', { class: 'btn btn-primary', type: 'button', text: 'Add transaction', 'data-new-transaction': '' })));
      return;
    }
    const list = h('ul', { class: 'mini-list' });
    for (const t of data.transactions.slice(0, 8)) {
      list.append(h('li', {},
        h('span', {}, t.name, h('span', { class: 'sub' }, catLabel(t.category, 'span'), ` · ${t.date}`)),
        h('span', { class: `amt ${t.kind === 'income' ? 'pos' : 'neg'}`, text: (t.kind === 'income' ? '+' : '-') + formatMoney(t.amount) })));
    }
    host.replaceChildren(list);
  } catch (error) {
    host.className = '';
    host.replaceChildren(errorState(error.message, loadRecent));
  }
}

async function loadBudgets() {
  const host = $('#budgets');
  try {
    const data = await api('/api/budgets/');
    host.className = '';
    const items = (data.overall ? [data.overall] : []).concat(data.budgets.slice().sort((a, b) => b.percent - a.percent).slice(0, 5));
    if (!items.length) {
      host.replaceChildren(emptyState('No budgets set', 'Set monthly limits to keep spending in check.',
        h('a', { class: 'btn', href: '/budgets/', text: 'Set a budget' })));
      return;
    }
    const rows = items.map((b) => budgetRow(b));
    if (data.overall) rows.push(h('p', { class: 'small muted', text: `Safe to spend ${formatMoney(data.overall.safe_per_day)} per day for the rest of the month.` }));
    host.replaceChildren(...rows);
  } catch (error) {
    host.className = '';
    host.replaceChildren(errorState(error.message, loadBudgets));
  }
}

async function loadAccounts() {
  const host = $('#accounts');
  try {
    const data = await api('/api/accounts/');
    host.className = '';
    const active = data.accounts.filter((a) => !a.archived);
    host.replaceChildren(h('ul', { class: 'mini-list' }, ...active.map((a) => h('li', {},
      h('span', { class: 'cat-label' }, icon(a.icon, 'cat-icon'), a.name),
      h('span', { class: `amt ${Number(a.balance) < 0 ? 'neg' : ''}`, text: formatMoney(a.balance) })))));
  } catch (error) {
    host.className = '';
    host.replaceChildren(errorState(error.message, loadAccounts));
  }
}

function secondary(data, value) {
  if (!data.secondary || !data.secondary.rate) return '';
  const converted = Number(value) * Number(data.secondary.rate);
  return `\u2248 ${data.secondary.code} ${formatNumber(converted)}`;
}

async function loadInsights() {
  try {
    const data = await api('/api/insights/');
    const card = $('#insights');
    card.hidden = data.sentences.length === 0;
    $('#insight-list').replaceChildren(...data.sentences.map((s) => h('li', { class: s.level },
      icon(s.level === 'bad' ? 'circle-alert' : s.level === 'warn' ? 'triangle-alert' : s.level === 'good' ? 'circle-check' : 'trending-up'),
      h('a', { href: s.url, text: s.text }))));

    const bills = $('#bills');
    bills.className = '';
    bills.replaceChildren(data.bills.length ? h('ul', { class: 'mini-list' }, ...data.bills.map((b) => h('li', {},
      h('span', {}, b.name, h('span', { class: `sub ${b.days <= 3 ? 'neg' : ''}`, text: b.days < 0 ? `Overdue since ${b.due}` : b.days === 0 ? 'Due today' : `Due ${b.due} (in ${b.days} day${b.days === 1 ? '' : 's'})` })),
      h('span', { class: 'amt', text: formatMoney(b.amount) }))))
      : emptyState('Nothing due soon', 'Add rent, subscriptions or loans as recurring bills.', h('a', { class: 'btn', href: '/recurring/', text: 'Add a bill' })));

    const goals = $('#goals');
    goals.className = '';
    goals.replaceChildren(data.goals.length ? h('div', {}, ...data.goals.map((g) => {
      const bar = h('div', { class: 'progress', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(g.percent)), 'aria-label': `${g.name} progress` }, h('span'));
      bar.firstChild.style.width = `${g.percent}%`;
      return h('div', { class: 'budget-row' }, h('div', { class: 'budget-top' }, h('strong', { text: g.name })),
        h('div', { class: 'budget-amt' }, h('span', { text: `${formatMoney(g.saved)} of ${formatMoney(g.target)}` }), h('span', { class: 'muted', text: `${g.percent}%` })), bar);
    })) : emptyState('No goals yet', 'Name something you are saving for.', h('a', { class: 'btn', href: '/goals/', text: 'Create a goal' })));

    const movers = $('#movers');
    movers.className = '';
    const row = (m, cls) => h('li', {}, h('span', {}, h('span', { class: `tone tone-${m.color}` }), m.name),
      h('span', { class: `amt ${cls}`, text: `${Number(m.change) > 0 ? '+' : '-'}${formatMoney(Math.abs(Number(m.change)))}` }));
    const items = data.movers.up.map((m) => row(m, 'neg')).concat(data.movers.down.map((m) => row(m, 'pos')));
    movers.replaceChildren(items.length ? h('ul', { class: 'mini-list' }, ...items) : emptyState('Not enough data yet', 'Come back after a few more transactions.'));

    const subs = $('#subs');
    subs.className = '';
    subs.replaceChildren(data.subscriptions.length ? h('ul', { class: 'mini-list' }, ...data.subscriptions.map((x) => h('li', {},
      h('span', {}, x.name, h('span', { class: 'sub', text: `${x.months} months in a row${x.tracked ? ', already a bill' : `, next about ${x.next_date}`}` })),
      h('span', { class: 'amt', text: formatMoney(x.amount) }))))
      : emptyState('No repeating payments found', 'They show up after three months of similar payments.'));
    return data;
  } catch (error) {
    for (const id of ['bills', 'goals', 'movers', 'subs']) {
      const node = $(`#${id}`);
      node.className = '';
      node.replaceChildren(errorState(error.message, loadInsights));
    }
    return null;
  }
}

async function loadAlerts() {
  const card = $('#alerts');
  try {
    const data = await api('/api/notifications/');
    // budget alerts are already spelled out in "How you are doing"
    const items = data.notifications.filter((n) => n.kind !== 'budget');
    card.hidden = items.length === 0;
    $('#alert-list').replaceChildren(...items.map((n) => h('li', { class: n.level },
      icon(n.level === 'error' ? 'circle-alert' : 'triangle-alert'), h('a', { href: n.url, text: n.text }))));
  } catch (error) { card.hidden = true; }
}

/* ---------- onboarding ---------- */

async function loadOnboarding(data) {
  const card = $('#onboarding');
  try {
    data = data || await api('/api/onboarding/');
    card.hidden = data.dismissed;
    $('#onb-list').replaceChildren(...data.steps.map((s) => h('li', { class: s.done ? 'done' : '' },
      icon(s.done ? 'circle-check' : 'flag'), h('a', { href: s.url, text: s.label }))));
    $('#onb-sample').hidden = !data.can_load_sample;
  } catch (error) { card.hidden = true; }
}

$('#onb-dismiss').addEventListener('click', async () => {
  try { await api('/api/onboarding/', { method: 'POST' }); $('#onboarding').hidden = true; } catch (error) { showError(error); }
});
$('#load-sample').addEventListener('click', async (event) => {
  event.target.disabled = true;
  try {
    await api('/api/sample-data/', { method: 'POST' });
    toast('Sample data added.');
    window.location.reload();
  } catch (error) { event.target.disabled = false; showError(error); }
});

/* ---------- quick add: "coffee 150 food" ---------- */

function knownCategories() {
  return Array.from(document.querySelectorAll('#tx-category option')).filter((o) => o.value)
    .map((o) => ({ id: o.value, name: o.textContent.trim(), kind: o.dataset.kind }));
}

export function parseQuick(text, categories) {
  const words = text.trim().split(/\s+/).filter(Boolean);
  let kind = 'expense';
  let date = today();
  let amount = null;
  const rest = [];
  for (let i = words.length - 1; i >= 0; i -= 1) {
    const word = words[i];
    if (amount === null && /^[+-]?\d[\d,]*(\.\d+)?$/.test(word)) {
      if (word.startsWith('+')) kind = 'income';
      amount = word.replace(/^[+-]/, '').replace(/,/g, '');
    } else rest.unshift(word);
  }
  const keep = [];
  for (const word of rest) {
    const lower = word.toLowerCase();
    if (lower === 'yesterday') { date = today(-1); }
    else if (lower === 'today') date = today();
    else if (lower === 'income') kind = 'income';
    else keep.push(word);
  }
  let category = null;
  let nameWords = keep;
  for (let i = keep.length - 1; i >= 0 && !category; i -= 1) {
    const word = keep[i].toLowerCase();
    const found = categories.find((c) => (c.kind === 'both' || c.kind === kind)
      && (c.name.toLowerCase() === word || c.name.toLowerCase().split(' / ').pop() === word
        || (word.length >= 3 && c.name.toLowerCase().startsWith(word))));
    if (found && keep.length > 1) { category = found; nameWords = keep.filter((_, j) => j !== i); }
  }
  const name = nameWords.join(' ') || (category ? category.name : '');
  return { name: name.charAt(0).toUpperCase() + name.slice(1), amount, kind, date, category };
}

const form = $('#quick-add');
const preview = $('#quick-preview');

async function showPreview(event) {
  event.preventDefault();
  const parsed = parseQuick($('#quick-input').value, knownCategories());
  if (!parsed.amount || !parsed.name) {
    preview.replaceChildren(h('span', { class: 'neg', text: 'Add a description and an amount, for example: coffee 150 food' }));
    preview.hidden = false;
    return;
  }
  if (!parsed.category) {
    try {
      const { category } = await api('/api/rules/suggest/', { query: { text: parsed.name, kind: parsed.kind } });
      if (category) parsed.category = { id: String(category.id), name: category.full_name };
    } catch (error) { /* fall back to the dialog */ }
  }
  const chip = (text, cls = '') => h('span', { class: `chip-static ${cls}`, text });
  const save = h('button', { class: 'btn btn-primary btn-sm', type: 'button', text: 'Add', onclick: () => commit(parsed) });
  const edit = h('button', { class: 'btn btn-sm', type: 'button', text: 'Edit details', onclick: () => {
    openTransactionDialog(null, { name: parsed.name, amount: parsed.amount, kind: parsed.kind, date: parsed.date, category: parsed.category && parsed.category.id });
  } });
  const cancel = h('button', { class: 'btn btn-quiet btn-sm', type: 'button', text: 'Cancel', onclick: () => { preview.hidden = true; } });
  preview.replaceChildren(
    chip(parsed.name), chip(`${parsed.kind === 'income' ? '+' : '-'}${formatMoney(parsed.amount)}`, parsed.kind === 'income' ? 'pos' : 'neg'),
    chip(parsed.category ? parsed.category.name : 'No category yet', parsed.category ? '' : 'neg'), chip(parsed.date), save, edit, cancel);
  preview.hidden = false;
  if (!parsed.category) save.disabled = true;
}

async function commit(parsed) {
  try {
    const result = await api('/api/transactions/', { method: 'POST', body: {
      name: parsed.name, amount: parsed.amount, kind: parsed.kind, date: parsed.date, category: parsed.category.id } });
    toast('Transaction added.');
    if (result.warning) toast(result.warning, { kind: 'warn' });
    $('#quick-input').value = '';
    preview.hidden = true;
    document.dispatchEvent(new CustomEvent('tx:changed'));
  } catch (error) { showError(error); }
}

form.addEventListener('submit', showPreview);

function loadAll() { loadSummary(); loadRecent(); loadBudgets(); loadAccounts(); loadAlerts(); loadOnboarding(); loadInsights(); }
loadAll();
document.addEventListener('tx:changed', loadAll);
