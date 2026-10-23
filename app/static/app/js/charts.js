// Hand-written SVG charts. No libraries, no animation.
// Every chart renders into a container at its current pixel width, labels its marks for assistive
// technology, and shows a tooltip on hover and on keyboard focus.
import { formatMoney, h, svg } from './core.js';
import { compact, dayLabel, monthLong, monthShort } from './format.js';

const M = { top: 10, right: 12, bottom: 26, left: 48 };

export function niceScale(min, max, count = 4) {
  if (max === min) max = min + 1;
  const rough = (max - min) / count;
  const pow = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= rough);
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return { lo, hi, ticks };
}

function frame(width, height, title, desc) {
  const id = `c${Math.random().toString(36).slice(2, 8)}`;
  const root = svg('svg', { viewBox: `0 0 ${width} ${height}`, width, height, role: 'img', 'aria-labelledby': `${id}t ${id}d` });
  root.append(svg('title', { id: `${id}t` }, title), svg('desc', { id: `${id}d` }, desc));
  return root;
}

function tooltipFor(box) {
  const node = h('div', { class: 'tooltip', role: 'status', hidden: true });
  return {
    node,
    show(target, ...content) {
      node.replaceChildren(...content);
      node.hidden = false;
      const b = box.getBoundingClientRect();
      const r = target.getBoundingClientRect();
      const x = Math.min(Math.max(r.left - b.left + r.width / 2, 70), Math.max(70, b.width - 70));
      node.style.left = `${x}px`;
      node.style.top = `${r.top - b.top - 6}px`;
    },
    hide() { node.hidden = true; },
  };
}

function mark(tip, node, label, ...content) {
  node.setAttribute('tabindex', '0');
  node.setAttribute('role', 'img');
  node.setAttribute('aria-label', label);
  const show = () => tip.show(node, ...content.map((c) => (c instanceof Node ? c.cloneNode(true) : c)));
  node.addEventListener('mouseenter', show);
  node.addEventListener('focus', show);
  node.addEventListener('mouseleave', tip.hide);
  node.addEventListener('blur', tip.hide);
  return node;
}

function finish(box, root, tip) { box.replaceChildren(root, tip.node); }

function yAxis(root, scale, y, width) {
  for (const tick of scale.ticks) {
    const py = y(tick);
    root.append(svg('line', { class: tick === 0 ? 'ax-zero' : 'ax-grid', x1: M.left, x2: width - M.right, y1: py, y2: py }));
    root.append(svg('text', { class: 'ax-text', x: M.left - 6, y: py + 4, 'text-anchor': 'end' }, compact(tick)));
  }
}

const tipLine = (title, text) => [h('b', { text: title }), ` ${text}`];

/* Vertical grouped bars. items: [{label, long, a, b}] with up to two series. */
export function groupedBars(box, items, width, o) {
  const height = width < 480 ? 220 : 270;
  const two = o.bName !== undefined;
  const root = frame(width, height, o.title, `${o.title}. ` + items.map((r) =>
    `${r.long}: ${o.aName} ${formatMoney(r.a)}${two ? `, ${o.bName} ${formatMoney(r.b)}` : ''}.`).join(' '));
  const max = Math.max(1, ...items.flatMap((r) => [Number(r.a), two ? Number(r.b) : 0]));
  const scale = niceScale(0, max);
  const innerW = width - M.left - M.right;
  const innerH = height - M.top - M.bottom;
  const y = (v) => M.top + innerH - ((v - scale.lo) / (scale.hi - scale.lo)) * innerH;
  yAxis(root, scale, y, width);
  const group = innerW / items.length;
  const bar = Math.max(3, Math.min(two ? 18 : 28, group * (two ? 0.36 : 0.6)));
  const tip = tooltipFor(box);
  items.forEach((r, i) => {
    const cx = M.left + group * i + group / 2;
    const parts = two ? [['a', o.aClass, o.aName, -bar - 1], ['b', o.bClass, o.bName, 1]] : [['a', o.aClass, o.aName, -bar / 2]];
    for (const [key, cls, name, offset] of parts) {
      const value = Number(r[key]);
      const top = y(value);
      root.append(mark(tip, svg('rect', { class: `mark ${cls}`, x: cx + offset, y: top, width: bar, height: Math.max(0, y(0) - top) }),
        `${r.long} ${name} ${formatMoney(value)}`, ...tipLine(r.long, `${name} ${formatMoney(value)}`)));
    }
    const every = Math.ceil(items.length / Math.max(1, Math.floor(innerW / 44)));
    if (i % every === 0) root.append(svg('text', { class: 'ax-text', x: cx, y: height - 8, 'text-anchor': 'middle' }, r.label));
  });
  finish(box, root, tip);
}

export function monthlyBars(box, rows, width) {
  groupedBars(box, rows.map((r) => ({ label: monthShort(r.month), long: monthLong(r.month), a: r.income, b: r.expense })), width,
    { title: 'Income and expenses by month', aName: 'Income', bName: 'Expenses', aClass: 'm-income', bClass: 'm-expense' });
}

/* Lines over a shared x axis. series: [{name, cls, values, area}], labels: [{x label}] */
export function lineChart(box, labels, series, width, o) {
  const height = width < 480 ? 210 : 250;
  const all = series.flatMap((s) => s.values.map(Number));
  const root = frame(width, height, o.title, `${o.title}. ${labels[0].long} to ${labels[labels.length - 1].long}. `
    + series.map((s) => `${s.name} from ${formatMoney(s.values[0])} to ${formatMoney(s.values[s.values.length - 1])}.`).join(' '));
  const scale = niceScale(Math.min(0, ...all), Math.max(0, ...all, 1));
  const innerW = width - M.left - M.right;
  const innerH = height - M.top - M.bottom;
  const n = labels.length;
  const x = (i) => M.left + (n === 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  const y = (v) => M.top + innerH - ((v - scale.lo) / (scale.hi - scale.lo)) * innerH;
  yAxis(root, scale, y, width);
  const ticks = Math.min(n, width < 480 ? 3 : 6);
  for (let k = 0; k < ticks; k++) {
    const i = ticks === 1 ? 0 : Math.round((k / (ticks - 1)) * (n - 1));
    root.append(svg('text', { class: 'ax-text', x: x(i), y: height - 8, 'text-anchor': k === 0 ? 'start' : k === ticks - 1 ? 'end' : 'middle' }, labels[i].short));
  }
  for (const s of series) {
    const d = s.values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(Number(v)).toFixed(1)}`).join(' ');
    if (s.area) {
      root.append(svg('path', { class: 'm-area', d: `${d} L${x(n - 1).toFixed(1)} ${y(0).toFixed(1)} L${x(0).toFixed(1)} ${y(0).toFixed(1)} Z` }));
    }
    root.append(svg('path', { class: `m-line ${s.cls || ''}`, d }));
  }
  const dot = svg('circle', { class: 'm-dot', r: 4, visibility: 'hidden' });
  root.append(dot);
  const hit = svg('rect', { class: 'm-hit', x: M.left, y: M.top, width: innerW, height: innerH });
  root.append(hit);
  const tip = tooltipFor(box);
  let index = n - 1;
  const show = (i) => {
    index = Math.max(0, Math.min(n - 1, i));
    dot.setAttribute('cx', x(index));
    dot.setAttribute('cy', y(Number(series[0].values[index])));
    dot.setAttribute('visibility', 'visible');
    tip.show(dot, h('b', { text: labels[index].long }), ...series.map((s) => h('div', { text: `${s.name} ${formatMoney(s.values[index])}` })));
  };
  hit.setAttribute('tabindex', '0');
  hit.setAttribute('role', 'img');
  hit.setAttribute('aria-label', `${o.title}. Use the left and right arrow keys to inspect each point.`);
  hit.addEventListener('mousemove', (e) => {
    const r = hit.getBoundingClientRect();
    show(Math.round(((e.clientX - r.left) / r.width) * (n - 1)));
  });
  const hide = () => { tip.hide(); dot.setAttribute('visibility', 'hidden'); };
  hit.addEventListener('mouseleave', hide);
  hit.addEventListener('blur', hide);
  hit.addEventListener('focus', () => show(index));
  hit.addEventListener('keydown', (e) => {
    const step = { ArrowLeft: -1, ArrowRight: 1, Home: -9999, End: 9999 }[e.key];
    if (step !== undefined) { e.preventDefault(); show(index + step); }
  });
  finish(box, root, tip);
}

export function netFlowLine(box, monthly, width) {
  lineChart(box, monthly.map((r) => ({ short: monthShort(r.month), long: monthLong(r.month) })),
    [{ name: 'Net', values: monthly.map((r) => r.net), cls: '' }], width, { title: 'Net cash flow by month' });
}

export function balanceArea(box, daily, width) {
  lineChart(box, daily.map((r) => ({ short: dayLabel(r.date), long: dayLabel(r.date) })),
    [{ name: 'Balance', values: daily.map((r) => r.balance), area: true }], width, { title: 'Balance over time' });
}

export function cumulativeLine(box, cum, width) {
  const labels = cum.days.map((d) => ({ short: dayLabel(d.date), long: dayLabel(d.date) }));
  const series = [{ name: 'Spent', values: cum.days.map((d) => d.spent), cls: 'm-line-expense' }];
  if (cum.limit !== null) series.push({ name: 'Budget', values: cum.days.map(() => cum.limit), cls: 'm-line-budget' });
  lineChart(box, labels, series, width, { title: 'Spending this month against budget' });
}

/* Stacked monthly bars by category. */
export function stackedBars(box, data, width) {
  const height = width < 480 ? 230 : 280;
  const months = data.months;
  const totals = months.map((_, i) => data.series.reduce((s, x) => s + Number(x.values[i]), 0));
  const root = frame(width, height, 'Spending by category over time', 'Stacked monthly expenses. ' + months.map((m, i) => `${monthLong(m)}: ${formatMoney(totals[i])}.`).join(' '));
  const scale = niceScale(0, Math.max(1, ...totals));
  const innerW = width - M.left - M.right;
  const innerH = height - M.top - M.bottom;
  const y = (v) => M.top + innerH - ((v - scale.lo) / (scale.hi - scale.lo)) * innerH;
  yAxis(root, scale, y, width);
  const group = innerW / months.length;
  const bar = Math.max(4, Math.min(30, group * 0.62));
  const tip = tooltipFor(box);
  months.forEach((m, i) => {
    const cx = M.left + group * i + group / 2;
    let base = 0;
    const g = svg('g', {});
    const lines = [];
    data.series.forEach((s) => {
      const value = Number(s.values[i]);
      if (value <= 0) return;
      g.append(svg('rect', { class: `bar-tone-${s.color} seg`, x: cx - bar / 2, y: y(base + value), width: bar, height: y(base) - y(base + value) }));
      lines.push(h('div', { text: `${s.name} ${formatMoney(value)}` }));
      base += value;
    });
    mark(tip, g, `${monthLong(m)} total ${formatMoney(totals[i])}`, h('b', { text: monthLong(m) }), ...lines);
    g.classList.add('mark');
    root.append(g);
    const every = Math.ceil(months.length / Math.max(1, Math.floor(innerW / 44)));
    if (i % every === 0) root.append(svg('text', { class: 'ax-text', x: cx, y: height - 8, 'text-anchor': 'middle' }, monthShort(m)));
  });
  finish(box, root, tip);
  box.append(legend(data.series));
}

function legend(series) {
  return h('div', { class: 'legend chart-legend' }, ...series.map((s) => h('span', {}, h('i', { class: `sw tone-${s.color}` }), s.name)));
}

/* Donut of expense shares. */
export function donut(box, rows, width) {
  const shown = rows.slice(0, 7);
  const rest = rows.slice(7);
  if (rest.length) {
    shown.push({ name: 'Other', color: 'gray', total: rest.reduce((s, r) => s + Number(r.total), 0).toFixed(2),
      share: Math.round(rest.reduce((s, r) => s + r.share, 0) * 10) / 10 });
  }
  const size = Math.min(width, 260);
  const root = frame(size, size, 'Expenses by category', shown.map((r) => `${r.name}: ${formatMoney(r.total)}, ${r.share}%.`).join(' '));
  const cx = size / 2;
  const R = size / 2 - 6;
  const r = R * 0.6;
  const total = shown.reduce((s, x) => s + Number(x.total), 0);
  const tip = tooltipFor(box);
  let angle = -Math.PI / 2;
  for (const row of shown) {
    const sweep = (Number(row.total) / total) * Math.PI * 2;
    const a1 = angle + sweep;
    const large = sweep > Math.PI ? 1 : 0;
    const p = (rad, a) => `${(cx + rad * Math.cos(a)).toFixed(2)} ${(cx + rad * Math.sin(a)).toFixed(2)}`;
    const full = shown.length === 1;
    const d = full
      ? `M${p(R, angle)} A${R} ${R} 0 1 1 ${p(R, angle + Math.PI)} A${R} ${R} 0 1 1 ${p(R, angle)} M${p(r, angle)} A${r} ${r} 0 1 0 ${p(r, angle + Math.PI)} A${r} ${r} 0 1 0 ${p(r, angle)}`
      : `M${p(R, angle)} A${R} ${R} 0 ${large} 1 ${p(R, a1)} L${p(r, a1)} A${r} ${r} 0 ${large} 0 ${p(r, angle)} Z`;
    root.append(mark(tip, svg('path', { class: `mark bar-tone-${row.color} slice`, d, 'fill-rule': 'evenodd' }),
      `${row.name} ${formatMoney(row.total)}, ${row.share} percent`, ...tipLine(row.name, `${formatMoney(row.total)} (${row.share}%)`)));
    angle = a1;
  }
  root.append(svg('text', { class: 'ax-text donut-total', x: cx, y: cx - 2, 'text-anchor': 'middle' }, 'Total'));
  root.append(svg('text', { class: 'donut-value', x: cx, y: cx + 16, 'text-anchor': 'middle' }, compact(total)));
  box.replaceChildren(h('div', { class: 'donut-wrap' }, root, legend(shown.map((s) => ({ ...s, name: `${s.name} ${s.share}%` })))), tip.node);
}

/* Ranked horizontal bars. rows: [{name, color, total, share?}] */
export function rankedBars(box, rows, width, o = {}) {
  const shown = rows.slice(0, o.limit || 8);
  const rowH = 30;
  const height = Math.max(60, shown.length * rowH + 8);
  const root = frame(width, height, o.title || 'Ranked categories', shown.map((r) => `${r.name}: ${formatMoney(r.total)}${r.share !== undefined ? `, ${r.share}%` : ''}.`).join(' '));
  const labelW = Math.min(150, Math.round(width * 0.36));
  const valueW = width < 420 ? 52 : 64;
  const maxLen = Math.max(10, width - labelW - valueW - 12);
  const max = Math.max(...shown.map((r) => Number(r.total)));
  const tip = tooltipFor(box);
  shown.forEach((r, i) => {
    const top = 4 + i * rowH;
    const len = Math.max(2, (Number(r.total) / max) * maxLen);
    const cap = Math.floor(labelW / 7);
    const name = r.name.length > cap ? `${r.name.slice(0, cap - 1)}...` : r.name;
    root.append(svg('text', { class: 'ax-text', x: labelW, y: top + 15, 'text-anchor': 'end' }, name));
    root.append(mark(tip, svg('rect', { class: `mark bar-tone-${r.color || 'blue'}`, x: labelW + 8, y: top + 4, width: len, height: 16, rx: 2 }),
      `${r.name} ${formatMoney(r.total)}`, ...tipLine(r.name, `${formatMoney(r.total)}${r.share !== undefined ? ` (${r.share}%)` : ''}`)));
    root.append(svg('text', { class: 'ax-text', x: width - 2, y: top + 16, 'text-anchor': 'end' }, compact(Number(r.total))));
  });
  finish(box, root, tip);
}

/* Small multiples: one sparkline per category. */
export function sparklines(box, trend, months, width) {
  const cols = width >= 760 ? 3 : width >= 480 ? 2 : 1;
  const cellW = Math.floor((width - (cols - 1) * 12) / cols);
  const grid = h('div', { class: 'spark-grid' });
  grid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  const tip = tooltipFor(box);
  for (const s of trend) {
    const values = s.values.map(Number);
    const max = Math.max(1, ...values);
    const H = 46;
    const W = cellW - 4;
    const root = frame(W, H + 6, `${s.name} monthly spending`,
      months.map((m, i) => `${monthLong(m)} ${formatMoney(values[i])}`).join(', '));
    const x = (i) => 3 + (i / (values.length - 1)) * (W - 6);
    const y = (v) => 3 + H - (v / max) * H;
    root.append(svg('path', { class: `spark spark-${s.color}`, d: values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ') }));
    values.forEach((v, i) => {
      root.append(mark(tip, svg('circle', { class: `spark-dot spark-fill-${s.color}`, cx: x(i), cy: y(v), r: 4, fill: 'transparent' }),
        `${s.name} ${monthLong(months[i])} ${formatMoney(v)}`, ...tipLine(`${s.name} ${monthShort(months[i])}`, formatMoney(v))));
    });
    const total = values.reduce((a, b) => a + b, 0);
    grid.append(h('div', { class: 'spark-cell' },
      h('div', { class: 'spark-head' }, h('span', {}, h('i', { class: `sw tone-${s.color}` }), s.name), h('span', { class: 'muted small', text: formatMoney(total) })), root));
  }
  box.replaceChildren(grid, tip.node);
}

/* Calendar heatmap: columns are weeks (Monday first), rows are weekdays. */
export function heatmap(box, data, width) {
  const days = data.days;
  const weeks = Math.ceil(days.length / 7);
  const labelW = 30;
  const gap = 2;
  const cell = Math.max(8, Math.min(18, Math.floor((width - labelW) / weeks) - gap));
  const height = 7 * (cell + gap) + 22;
  const max = Math.max(1, ...days.map((d) => Number(d.expense)));
  const root = frame(labelW + weeks * (cell + gap), height, 'Daily spending heatmap',
    `Spending per day from ${data.start} to ${data.end}. Darker cells are days with more spending. The table view lists every day.`);
  const tip = tooltipFor(box);
  ['Mon', 'Wed', 'Fri'].forEach((name, k) => root.append(svg('text', { class: 'ax-text', x: 0, y: 22 + k * 2 * (cell + gap) + cell - 2 }, name)));
  let lastMonth = '';
  days.forEach((d, i) => {
    const week = Math.floor(i / 7);
    const dow = i % 7;
    const value = Number(d.expense);
    const level = value === 0 ? 0 : Math.min(4, 1 + Math.floor((value / max) * 3.999));
    const rect = svg('rect', { class: `heat heat-${level}`, x: labelW + week * (cell + gap), y: 14 + dow * (cell + gap), width: cell, height: cell, rx: 2,
      role: 'img', 'aria-label': `${d.date} spent ${formatMoney(value)}` });
    rect.addEventListener('mouseenter', () => tip.show(rect, ...tipLine(dayLabel(d.date), formatMoney(value))));
    rect.addEventListener('mouseleave', tip.hide);
    root.append(rect);
    const month = d.date.slice(0, 7);
    if (dow === 0 && month !== lastMonth) {
      lastMonth = month;
      root.append(svg('text', { class: 'ax-text', x: labelW + week * (cell + gap), y: 9 }, monthShort(month)));
    }
  });
  const legendRow = h('div', { class: 'legend heat-legend' }, 'Less', ...[0, 1, 2, 3, 4].map((l) => h('i', { class: `sw heat heat-${l}` })), 'More');
  box.replaceChildren(h('div', { class: 'heat-wrap' }, root), legendRow, tip.node);
}

/* Goal progress bars. */
export function goalBars(box, goals, width) {
  const rowH = 38;
  const height = Math.max(60, goals.length * rowH + 6);
  const root = frame(width, height, 'Savings goal progress', goals.map((g) => `${g.name}: ${formatMoney(g.saved)} of ${formatMoney(g.target)}, ${g.percent}%.`).join(' '));
  const tip = tooltipFor(box);
  goals.forEach((g, i) => {
    const top = 4 + i * rowH;
    root.append(svg('text', { class: 'ax-text', x: 0, y: top + 12 }, g.name.length > 36 ? `${g.name.slice(0, 35)}...` : g.name));
    root.append(svg('text', { class: 'ax-text', x: width, y: top + 12, 'text-anchor': 'end' }, `${g.percent}%`));
    root.append(svg('rect', { class: 'track', x: 0, y: top + 18, width: width, height: 10, rx: 3 }));
    root.append(mark(tip, svg('rect', { class: 'mark bar-tone-teal', x: 0, y: top + 18, width: Math.max(2, (width * g.percent) / 100), height: 10, rx: 3 }),
      `${g.name} ${g.percent} percent`, ...tipLine(g.name, `${formatMoney(g.saved)} of ${formatMoney(g.target)}`)));
  });
  finish(box, root, tip);
}

/* Accessible table alternative for a chart. */
export function dataTable(columns, rows) {
  return h('div', { class: 'table-wrap' }, h('table', { class: 'table chart-table' },
    h('thead', {}, h('tr', {}, ...columns.map((c) => h('th', { class: c.num ? 'num' : '', text: c.label })))),
    h('tbody', {}, ...rows.map((row) => h('tr', {}, ...columns.map((c) => h('td', { class: c.num ? 'num' : '', text: c.get(row) })))))));
}
