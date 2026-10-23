import {
  $, api, clearErrors, confirmDialog, emptyState, errorState, formData, formatMoney, h, icon, openDialog, setMoney, showError,
  showErrors, toast, withBusy, wireDialog, wireMoneyInputs,
} from './core.js';

const host = document.getElementById('goal-list');
const dialog = document.getElementById('goal-dialog');
const form = document.getElementById('goal-form');
const cDialog = document.getElementById('contrib-dialog');
const cForm = document.getElementById('contrib-form');
let goals = [];
let editing = null;
let contributing = null;

function ring(percent) {
  const R = 30;
  const C = 2 * Math.PI * R;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 72 72');
  svg.setAttribute('class', 'ring');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', `${percent} percent saved`);
  const make = (cls, dash) => {
    const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    c.setAttribute('cx', '36'); c.setAttribute('cy', '36'); c.setAttribute('r', String(R)); c.setAttribute('class', cls);
    if (dash !== undefined) {
      c.setAttribute('stroke-dasharray', `${(C * dash) / 100} ${C}`);
      c.setAttribute('transform', 'rotate(-90 36 36)');
    }
    return c;
  };
  svg.append(make('ring-track'), make('ring-fill', percent));
  const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
  text.setAttribute('x', '36'); text.setAttribute('y', '40'); text.setAttribute('text-anchor', 'middle'); text.setAttribute('class', 'ring-text');
  text.textContent = `${Math.round(percent)}%`;
  svg.append(text);
  return svg;
}

function card(g) {
  const bar = h('div', { class: 'progress', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100',
    'aria-valuenow': String(Math.round(g.percent)), 'aria-label': `${g.name} progress` }, h('span'));
  bar.firstChild.style.width = `${g.percent}%`;
  const info = [h('div', {}, h('strong', { text: formatMoney(g.saved) }), h('span', { class: 'muted', text: ` of ${formatMoney(g.target_amount)}` }))];
  if (g.complete) info.push(h('span', { class: 'tag income', text: 'Goal reached' }));
  else {
    if (g.target_date) info.push(h('div', { class: 'muted small', text: `Target ${g.target_date}${g.overdue ? ' (past due)' : ''}` }));
    if (g.required_monthly) info.push(h('div', { class: 'small', text: `Save ${formatMoney(g.required_monthly)} a month to get there` }));
    else if (g.overdue) info.push(h('div', { class: 'small neg', text: `${formatMoney(g.remaining)} still to save` }));
    else info.push(h('div', { class: 'muted small', text: `${formatMoney(g.remaining)} to go` }));
  }
  const links = [];
  if (g.account) links.push(`Account: ${g.account.name}`);
  if (g.category) links.push(`Category: ${g.category.name}`);
  const recent = g.contributions.slice(0, 3).map((c) => h('li', {}, h('span', { text: `${c.date}${c.note ? ` · ${c.note}` : ''}` }),
    h('span', { class: Number(c.amount) < 0 ? 'neg' : 'pos', text: formatMoney(c.amount) }),
    h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': 'Remove this contribution', onclick: () => removeContribution(c) }, icon('x'))));
  return h('article', { class: 'card goal', id: `goal-${g.id}` },
    h('div', { class: 'goal-head' }, ring(g.percent), h('div', { class: 'goal-title' }, h('h2', { text: g.name }), ...info)),
    bar,
    links.length ? h('p', { class: 'muted small', text: links.join(' · ') }) : null,
    recent.length ? h('ul', { class: 'mini-list small' }, ...recent) : h('p', { class: 'muted small', text: 'No contributions yet.' }),
    h('div', { class: 'actions' },
      h('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: () => openContribute(g) }, icon('plus'), 'Add money'),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': `Edit ${g.name}`, onclick: () => openEdit(g) }, icon('pencil')),
      h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': `Delete ${g.name}`, onclick: () => remove(g) }, icon('trash-2'))));
}

async function load() {
  try {
    goals = (await api('/api/goals/')).goals;
    host.className = 'goal-grid';
    if (!goals.length) {
      host.className = '';
      host.replaceChildren(emptyState('No goals yet', 'Name what you are saving for and how much it costs.',
        h('button', { class: 'btn btn-primary', type: 'button', text: 'Create a goal', onclick: () => openEdit(null) })));
      return;
    }
    host.replaceChildren(...goals.map(card));
    if (window.location.hash.startsWith('#goal-')) {
      const target = document.querySelector(window.location.hash);
      if (target) target.scrollIntoView({ block: 'center' });
    }
  } catch (error) {
    host.className = '';
    host.replaceChildren(errorState(error.message, load));
  }
}

function openEdit(goal) {
  editing = goal;
  clearErrors(form);
  form.reset();
  $('#goal-title').textContent = goal ? 'Edit goal' : 'New goal';
  if (goal) {
    form.elements.name.value = goal.name;
    setMoney(form.elements.target_amount, goal.target_amount);
    form.elements.target_date.value = goal.target_date || '';
    form.elements.account.value = goal.account ? String(goal.account.id) : '';
    form.elements.category.value = goal.category ? String(goal.category.id) : '';
  }
  openDialog(dialog, '#goal-name');
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearErrors(form);
  try {
    await withBusy($('[data-submit]', form), () => api(editing ? `/api/goals/${editing.id}/` : '/api/goals/', { method: 'POST', body: formData(form) }));
    dialog.close();
    toast('Goal saved.');
    await load();
  } catch (error) { showErrors(form, error); }
});

function openContribute(goal) {
  contributing = goal;
  clearErrors(cForm);
  cForm.elements.amount.value = goal.required_monthly ? '' : '';
  cForm.elements.note.value = '';
  $('#contrib-title').textContent = `Add to ${goal.name}`;
  openDialog(cDialog, '#contrib-amount');
}

cForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearErrors(cForm);
  try {
    await withBusy($('[data-submit]', cForm), () => api(`/api/goals/${contributing.id}/contributions/`, { method: 'POST', body: formData(cForm) }));
    cDialog.close();
    toast('Saved.');
    await load();
  } catch (error) { showErrors(cForm, error); }
});

async function removeContribution(c) {
  try {
    await api(`/api/contributions/${c.id}/`, { method: 'DELETE' });
    toast('Contribution removed.');
    await load();
  } catch (error) { showError(error); }
}

async function remove(goal) {
  const ok = await confirmDialog({ title: 'Delete goal', message: `Delete “${goal.name}” and its contributions?` });
  if (!ok) return;
  try {
    await api(`/api/goals/${goal.id}/`, { method: 'DELETE' });
    toast('Goal deleted.');
    await load();
  } catch (error) { showError(error); }
}

wireDialog(dialog);
wireDialog(cDialog);
wireMoneyInputs(dialog);
wireMoneyInputs(cDialog);
document.getElementById('new-goal').addEventListener('click', () => openEdit(null));
load();
