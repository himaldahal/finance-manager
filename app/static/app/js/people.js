import {
  $, api, clearErrors, confirmDialog, emptyState, errorState, formData, formatMoney, h, icon, openDialog, showError, showErrors,
  toast, withBusy, wireDialog, wireMoneyInputs,
} from './core.js';

const host = document.getElementById('people-list');
const totals = document.getElementById('people-totals');
const personDialog = document.getElementById('person-dialog');
const personForm = document.getElementById('person-form');
const entryDialog = document.getElementById('entry-dialog');
const entryForm = document.getElementById('entry-form');
let current = null;

function sentence(p) {
  const money = formatMoney(Math.abs(Number(p.net)));
  if (p.direction === 'owes_you') return `${p.name} owes you ${money}`;
  if (p.direction === 'you_owe') return `You owe ${p.name} ${money}`;
  return `You and ${p.name} are settled up`;
}

function card(p) {
  const entries = p.entries.slice(0, 4).map((e) => h('li', {}, h('span', {}, e.kind_label, h('span', { class: 'sub', text: `${e.date}${e.description ? ` · ${e.description}` : ''}${e.due_date ? ` · due ${e.due_date}` : ''}` })),
    h('span', { class: 'amt' }, h('span', { class: Number(e.amount) < 0 ? 'neg' : 'pos', text: formatMoney(e.amount) }),
      h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': 'Remove this entry', onclick: () => removeEntry(e) }, icon('x')))));
  return h('article', { class: 'card person' },
    h('h2', { text: p.name }),
    h('p', { class: `person-net ${p.direction === 'owes_you' ? 'pos' : p.direction === 'you_owe' ? 'neg' : 'muted'}`, text: sentence(p) }),
    p.next_due ? h('p', { class: 'small muted', text: `Next due date: ${p.next_due}` }) : null,
    entries.length ? h('ul', { class: 'mini-list small' }, ...entries) : h('p', { class: 'muted small', text: 'Nothing recorded yet.' }),
    h('div', { class: 'actions' },
      h('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: () => openEntry(p) }, icon('plus'), 'Add entry'),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': `Rename ${p.name}`, onclick: () => openPerson(p) }, icon('pencil')),
      h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': `Delete ${p.name}`, onclick: () => removePerson(p) }, icon('trash-2'))));
}

async function load() {
  try {
    const data = await api('/api/people/');
    totals.replaceChildren(
      h('div', { class: 'card stat' }, h('div', { class: 'label', text: 'Owed to you' }), h('div', { class: 'value pos', text: formatMoney(data.owed_to_you) })),
      h('div', { class: 'card stat' }, h('div', { class: 'label', text: 'You owe' }), h('div', { class: 'value neg', text: formatMoney(data.you_owe) })));
    host.className = 'goal-grid';
    if (!data.people.length) {
      host.className = '';
      host.replaceChildren(emptyState('Nobody yet', 'Add a friend to keep track of loans and shared bills.',
        h('button', { class: 'btn btn-primary', type: 'button', text: 'Add a person', onclick: () => openPerson(null) })));
      return;
    }
    host.replaceChildren(...data.people.map(card));
  } catch (error) {
    host.className = '';
    host.replaceChildren(errorState(error.message, load));
  }
}

let editing = null;
function openPerson(person) {
  editing = person;
  clearErrors(personForm);
  personForm.reset();
  $('#person-title').textContent = person ? 'Rename' : 'Add a person';
  if (person) personForm.elements.name.value = person.name;
  openDialog(personDialog, '#person-name');
}

personForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearErrors(personForm);
  try {
    await withBusy($('[data-submit]', personForm), () => api(editing ? `/api/people/${editing.id}/` : '/api/people/', { method: 'POST', body: formData(personForm) }));
    personDialog.close();
    toast('Saved.');
    await load();
  } catch (error) { showErrors(personForm, error); }
});

function syncKind() {
  const kind = entryForm.elements.kind.value;
  const split = kind === 'split_me' || kind === 'split_them';
  entryForm.querySelector('[data-for="amount"]').hidden = split;
  entryForm.querySelector('[data-for="total"]').hidden = !split;
  entryForm.querySelector('[data-for="share"]').hidden = !split;
  entryForm.querySelector('[data-for="due"]').hidden = !(kind === 'lent' || kind === 'borrowed');
}
entryForm.elements.kind.addEventListener('change', syncKind);

function openEntry(person) {
  current = person;
  clearErrors(entryForm);
  entryForm.reset();
  entryForm.elements.date.value = entryDialog.dataset.today;
  $('#entry-title').textContent = `Add entry for ${person.name}`;
  syncKind();
  openDialog(entryDialog, '#entry-kind');
}

entryForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearErrors(entryForm);
  const body = formData(entryForm);
  for (const key of ['amount', 'total', 'my_share', 'due_date']) if (body[key] === '') delete body[key];
  try {
    await withBusy($('[data-submit]', entryForm), () => api(`/api/people/${current.id}/entries/`, { method: 'POST', body }));
    entryDialog.close();
    toast('Entry added.');
    await load();
  } catch (error) { showErrors(entryForm, error); }
});

async function removeEntry(e) {
  try {
    await api(`/api/entries/${e.id}/`, { method: 'DELETE' });
    toast('Entry removed.');
    await load();
  } catch (error) { showError(error); }
}

async function removePerson(p) {
  const ok = await confirmDialog({ title: 'Delete person', message: `Delete ${p.name} and everything recorded with them?` });
  if (!ok) return;
  try {
    await api(`/api/people/${p.id}/`, { method: 'DELETE' });
    toast('Deleted.');
    await load();
  } catch (error) { showError(error); }
}

wireDialog(personDialog);
wireDialog(entryDialog);
wireMoneyInputs(entryDialog);
$('#new-person').addEventListener('click', () => openPerson(null));
load();
