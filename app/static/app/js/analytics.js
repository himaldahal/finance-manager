import { $, $$, api, emptyState, errorState, formatMoney, h, icon } from './core.js';
import {
  balanceArea, cumulativeLine, dataTable, donut, goalBars, groupedBars, heatmap, monthlyBars, netFlowLine, rankedBars,
  sparklines, stackedBars,
} from './charts.js';
import { dayLabel, monthLong, monthShort } from './format.js';

const form = document.getElementById('range-form');
const note = document.getElementById('range-note');
const errorBox = document.getElementById('analytics-error');
let data = null;

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const now = () => new Date();
const PRESETS = {
  month: () => [new Date(now().getFullYear(), now().getMonth(), 1), now()],
  'last-month': () => [new Date(now().getFullYear(), now().getMonth() - 1, 1), new Date(now().getFullYear(), now().getMonth(), 0)],
  30: () => [new Date(now().getFullYear(), now().getMonth(), now().getDate() - 29), now()],
  90: () => [new Date(now().getFullYear(), now().getMonth(), now().getDate() - 89), now()],
  year: () => [new Date(now().getFullYear(), 0, 1), now()],
  365: () => [new Date(now().getFullYear(), now().getMonth(), now().getDate() - 364), now()],
};

const empty = (title, text = 'Try a wider date range or remove a filter.') => emptyState(title, text);

// Each chart: draw(box, width, data) and the columns/rows for its table view.
const CHARTS = {
  monthly: {
    draw: (box, w, d) => monthlyBars(box, d.monthly, w),
    table: (d) => [[{ label: 'Month', get: (r) => monthLong(r.month) }, { label: 'Income', num: true, get: (r) => formatMoney(r.income) },
      { label: 'Expenses', num: true, get: (r) => formatMoney(r.expense) }], d.monthly],
  },
  netflow: {
    draw: (box, w, d) => netFlowLine(box, d.monthly, w),
    table: (d) => [[{ label: 'Month', get: (r) => monthLong(r.month) }, { label: 'Net', num: true, get: (r) => formatMoney(r.net) }], d.monthly],
  },
  stacked: {
    draw: (box, w, d) => (d.stacked.series.length ? stackedBars(box, d.stacked, w) : box.replaceChildren(empty('No expenses yet'))),
    table: (d) => [[{ label: 'Month', get: (r) => monthLong(r.month) }, ...d.stacked.series.map((s, i) => ({ label: s.name, num: true, get: (r) => formatMoney(s.values[r.i]) }))],
      d.stacked.months.map((month, i) => ({ month, i }))],
  },
  donut: {
    draw: (box, w, d) => (d.categories.length ? donut(box, d.categories, w) : box.replaceChildren(empty('No expenses in this range'))),
    table: (d) => [[{ label: 'Category', get: (r) => r.name }, { label: 'Share', num: true, get: (r) => `${r.share}%` }, { label: 'Total', num: true, get: (r) => formatMoney(r.total) }], d.categories],
  },
  ranked: {
    draw: (box, w, d) => (d.categories.length ? rankedBars(box, d.categories, w, { title: 'Expenses by category, ranked' }) : box.replaceChildren(empty('No expenses in this range'))),
    table: (d) => [[{ label: 'Category', get: (r) => r.name }, { label: 'Transactions', num: true, get: (r) => String(r.count) }, { label: 'Total', num: true, get: (r) => formatMoney(r.total) }], d.categories],
  },
  sparks: {
    draw: (box, w, d) => (d.trend.length ? sparklines(box, d.trend, d.stacked.months, w) : box.replaceChildren(empty('No category history yet'))),
    table: (d) => [[{ label: 'Category', get: (r) => r.name }, ...d.stacked.months.map((m, i) => ({ label: monthShort(m), num: true, get: (r) => formatMoney(r.values[i]) }))], d.trend],
  },
  heatmap: {
    draw: (box, w, d) => heatmap(box, d.heatmap, w),
    table: (d) => [[{ label: 'Date', get: (r) => r.date }, { label: 'Spent', num: true, get: (r) => formatMoney(r.expense) }], d.heatmap.days.filter((x) => Number(x.expense) > 0)],
  },
  weekday: {
    draw: (box, w, d) => groupedBars(box, d.weekday.map((r) => ({ label: r.day, long: r.day, a: r.average })), w,
      { title: 'Average spending by weekday', aName: 'Average', aClass: 'm-budget' }),
    table: (d) => [[{ label: 'Weekday', get: (r) => r.day }, { label: 'Average per day', num: true, get: (r) => formatMoney(r.average) }, { label: 'Total', num: true, get: (r) => formatMoney(r.total) }], d.weekday],
  },
  cumulative: {
    draw: (box, w, d) => cumulativeLine(box, d.cumulative, w),
    table: (d) => [[{ label: 'Date', get: (r) => r.date }, { label: 'Spent so far', num: true, get: (r) => formatMoney(r.spent) }], d.cumulative.days],
  },
  budget: {
    draw: (box, w, d) => (d.budget_vs_actual.length
      ? groupedBars(box, d.budget_vs_actual.map((r) => ({ label: r.name.slice(0, 8), long: r.name, a: r.limit, b: r.spent })), w,
        { title: 'Budget and actual', aName: 'Budget', bName: 'Spent', aClass: 'm-budget', bClass: 'm-expense' })
      : box.replaceChildren(empty('No budgets for this month', 'Set budgets on the Budgets page.'))),
    table: (d) => [[{ label: 'Budget', get: (r) => r.name }, { label: 'Limit', num: true, get: (r) => formatMoney(r.limit) }, { label: 'Spent', num: true, get: (r) => formatMoney(r.spent) }], d.budget_vs_actual],
  },
  goals: {
    draw: (box, w, d) => (d.goals.length ? goalBars(box, d.goals, w) : box.replaceChildren(empty('No goals yet', 'Create one on the Goals page.'))),
    table: (d) => [[{ label: 'Goal', get: (r) => r.name }, { label: 'Saved', num: true, get: (r) => formatMoney(r.saved) }, { label: 'Target', num: true, get: (r) => formatMoney(r.target) }, { label: 'Progress', num: true, get: (r) => `${r.percent}%` }], d.goals],
  },
  balance: {
    draw: (box, w, d) => balanceArea(box, d.daily, w),
    table: (d) => [[{ label: 'Date', get: (r) => r.date }, { label: 'Income', num: true, get: (r) => formatMoney(r.income) }, { label: 'Expenses', num: true, get: (r) => formatMoney(r.expense) }, { label: 'Balance', num: true, get: (r) => formatMoney(r.balance) }], d.daily],
  },
  payees: {
    draw: (box, w, d) => (d.payees.length ? rankedBars(box, d.payees.map((p) => ({ ...p, total: p.total, color: 'blue' })), w, { title: 'Top payees' }) : box.replaceChildren(empty('No payees recorded', 'Add a payee when you record an expense.'))),
    table: (d) => [[{ label: 'Payee', get: (r) => r.name }, { label: 'Transactions', num: true, get: (r) => String(r.count) }, { label: 'Total', num: true, get: (r) => formatMoney(r.total) }], d.payees],
  },
};

const cards = {};
$$('[data-chart-card]').forEach((el) => { cards[el.dataset.chartCard] = { el, view: 'chart', box: $('[data-chart]', el) }; });

function draw(name) {
  const card = cards[name];
  const spec = CHARTS[name];
  const width = Math.max(240, Math.floor(card.box.clientWidth || card.el.clientWidth - 32));
  if (card.view === 'table') {
    const [columns, rows] = spec.table(data);
    card.box.replaceChildren(rows.length ? dataTable(columns, rows) : empty('No data'));
  } else {
    spec.draw(card.box, width, data);
  }
}

function renderTotals() {
  const t = data.totals;
  const stat = (label, value, tint) => h('div', { class: 'card stat' }, h('div', { class: 'label', text: label }),
    h('div', { class: `value ${tint || ''}`, text: formatMoney(value) }));
  $('#totals').replaceChildren(stat('Income', t.income, 'pos'), stat('Expenses', t.expense, 'neg'),
    stat('Net', t.net, Number(t.net) < 0 ? 'neg' : 'pos'), stat('Balance at start', data.opening_balance));
}

function renderTop() {
  const host = $('#top-list');
  if (!data.top.length) { host.replaceChildren(empty('No expenses in this range')); return; }
  host.replaceChildren(h('ol', { class: 'top-list' }, ...data.top.map((t) => h('li', {},
    h('span', { class: 'grow' }, h('strong', { text: t.name }), h('span', { class: 'muted small', text: ` ${t.category.name} · ${t.date}` })),
    h('span', { class: 'neg', text: formatMoney(t.amount) })))));
}

function query() {
  const q = { start: form.elements.start.value, end: form.elements.end.value };
  if (form.elements.category.value) q.category = form.elements.category.value;
  if (form.elements.tag.value) q.tag = form.elements.tag.value;
  return q;
}

async function load() {
  const q = query();
  if (!q.start || !q.end) return;
  history.replaceState(null, '', `${window.location.pathname}?${new URLSearchParams(q)}`);
  try {
    data = await api('/api/analytics/', { query: q });
    errorBox.hidden = true;
    note.textContent = `${data.daily.length} day(s). Monthly charts show the 12 months up to the end date. Balance ignores the category and tag filters.`;
    renderTotals();
    renderTop();
    Object.keys(cards).forEach(draw);
  } catch (error) {
    errorBox.replaceChildren(errorState(error.message, load));
    errorBox.hidden = false;
  }
}

$$('[data-toggle-table]').forEach((button) => button.addEventListener('click', () => {
  const name = Object.keys(cards).find((key) => cards[key].el.contains(button));
  const card = cards[name];
  card.view = card.view === 'chart' ? 'table' : 'chart';
  button.textContent = card.view === 'chart' ? 'Show table' : 'Show chart';
  button.setAttribute('aria-pressed', String(card.view === 'table'));
  if (data) draw(name);
}));

form.addEventListener('change', (event) => {
  if (event.target.id === 'r-preset') {
    const make = PRESETS[event.target.value];
    if (make) {
      const [a, b] = make();
      form.elements.start.value = iso(a);
      form.elements.end.value = iso(b);
    }
  } else if (event.target.name === 'start' || event.target.name === 'end') {
    $('#r-preset').value = '';
  }
  load();
});
form.addEventListener('submit', (event) => { event.preventDefault(); load(); });

const params = new URLSearchParams(window.location.search);
form.elements.start.value = params.get('start') || form.dataset.start;
form.elements.end.value = params.get('end') || form.dataset.end;
if (params.get('category')) form.elements.category.value = params.get('category');
if (params.get('tag')) form.elements.tag.value = params.get('tag');

let lastWidth = window.innerWidth;
window.addEventListener('resize', () => {
  if (Math.abs(window.innerWidth - lastWidth) < 8) return;
  lastWidth = window.innerWidth;
  clearTimeout(window.__fmResize);
  window.__fmResize = setTimeout(() => { if (data) Object.keys(cards).forEach(draw); }, 150);
});
document.addEventListener('tx:changed', load);
load();
