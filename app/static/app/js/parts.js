// Small renderers shared by several pages.
import { formatMoney, h, icon, tone } from './core.js';

export function catLabel(category, tag = 'strong') {
  return h(tag, { class: 'cat-label' }, icon(category.icon || 'tag', `cat-icon tone-text-${category.color}`), category.name);
}

/** One budget (category or overall) with a progress bar and alert badge. */
export function budgetRow(b, { detail = false } = {}) {
  const percent = Math.min(b.percent, 100);
  const level = b.level;
  const bar = h('div', {
    class: `progress ${level === 'over' ? 'over' : level === 'warn' ? 'near' : ''}`, role: 'progressbar',
    'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(percent)),
    'aria-label': `${b.category ? b.category.name : 'Overall'} budget used`,
  }, h('span'));
  bar.firstChild.style.width = `${percent}%`;
  const remaining = Number(b.remaining);
  const badge = level === 'over' ? h('span', { class: 'tag expense', text: 'Over budget' })
    : level === 'warn' ? h('span', { class: 'tag warn', text: `${Math.round(b.percent)}% used` }) : null;
  const name = b.category ? catLabel(b.category) : h('strong', { text: 'Whole month' });
  const row = h('div', { class: 'budget-row' },
    h('div', { class: 'budget-top' }, h('span', { class: 'budget-name' }, name, badge, b.rollover ? h('span', { class: 'tag', text: 'Rollover' }) : null)),
    h('div', { class: 'budget-amt' }, h('span', { class: 'amt' }, `${formatMoney(b.spent)} of ${formatMoney(b.available)}`),
      remaining < 0 ? h('span', { class: 'over-note', text: `Over by ${formatMoney(-remaining)}` })
        : h('span', { class: 'muted', text: `${formatMoney(remaining)} left` })),
    bar);
  if (detail) {
    const parts = [`Safe to spend ${formatMoney(b.safe_per_day)} per day`];
    if (Number(b.carry) > 0) parts.push(`includes ${formatMoney(b.carry)} carried over`);
    parts.push(`on pace to spend ${formatMoney(b.projected)}`);
    row.append(h('p', { class: `budget-note small ${b.projected_over ? 'neg' : 'muted'}`, text: parts.join(' · ') }));
  }
  return row;
}

export { tone };
