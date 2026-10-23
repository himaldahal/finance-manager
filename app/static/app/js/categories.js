import {
  $, api, clearErrors, confirmDialog, emptyState, errorState, formData, h, icon, openDialog, showError, showErrors, toast,
  withBusy, wireDialog,
} from './core.js';
import { catLabel } from './parts.js';

const KIND = { both: 'Income and expense', expense: 'Expense only', income: 'Income only' };

/* ---------- categories ---------- */

const list = document.getElementById('category-list');
const dialog = document.getElementById('cat-dialog');
const form = document.getElementById('cat-form');
const delDialog = document.getElementById('del-dialog');
const delForm = document.getElementById('del-form');
let categories = [];
let editing = null;
let deleting = null;

function ordered() {
  const tops = categories.filter((c) => !c.parent);
  const out = [];
  for (const top of tops) {
    out.push({ ...top, depth: 0 });
    categories.filter((c) => c.parent === top.id).forEach((c) => out.push({ ...c, depth: 1 }));
  }
  return out;
}

function row(c) {
  return h('tr', {},
    h('td', { 'data-label': 'Name', class: c.depth ? 'sub-cat' : '' }, catLabel(c, 'span')),
    h('td', { 'data-label': 'Used for' }, h('span', { class: 'tag', text: KIND[c.kind] })),
    h('td', { class: 'num', 'data-label': 'Transactions', text: String(c.count) }),
    h('td', { class: 'row-actions' },
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': `Edit ${c.name}`, onclick: () => openEdit(c) }, icon('pencil')),
      h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': `Delete ${c.name}`, onclick: () => openDelete(c) }, icon('trash-2'))));
}

function render() {
  if (!categories.length) {
    list.className = '';
    list.replaceChildren(emptyState('No categories', 'Create a category to start recording transactions.'));
    return;
  }
  list.className = 'table-wrap';
  list.replaceChildren(h('table', { class: 'table stack' },
    h('caption', { class: 'sr-only', text: 'Categories' }),
    h('thead', {}, h('tr', {}, h('th', { text: 'Name' }), h('th', { text: 'Used for' }), h('th', { class: 'num', text: 'Transactions' }),
      h('th', {}, h('span', { class: 'sr-only', text: 'Actions' })))),
    h('tbody', {}, ...ordered().map(row))));
}

async function load() {
  try {
    categories = (await api('/api/categories/')).categories;
    render();
  } catch (error) {
    list.className = '';
    list.replaceChildren(errorState(error.message, load));
  }
}

function openEdit(category) {
  editing = category;
  clearErrors(form);
  form.reset();
  $('#cat-title').textContent = category ? 'Edit category' : 'New category';
  const parent = form.elements.parent;
  const options = categories.filter((c) => !c.parent && (!category || c.id !== category.id));
  parent.replaceChildren(h('option', { value: '', text: 'None (top level)' }), ...options.map((c) => h('option', { value: c.id, text: c.name })));
  if (category) {
    form.elements.name.value = category.name;
    form.elements.kind.value = category.kind;
    form.elements.color.value = category.color;
    form.elements.icon.value = category.icon;
    parent.value = category.parent ? String(category.parent) : '';
  }
  openDialog(dialog, '#cat-name');
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearErrors(form);
  try {
    await withBusy($('[data-submit]', form), () => api(
      editing ? `/api/categories/${editing.id}/` : '/api/categories/', { method: 'POST', body: formData(form) }));
    dialog.close();
    toast(editing ? 'Category updated.' : 'Category added.');
    await load();
    loadRules();
  } catch (error) { showErrors(form, error); }
});

function openDelete(category) {
  deleting = category;
  clearErrors(delForm);
  const others = categories.filter((c) => c.id !== category.id);
  $('#del-target').replaceChildren(...others.map((c) => h('option', { value: c.id, text: c.full_name })));
  const needs = category.count > 0;
  $('#del-reassign').hidden = !needs;
  $('#del-message').textContent = needs
    ? `“${category.name}” has ${category.count} transaction(s). Choose where they should go.`
    : `Delete “${category.name}”? This cannot be undone.`;
  $('[data-submit]', delForm).disabled = needs && !others.length;
  if (needs && !others.length) $('#del-message').textContent += ' Create another category first.';
  openDialog(delDialog, needs ? '#del-target' : '[data-submit]');
}

delForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearErrors(delForm);
  const target = $('#del-reassign').hidden ? '' : $('#del-target').value;
  try {
    await withBusy($('[data-submit]', delForm), () => api(
      `/api/categories/${deleting.id}/${target ? `?reassign_to=${encodeURIComponent(target)}` : ''}`, { method: 'DELETE' }));
    delDialog.close();
    toast('Category deleted.');
    await load();
    loadRules();
  } catch (error) {
    if (error.status === 409 || error.status === 422) showErrors(delForm, error); else showError(error);
  }
});

wireDialog(dialog);
wireDialog(delDialog);
document.getElementById('new-category').addEventListener('click', () => openEdit(null));

/* ---------- rules ---------- */

const ruleList = document.getElementById('rule-list');
const ruleDialog = document.getElementById('rule-dialog');
const ruleForm = document.getElementById('rule-form');
let rules = [];
let editingRule = null;

function renderRules() {
  if (!rules.length) {
    ruleList.className = '';
    ruleList.replaceChildren(emptyState('No rules yet', 'For example: description contains "cafe" goes to Dining out.'));
    return;
  }
  ruleList.className = '';
  ruleList.replaceChildren(h('ul', { class: 'mini-list' }, ...rules.map((r) => h('li', { class: r.active ? '' : 'inactive' },
    h('span', {}, h('code', { text: r.pattern }), ' → ', catLabel(r.category, 'span'),
      r.active ? null : h('span', { class: 'tag', text: 'Off' })),
    h('span', { class: 'row-actions' },
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': `Edit rule ${r.pattern}`, onclick: () => openRule(r) }, icon('pencil')),
      h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': `Delete rule ${r.pattern}`, onclick: () => removeRule(r) }, icon('trash-2')))))));
}

async function loadRules() {
  try {
    rules = (await api('/api/rules/')).rules;
    renderRules();
  } catch (error) {
    ruleList.className = '';
    ruleList.replaceChildren(errorState(error.message, loadRules));
  }
}

function openRule(rule) {
  editingRule = rule;
  clearErrors(ruleForm);
  ruleForm.reset();
  $('#rule-title').textContent = rule ? 'Edit rule' : 'New rule';
  $('#rule-category').replaceChildren(...categories.map((c) => h('option', { value: c.id, text: c.full_name })));
  if (rule) {
    ruleForm.elements.pattern.value = rule.pattern;
    ruleForm.elements.category.value = String(rule.category.id);
    ruleForm.elements.priority.value = rule.priority;
    ruleForm.elements.active.checked = rule.active;
  }
  openDialog(ruleDialog, '#rule-pattern');
}

ruleForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearErrors(ruleForm);
  try {
    await withBusy($('[data-submit]', ruleForm), () => api(
      editingRule ? `/api/rules/${editingRule.id}/` : '/api/rules/', { method: 'POST', body: formData(ruleForm) }));
    ruleDialog.close();
    toast('Rule saved.');
    await loadRules();
  } catch (error) { showErrors(ruleForm, error); }
});

async function removeRule(rule) {
  const ok = await confirmDialog({ title: 'Delete rule', message: `Delete the rule for “${rule.pattern}”?` });
  if (!ok) return;
  try {
    await api(`/api/rules/${rule.id}/`, { method: 'DELETE' });
    toast('Rule deleted.');
    await loadRules();
  } catch (error) { showError(error); }
}

wireDialog(ruleDialog);
document.getElementById('new-rule').addEventListener('click', () => openRule(null));

/* ---------- tags ---------- */

const tagList = document.getElementById('tag-list');

async function loadTags() {
  try {
    const { tags } = await api('/api/tags/');
    tagList.className = '';
    if (!tags.length) {
      tagList.replaceChildren(emptyState('No tags yet', 'Add tags when you record a transaction.'));
      return;
    }
    tagList.replaceChildren(h('ul', { class: 'mini-list' }, ...tags.map((t) => h('li', {},
      h('span', {}, h('a', { class: 'tag-chip', href: `/transactions/?tag=${t.id}`, text: t.name }), h('span', { class: 'muted small', text: ` ${t.count} transaction(s)` })),
      h('span', { class: 'row-actions' },
        h('button', { class: 'icon-btn danger', type: 'button', 'aria-label': `Delete tag ${t.name}`, onclick: () => removeTag(t) }, icon('trash-2')))))));
  } catch (error) {
    tagList.className = '';
    tagList.replaceChildren(errorState(error.message, loadTags));
  }
}

async function removeTag(tag) {
  const ok = await confirmDialog({ title: 'Delete tag', message: `Remove the tag “${tag.name}” from all transactions?` });
  if (!ok) return;
  try {
    await api(`/api/tags/${tag.id}/`, { method: 'DELETE' });
    toast('Tag deleted.');
    await loadTags();
  } catch (error) { showError(error); }
}

load().then(loadRules);
loadTags();
