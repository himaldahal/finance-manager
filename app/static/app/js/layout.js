// Behaviour shared by every signed-in page: menu, shortcuts, flash messages.
import { $, $$, icon, toast } from './core.js';
import { openTransactionDialog } from './tx-dialog.js';
import { openSearch } from './search.js';
import { api } from './core.js';

const body = document.body;
const root = document.documentElement;
const sidebar = document.getElementById('sidebar');
const toggle = document.getElementById('nav-toggle');
const collapseButton = document.getElementById('sidebar-collapse');
const mobile = window.matchMedia('(max-width: 860px)');

function store(key, value) { try { localStorage.setItem(`fm:${key}`, value); } catch (e) { /* ignore */ } }
function load(key) { try { return localStorage.getItem(`fm:${key}`); } catch (e) { return null; } }

/* ---------- desktop: collapse to an icon rail ---------- */

function setCollapsed(collapsed, persist = true) {
  if (collapsed) root.setAttribute('data-sidebar', 'collapsed'); else root.removeAttribute('data-sidebar');
  if (collapseButton) {
    collapseButton.setAttribute('aria-expanded', String(!collapsed));
    collapseButton.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
    collapseButton.replaceChildren(icon(collapsed ? 'panel-left-open' : 'panel-left-close'));
  }
  if (persist) store('sidebar', collapsed ? 'collapsed' : 'expanded');
}

if (collapseButton) {
  collapseButton.hidden = false;
  setCollapsed(root.getAttribute('data-sidebar') === 'collapsed', false);
  collapseButton.addEventListener('click', () => setCollapsed(root.getAttribute('data-sidebar') !== 'collapsed'));
}

/* ---------- groups that fold ---------- */

$$('.nav-group').forEach((group) => {
  const button = $('.nav-group-toggle', group);
  const panel = $('.nav-group-body', group);
  const key = `group-${group.dataset.group}`;
  const set = (open) => {
    button.setAttribute('aria-expanded', String(open));
    panel.hidden = !open;
    group.classList.toggle('folded', !open);
  };
  button.hidden = false;
  const hasCurrent = Boolean($('[aria-current="page"]', panel));
  set(hasCurrent || load(key) !== 'closed');
  button.addEventListener('click', () => {
    const open = button.getAttribute('aria-expanded') !== 'true';
    set(open);
    store(key, open ? 'open' : 'closed');
  });
});

/* ---------- small screens: off-canvas drawer ---------- */

let drawerOpener = null;

function focusables() {
  return $$('a[href], button:not([disabled]), input, select', sidebar).filter((el) => !el.hidden && el.offsetParent !== null);
}

function setDrawer(open) {
  body.classList.toggle('nav-open', open);
  if (toggle) {
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
  }
  syncInert();
  if (open) {
    drawerOpener = document.activeElement;
    const first = focusables()[0];
    if (first) first.focus();
  } else if (drawerOpener) {
    drawerOpener.focus();
    drawerOpener = null;
  }
}

/* While the drawer is closed on a small screen it is not reachable by keyboard or screen reader. */
function syncInert() {
  const hidden = mobile.matches && !body.classList.contains('nav-open');
  sidebar.inert = hidden;
  if (hidden) sidebar.setAttribute('aria-hidden', 'true'); else sidebar.removeAttribute('aria-hidden');
}

if (toggle) {
  toggle.addEventListener('click', () => setDrawer(!body.classList.contains('nav-open')));
  document.getElementById('scrim').addEventListener('click', () => setDrawer(false));
  sidebar.addEventListener('keydown', (event) => {
    if (event.key !== 'Tab' || !body.classList.contains('nav-open')) return;
    const items = focusables();
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && body.classList.contains('nav-open') && !$('dialog[open]')) setDrawer(false);
  });
  $$('#sidebar a').forEach((link) => link.addEventListener('click', () => { body.classList.remove('nav-open'); }));
}
mobile.addEventListener('change', () => { body.classList.remove('nav-open'); if (toggle) toggle.setAttribute('aria-expanded', 'false'); syncInert(); });
syncInert();

// Server messages become toasts; without JavaScript they stay visible as notices.
const flash = $('[data-flash]');
if (flash) {
  $$('li', flash).forEach((item) => {
    const level = item.dataset.level;
    toast(item.textContent, { kind: level === 'error' ? 'error' : level === 'warning' ? 'warn' : 'success', timeout: 6000 });
  });
  flash.remove();
}

document.addEventListener('click', (event) => {
  if (event.target.closest('[data-open-search]')) {
    event.preventDefault();
    if (body.classList.contains('nav-open')) setDrawer(false);
    openSearch();
    return;
  }
  if (event.target.closest('[data-new-transaction]')) {
    event.preventDefault();
    openTransactionDialog();
  }
});

function typing(target) {
  if (!target || !target.closest) return false;
  return target.closest('input, textarea, select, [contenteditable="true"]') !== null;
}

document.addEventListener('keydown', (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey || typing(event.target)) return;
  if ($('dialog[open]')) return;
  if (event.key === 'n') {
    event.preventDefault();
    openTransactionDialog();
  } else if (event.key === '/') {
    event.preventDefault();
    openSearch();
  } else if (event.key === '[') {
    event.preventDefault();
    if (mobile.matches) setDrawer(!body.classList.contains('nav-open'));
    else setCollapsed(root.getAttribute('data-sidebar') !== 'collapsed');
  } else if (event.key === '?') {
    event.preventDefault();
    const help = document.getElementById('help-dialog');
    help.showModal();
  }
});

// Alert count in the top bar.
const count = document.querySelector('[data-bell-count]');
if (count) {
  api('/api/notifications/').then((data) => {
    if (data.count) { count.textContent = String(data.count); count.hidden = false; }
  }).catch(() => {});
}

$$('dialog').forEach((dialog) => {
  if (dialog.id === 'help-dialog' || dialog.id === 'confirm-dialog') {
    dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
  }
});

if (window.location.hash === '#new') {
  history.replaceState(null, '', window.location.pathname + window.location.search);
  openTransactionDialog();
}
