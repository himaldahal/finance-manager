import { $, api, confirmDialog, emptyState, errorState, formatMoney, h, icon, showError, toast } from './core.js';
import { catLabel } from './parts.js';

const list = document.getElementById('trash-list');
const activity = document.getElementById('activity-list');

async function loadTrash() {
  try {
    const data = await api('/api/trash/');
    list.className = '';
    $('#empty-trash').hidden = data.transactions.length === 0;
    if (!data.transactions.length) {
      list.replaceChildren(emptyState('Trash is empty', 'Deleted transactions appear here and can be restored.'));
      return;
    }
    list.replaceChildren(h('ul', { class: 'mini-list' }, ...data.transactions.map((t) => h('li', {},
      h('span', {}, t.name, h('span', { class: 'sub' }, catLabel(t.category, 'span'), ` · ${t.date} · ${t.days_left} day${t.days_left === 1 ? '' : 's'} left`)),
      h('span', { class: 'amt' }, h('span', { class: t.kind === 'income' ? 'pos' : 'neg', text: `${t.kind === 'income' ? '+' : '-'}${formatMoney(t.amount)} ` }),
        h('button', { class: 'btn btn-sm', type: 'button', onclick: () => restore(t) }, icon('rotate-ccw'), 'Restore'),
        h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': `Delete ${t.name} forever`, onclick: () => remove(t) }, icon('trash-2')))))));
  } catch (error) {
    list.className = '';
    list.replaceChildren(errorState(error.message, loadTrash));
  }
}

async function loadActivity() {
  try {
    const { entries } = await api('/api/activity/');
    activity.className = '';
    activity.replaceChildren(entries.length ? h('ul', { class: 'mini-list' }, ...entries.map((e) => h('li', {},
      h('span', {}, e.summary || e.action, h('span', { class: 'sub', text: new Date(e.when).toLocaleString() })),
      h('span', { class: 'tag', text: e.action })))) : emptyState('No changes yet', 'Adding, editing and deleting transactions is logged here.'));
  } catch (error) {
    activity.className = '';
    activity.replaceChildren(errorState(error.message, loadActivity));
  }
}

async function restore(t) {
  try {
    await api(`/api/transactions/${t.id}/restore/`, { method: 'POST' });
    toast('Transaction restored.');
    loadTrash();
    loadActivity();
  } catch (error) { showError(error); }
}

async function remove(t) {
  const ok = await confirmDialog({ title: 'Delete forever', message: `Permanently delete “${t.name}”? This cannot be undone.` });
  if (!ok) return;
  try {
    await api(`/api/trash/${t.id}/`, { method: 'DELETE' });
    toast('Deleted forever.');
    loadTrash();
  } catch (error) { showError(error); }
}

$('#empty-trash').addEventListener('click', async () => {
  const ok = await confirmDialog({ title: 'Empty trash', message: 'Permanently delete everything in the trash?', confirmLabel: 'Empty trash' });
  if (!ok) return;
  try {
    const r = await api('/api/trash/empty/', { method: 'POST' });
    toast(`Removed ${r.removed} transaction(s).`);
    loadTrash();
  } catch (error) { showError(error); }
});

loadTrash();
loadActivity();
