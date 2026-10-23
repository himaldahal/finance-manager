import { $, api, clearErrors, confirmDialog, emptyState, errorState, formData, formatMoney, h, icon, openDialog, setMoney, showError, showErrors, toast, withBusy, wireDialog, wireMoneyInputs } from './core.js';
import { catLabel } from './parts.js';

const list = document.getElementById('recurring-list');
const dialog = document.getElementById('rec-dialog');
const form = document.getElementById('rec-form');
let items = [];
let editing = null;

function syncCategories() {
  const select = form.elements.category;
  const wanted = form.elements.kind.value;
  for (const option of select.options) {
    if (!option.value) continue;
    const ok = option.dataset.kind === 'both' || option.dataset.kind === wanted;
    option.hidden = !ok;
    option.disabled = !ok;
  }
  if (select.selectedOptions[0] && select.selectedOptions[0].disabled) select.value = '';
}
form.querySelectorAll('input[name="kind"]').forEach((radio) => radio.addEventListener('change', syncCategories));

function row(item) {
  const sign = item.kind === 'income' ? '+' : '-';
  return h('tr', { class: item.active ? '' : 'is-dup' },
    h('td', { class: 'name-cell', 'data-label': 'Description' }, item.name,
      item.last_error ? h('span', { class: 'row-error', text: `Last run failed: ${item.last_error}` }) : null),
    h('td', { 'data-label': 'Category' }, catLabel(item.category, 'span')),
    h('td', { 'data-label': 'Repeats', text: item.frequency === 'weekly' ? 'Every week' : 'Every month' }),
    h('td', { 'data-label': 'Next date', text: item.active ? item.next_due : 'Paused' }),
    h('td', { class: `num ${item.kind === 'income' ? 'pos' : 'neg'}`, 'data-label': 'Amount', text: sign + formatMoney(item.amount) }),
    h('td', { class: 'row-actions' },
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': `${item.active ? 'Pause' : 'Resume'} ${item.name}`, title: item.active ? 'Pause' : 'Resume', onclick: () => toggle(item) }, icon(item.active ? 'pause' : 'play')),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': `Edit ${item.name}`, onclick: () => openEdit(item) }, icon('pencil')),
      h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': `Delete ${item.name}`, onclick: () => remove(item) }, icon('trash-2'))));
}

function render() {
  if (!items.length) {
    list.className = '';
    list.replaceChildren(emptyState('Nothing scheduled', 'Add rent, a salary or a subscription once and it is recorded for you.'));
    return;
  }
  list.className = 'table-wrap';
  list.replaceChildren(h('table', { class: 'table stack' },
    h('caption', { class: 'sr-only', text: 'Recurring transactions' }),
    h('thead', {}, h('tr', {}, ...['Description', 'Category', 'Repeats', 'Next date'].map((t) => h('th', { text: t })),
      h('th', { class: 'num', text: 'Amount' }), h('th', {}, h('span', { class: 'sr-only', text: 'Actions' })))),
    h('tbody', {}, ...items.map(row))));
}

async function load() {
  try {
    items = (await api('/api/recurring/')).items;
    render();
  } catch (error) {
    list.className = '';
    list.replaceChildren(errorState(error.message, load));
  }
}

function openEdit(item) {
  editing = item;
  clearErrors(form);
  form.reset();
  $('#rec-title').textContent = item ? 'Edit recurring item' : 'New recurring item';
  if (item) {
    for (const key of ['name', 'frequency', 'note', 'payee']) form.elements[key].value = item[key] || '';
    setMoney(form.elements.amount, item.amount);
    form.elements.account.value = item.account ? String(item.account) : '';
    form.elements.kind.value = item.kind;
    form.elements.start_date.value = item.start_date;
    form.elements.end_date.value = item.end_date || '';
    syncCategories();
    form.elements.category.value = String(item.category.id);
  } else {
    form.elements.start_date.value = dialog.dataset.today;
    syncCategories();
  }
  openDialog(dialog, '#rec-name');
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearErrors(form);
  try {
    await withBusy($('[data-submit]', form), () => api(
      editing ? `/api/recurring/${editing.id}/` : '/api/recurring/', { method: 'POST', body: formData(form) }));
    dialog.close();
    toast('Recurring item saved.');
    await load();
  } catch (error) { showErrors(form, error); }
});

async function toggle(item) {
  try {
    await api(`/api/recurring/${item.id}/toggle/`, { method: 'POST' });
    toast(item.active ? 'Paused.' : 'Resumed. Missed dates while paused are skipped.');
    await load();
  } catch (error) { showError(error); }
}

async function remove(item) {
  const ok = await confirmDialog({ title: 'Delete recurring item', message: `Stop and delete “${item.name}”? Transactions it already created are kept.` });
  if (!ok) return;
  try {
    await api(`/api/recurring/${item.id}/`, { method: 'DELETE' });
    toast('Recurring item deleted.');
    await load();
  } catch (error) { showError(error); }
}

wireDialog(dialog);
wireMoneyInputs(dialog);
$('#new-recurring').addEventListener('click', () => openEdit(null));
load();
