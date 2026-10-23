// Shared helpers: DOM builder, API client, toasts, dialogs, form helpers.
import { config, formatNumber } from './format.js';
export { formatMoney, formatNumber } from './format.js';

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const SVG_NS = 'http://www.w3.org/2000/svg';

/** Create an element. Strings become text nodes (never HTML). */
export function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  applyAttrs(node, attrs);
  append(node, children);
  return node;
}

export function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  applyAttrs(node, attrs);
  append(node, children);
  return node;
}

function applyAttrs(node, attrs) {
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.setAttribute('class', value);
    else if (key === 'text') node.textContent = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? '' : String(value));
  }
}

function append(node, children) {
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

function spriteUrl() {
  const meta = document.querySelector('meta[name="sprite"]');
  return document.body.dataset.sprite || (meta ? meta.content : '');
}

/** An icon from the self-hosted sprite (Lucide). */
export function icon(name, cssClass = '') {
  const node = svg('svg', { class: `icon ${cssClass}`.trim(), 'aria-hidden': 'true', focusable: 'false' });
  const use = svg('use');
  use.setAttribute('href', `${spriteUrl()}#${name}`);
  node.append(use);
  return node;
}

export function debounce(fn, wait = 250) {
  let timer;
  const wrapped = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
  wrapped.cancel = () => clearTimeout(timer);
  return wrapped;
}

export function readJson(id, fallback = null) {
  const node = document.getElementById(id);
  if (!node) return fallback;
  try { return JSON.parse(node.textContent); } catch (e) { return fallback; }
}

/* ---------- API ---------- */

export class ApiError extends Error {
  constructor(status, message, errors = {}) {
    super(message);
    this.status = status;
    this.errors = errors;
  }
}

function csrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.content : '';
}

/* ---------- system status: saving, saved, offline ---------- */

let statusTimer;
export function setStatus(text, offline = false) {
  const node = document.getElementById('sys-status');
  if (!node) return;
  node.textContent = text;
  node.classList.toggle('offline', offline);
  clearTimeout(statusTimer);
  if (text && !offline) statusTimer = setTimeout(() => { if (navigator.onLine) node.textContent = ''; }, 2200);
}
window.addEventListener('offline', () => setStatus('You are offline. Changes will not be saved.', true));
window.addEventListener('online', () => setStatus('Back online'));

export async function api(path, { method = 'GET', body, query } = {}) {
  if (method !== 'GET') setStatus('Saving...');
  let url = path;
  if (query) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== '' && value !== null && value !== undefined) params.set(key, value);
    }
    const text = params.toString();
    if (text) url += (url.includes('?') ? '&' : '?') + text;
  }
  const headers = { Accept: 'application/json', 'X-Requested-With': 'fetch' };
  const init = { method, headers, credentials: 'same-origin' };
  if (method !== 'GET') headers['X-CSRFToken'] = csrfToken();
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(url, init);
  } catch (e) {
    setStatus(navigator.onLine ? 'Could not reach the server' : 'You are offline. Changes will not be saved.', true);
    throw new ApiError(0, 'Could not reach the server. Check your connection and try again.');
  }
  let data = null;
  try { data = await response.json(); } catch (e) { /* non JSON */ }
  if (response.status === 401) {
    window.location.assign('/login/?next=' + encodeURIComponent(window.location.pathname));
    throw new ApiError(401, 'Please sign in again.');
  }
  if (method !== 'GET' && response.ok) setStatus('Saved');
  if (method !== 'GET' && !response.ok) setStatus('');
  if (!response.ok || !data || data.ok === false) {
    const fallback = response.status >= 500 ? 'The server had a problem. Please try again.' : 'The request failed.';
    throw new ApiError(response.status, (data && data.message) || fallback, (data && data.errors) || {});
  }
  return data;
}

/* ---------- toasts ---------- */

export function toast(message, { kind = 'success', action = null, timeout = 5000 } = {}) {
  const host = document.getElementById('toasts');
  if (!host) return null;
  const node = h('div', { class: `toast ${kind}` }, h('span', { text: message }));
  const remove = () => node.remove();
  if (action) {
    node.append(h('button', {
      type: 'button', text: action.label,
      onclick: async () => { remove(); await action.onClick(); },
    }));
  }
  host.append(node);
  if (timeout) setTimeout(remove, action ? Math.max(timeout, 8000) : timeout);
  return node;
}

export function showError(error) {
  toast(error instanceof ApiError ? error.message : 'Something went wrong.', { kind: 'error', timeout: 7000 });
}

/* ---------- dialogs ---------- */

export function openDialog(dialog, focusSelector) {
  const opener = document.activeElement;
  if (!dialog.open) dialog.showModal();
  const target = focusSelector ? dialog.querySelector(focusSelector) : null;
  if (target) target.focus();
  dialog.addEventListener('close', () => {
    if (opener && document.contains(opener)) opener.focus();
  }, { once: true });
}

export function wireDialog(dialog) {
  dialog.addEventListener('click', (event) => {
    if (event.target.closest('[data-close]')) dialog.close();
    else if (event.target === dialog) dialog.close();
  });
}

export function confirmDialog({ title = 'Are you sure?', message = '', confirmLabel = 'Delete', danger = true } = {}) {
  const dialog = document.getElementById('confirm-dialog');
  dialog.querySelector('#confirm-title').textContent = title;
  dialog.querySelector('#confirm-message').textContent = message;
  const ok = dialog.querySelector('[data-ok]');
  ok.textContent = confirmLabel;
  ok.classList.toggle('btn-danger', danger);
  ok.classList.toggle('btn-primary', !danger);
  return new Promise((resolve) => {
    dialog.returnValue = '';
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'ok'), { once: true });
    openDialog(dialog, '[data-cancel]');
  });
}

/* ---------- forms ---------- */

export function clearErrors(form) {
  $$('[data-error-for]', form).forEach((node) => { node.textContent = ''; });
  $$('[aria-invalid]', form).forEach((node) => node.removeAttribute('aria-invalid'));
  const box = $('[data-form-error]', form);
  if (box) { box.hidden = true; box.textContent = ''; }
}

export function showErrors(form, error) {
  clearErrors(form);
  let general = [];
  const errors = error.errors || {};
  for (const [field, messages] of Object.entries(errors)) {
    const slot = form.querySelector(`[data-error-for="${CSS.escape(field)}"]`);
    if (slot && field !== '__all__') {
      slot.textContent = messages.join(' ');
      const input = form.querySelector(`[name="${CSS.escape(field)}"]`);
      if (input) input.setAttribute('aria-invalid', 'true');
    } else {
      general = general.concat(messages);
    }
  }
  if (!general.length && !Object.keys(errors).length) general = [error.message];
  const box = $('[data-form-error]', form);
  if (box && general.length) { box.textContent = general.join(' '); box.hidden = false; }
  const first = form.querySelector('[aria-invalid="true"]');
  if (first) first.focus();
}

export function formData(form) {
  const data = {};
  for (const [key, value] of new FormData(form).entries()) data[key] = value;
  for (const input of $$('input[data-money]', form)) data[input.name] = parseMoney(input.value);
  for (const input of $$('input[type="checkbox"]', form)) data[input.name] = input.checked;
  return data;
}

/* ---------- money inputs: thousands separators while keeping a plain decimal for the server ---------- */

const GROUP = { intl: ',', indian: ',', eu: '.', space: ' ' };
const DECIMAL = { intl: '.', indian: '.', eu: ',', space: ',' };

export function parseMoney(text) {
  let value = String(text || '').replace(/[\s\u00a0\u202f]/g, '');
  if (!value) return '';
  const format = config.format;
  const group = GROUP[format];
  const decimal = DECIMAL[format];
  if (decimal === ',' && !value.includes(',') && /^-?\d+\.\d{1,2}$/.test(value)) return value;
  if (group && group !== ' ') value = value.split(group).join('');
  if (decimal !== '.') value = value.replace(decimal, '.');
  return /^-?\d*\.?\d*$/.test(value) ? value : String(text);
}

export function setMoney(input, value) {
  input.value = value === '' || value === null || value === undefined ? '' : formatNumber(value);
}

export function wireMoneyInputs(root = document) {
  for (const input of $$('input[data-money]', root)) {
    if (input.dataset.moneyWired) continue;
    input.dataset.moneyWired = '1';
    input.addEventListener('blur', () => {
      const plain = parseMoney(input.value);
      if (plain !== '' && /^-?\d*\.?\d+$|^-?\d+\.$/.test(plain) && Number.isFinite(Number(plain))) {
        if (!(input.hasAttribute('data-signed')) && Number(plain) < 0) return;
        setMoney(input, plain);
      }
    });
  }
}

export async function withBusy(button, task) {
  button.disabled = true;
  button.setAttribute('aria-busy', 'true');
  try { return await task(); } finally {
    button.disabled = false;
    button.removeAttribute('aria-busy');
  }
}

/* ---------- states ---------- */

export function errorState(message, retry) {
  const box = h('div', { class: 'state-error', role: 'alert' }, h('span', { text: message }));
  if (retry) box.append(h('button', { class: 'btn btn-sm', type: 'button', text: 'Try again', onclick: retry }));
  return box;
}

export function emptyState(title, text, button) {
  return h('div', { class: 'empty' }, h('h3', { text: title }), h('p', { text }), button || null);
}

export function tone(color) { return h('span', { class: `tone tone-${color}` }); }

export function remember(key, value) {
  try { localStorage.setItem(`fm:${key}`, value); } catch (e) { /* storage unavailable */ }
}
export function recall(key) {
  try { return localStorage.getItem(`fm:${key}`); } catch (e) { return null; }
}

export function today(offsetDays = 0) {
  const now = new Date();
  now.setDate(now.getDate() + offsetDays);
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
