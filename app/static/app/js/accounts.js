import {
  $, api, clearErrors, confirmDialog, emptyState, errorState, formData, formatMoney, h, icon, openDialog, setMoney, showError,
  showErrors, toast, withBusy, wireDialog, wireMoneyInputs,
} from './core.js';

const host = document.getElementById('account-list');
const tHost = document.getElementById('transfer-list');
const dialog = document.getElementById('account-dialog');
const form = document.getElementById('account-form');
const tDialog = document.getElementById('transfer-dialog');
const tForm = document.getElementById('transfer-form');
let accounts = [];
let editing = null;

const TYPE = { bank: 'Bank', cash: 'Cash', wallet: 'Wallet', credit: 'Credit' };

function card(a) {
  return h('article', { class: `card account${a.archived ? ' archived' : ''}` },
    h('div', { class: 'account-head' }, h('span', { class: 'cat-label' }, icon(a.icon, 'cat-icon'), h('strong', { text: a.name })),
      h('span', { class: 'tag', text: a.archived ? 'Archived' : TYPE[a.type] })),
    h('div', { class: `account-balance ${Number(a.balance) < 0 ? 'neg' : ''}`, text: formatMoney(a.balance) }),
    h('p', { class: 'muted small', text: `Opening balance ${formatMoney(a.opening_balance)}` }),
    h('div', { class: 'actions' },
      h('a', { class: 'btn btn-sm', href: `/transactions/?account=${a.id}`, text: 'View activity' }),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': `Edit ${a.name}`, onclick: () => openEdit(a) }, icon('pencil')),
      h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': `Delete ${a.name}`, onclick: () => remove(a) }, icon('trash-2'))));
}

async function load() {
  try {
    const data = await api('/api/accounts/');
    accounts = data.accounts;
    host.className = 'account-grid';
    host.replaceChildren(...accounts.map(card),
      h('div', { class: 'card account total' }, h('div', { class: 'account-head' }, h('strong', { text: 'Total across accounts' })),
        h('div', { class: `account-balance ${Number(data.total) < 0 ? 'neg' : ''}`, text: formatMoney(data.total) })));
  } catch (error) {
    host.className = '';
    host.replaceChildren(errorState(error.message, load));
  }
  loadTransfers();
}

async function loadTransfers() {
  try {
    const { transfers } = await api('/api/transfers/');
    tHost.className = '';
    if (!transfers.length) { tHost.replaceChildren(emptyState('No transfers yet', 'Move money between accounts without affecting income or expenses.')); return; }
    tHost.replaceChildren(h('ul', { class: 'mini-list' }, ...transfers.map((t) => h('li', {},
      h('span', {}, `${t.from.name} → ${t.to.name}`, h('span', { class: 'sub', text: `${t.date}${t.note ? ` · ${t.note}` : ''}` })),
      h('span', { class: 'amt' }, formatMoney(t.amount),
        h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': 'Delete this transfer', onclick: () => removeTransfer(t) }, icon('trash-2')))))));
  } catch (error) {
    tHost.className = '';
    tHost.replaceChildren(errorState(error.message, loadTransfers));
  }
}

function openEdit(account) {
  editing = account;
  clearErrors(form);
  form.reset();
  $('#account-title').textContent = account ? 'Edit account' : 'New account';
  if (account) {
    form.elements.name.value = account.name;
    form.elements.type.value = account.type;
    setMoney(form.elements.opening_balance, account.opening_balance);
    form.elements.archived.checked = account.archived;
  }
  openDialog(dialog, '#account-name');
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearErrors(form);
  try {
    await withBusy($('[data-submit]', form), () => api(editing ? `/api/accounts/${editing.id}/` : '/api/accounts/', { method: 'POST', body: formData(form) }));
    dialog.close();
    toast('Account saved.');
    await load();
  } catch (error) { showErrors(form, error); }
});

async function remove(account) {
  const ok = await confirmDialog({ title: 'Delete account', message: `Delete “${account.name}”? Accounts with activity can only be archived.` });
  if (!ok) return;
  try {
    await api(`/api/accounts/${account.id}/`, { method: 'DELETE' });
    toast('Account deleted.');
    await load();
  } catch (error) { showError(error); }
}

function openTransfer() {
  clearErrors(tForm);
  const active = accounts.filter((a) => !a.archived);
  const options = () => active.map((a) => h('option', { value: a.id, text: `${a.name} (${formatMoney(a.balance)})` }));
  tForm.elements.from_account.replaceChildren(...options());
  tForm.elements.to_account.replaceChildren(...options());
  if (active.length > 1) tForm.elements.to_account.value = String(active[1].id);
  tForm.elements.amount.value = '';
  tForm.elements.note.value = '';
  openDialog(tDialog, '#tr-amount');
}

tForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearErrors(tForm);
  try {
    await withBusy($('[data-submit]', tForm), () => api('/api/transfers/', { method: 'POST', body: formData(tForm) }));
    tDialog.close();
    toast('Transfer recorded.');
    await load();
  } catch (error) { showErrors(tForm, error); }
});

async function removeTransfer(t) {
  const ok = await confirmDialog({ title: 'Delete transfer', message: `Delete the transfer from ${t.from.name} to ${t.to.name}?` });
  if (!ok) return;
  try {
    await api(`/api/transfers/${t.id}/`, { method: 'DELETE' });
    toast('Transfer deleted.');
    await load();
  } catch (error) { showError(error); }
}

wireDialog(dialog);
wireDialog(tDialog);
wireMoneyInputs(dialog);
wireMoneyInputs(tDialog);
document.getElementById('new-account').addEventListener('click', () => openEdit(null));
document.getElementById('new-transfer').addEventListener('click', openTransfer);
load();
