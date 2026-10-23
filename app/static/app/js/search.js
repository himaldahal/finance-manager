// Global quick search: an ARIA combobox in a dialog, results fetched as you type.
import { $, api, debounce, h, openDialog, recall, remember, wireDialog } from './core.js';

const dialog = document.getElementById('search-dialog');
const input = document.getElementById('search-input');
const list = document.getElementById('search-results');
const hint = document.getElementById('search-hint');
let options = [];
let active = -1;
let sequence = 0;

function setActive(index) {
  options.forEach((option, i) => {
    const on = i === index;
    option.setAttribute('aria-selected', String(on));
    option.classList.toggle('active', on);
  });
  active = index;
  const current = options[index];
  if (current) {
    input.setAttribute('aria-activedescendant', current.id);
    current.scrollIntoView({ block: 'nearest' });
  } else {
    input.removeAttribute('aria-activedescendant');
  }
}

function render(groups) {
  options = [];
  const nodes = [];
  let n = 0;
  for (const group of groups) {
    nodes.push(h('div', { class: 'search-group', role: 'presentation', text: group.type }));
    for (const item of group.items) {
      const option = h('a', { class: 'search-option', role: 'option', id: `search-opt-${n++}`, href: item.url, 'aria-selected': 'false' },
        h('span', { class: 'search-title', text: item.title }), h('span', { class: 'muted small', text: item.subtitle }));
      options.push(option);
      nodes.push(option);
    }
  }
  list.replaceChildren(...nodes);
  input.setAttribute('aria-expanded', String(options.length > 0));
  hint.hidden = options.length > 0;
  setActive(options.length ? 0 : -1);
}

const run = debounce(async () => {
  const q = input.value.trim();
  const mine = ++sequence;
  if (q.length < 2) {
    render([]);
    showDefaults();
    hint.textContent = 'Type at least 2 characters. Try "food last month over 500".';
    return;
  }
  hint.textContent = 'Searching...';
  hint.hidden = false;
  try {
    const data = await api('/api/search/', { query: { q } });
    if (mine !== sequence) return;
    render(data.groups);
    if (!data.groups.length) { hint.textContent = `No results for “${q}”.`; hint.hidden = false; }
  } catch (error) {
    if (mine !== sequence) return;
    render([]);
    hint.textContent = error.message;
    hint.hidden = false;
  }
}, 200);

function recents() {
  try { return JSON.parse(recall('recent') || '[]'); } catch (e) { return []; }
}

function rememberItem(item) {
  const list = recents().filter((r) => r.url !== item.url);
  list.unshift({ title: item.title, subtitle: item.subtitle, url: item.url });
  remember('recent', JSON.stringify(list.slice(0, 5)));
}

/** With an empty box, offer recent results and the saved views (favourites). */
async function showDefaults() {
  const groups = [];
  const recent = recents();
  if (recent.length) groups.push({ type: 'Recent', items: recent });
  try {
    const { views } = await api('/api/views/');
    if (views.length) {
      groups.push({ type: 'Saved views', items: views.slice(0, 5).map((v) => ({
        title: v.name, subtitle: 'Saved filters', url: `/transactions/?${v.query}` })) });
    }
  } catch (e) { /* optional */ }
  if (!input.value.trim()) render(groups);
}

export function openSearch() {
  if (!dialog) return;
  input.value = '';
  render([]);
  hint.textContent = 'Type at least 2 characters. Try "food last month over 500". Use the arrow keys and Enter.';
  hint.hidden = false;
  openDialog(dialog, '#search-input');
  showDefaults();
}

function go(option) {
  rememberItem({ title: option.querySelector('.search-title').textContent, subtitle: option.querySelector('.muted').textContent, url: option.getAttribute('href') });
  window.location.assign(option.getAttribute('href'));
}

if (dialog) {
  wireDialog(dialog);
  input.addEventListener('input', run);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown') { event.preventDefault(); if (options.length) setActive((active + 1) % options.length); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); if (options.length) setActive((active - 1 + options.length) % options.length); }
    else if (event.key === 'Enter' && options[active]) { event.preventDefault(); go(options[active]); }
  });
  list.addEventListener('click', (event) => {
    const link = event.target.closest('.search-option');
    if (link) { event.preventDefault(); go(link); }
  });
  list.addEventListener('mousemove', (event) => {
    const index = options.indexOf(event.target.closest('.search-option'));
    if (index >= 0 && index !== active) setActive(index);
  });
}
