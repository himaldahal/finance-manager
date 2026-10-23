// Password fields: show/hide, caps lock warning, live checks with one short message, strength meter, match indicator.
import { icon } from './core.js';
import { COMMON } from './common-passwords.js';

function swap(button, show) {
  button.setAttribute('aria-pressed', String(show));
  button.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  button.replaceChildren(icon(show ? 'eye-off' : 'eye'));
}

function score(value) {
  if (!value) return 0;
  let points = 0;
  if (value.length >= 10) points += 1;
  if (value.length >= 14) points += 1;
  if (/[a-z]/.test(value) && /[A-Z]/.test(value)) points += 1;
  if (/\d/.test(value)) points += 1;
  if (/[^A-Za-z0-9]/.test(value)) points += 1;
  if (/^(.)\1+$/.test(value) || COMMON.has(value.toLowerCase())) points = Math.min(points, 1);
  return Math.min(points, 4);
}

const LABELS = ['Too weak', 'Weak', 'Fair', 'Good', 'Strong'];

/** Words from other fields (or a data attribute) that a password should not contain. */
function personalWords(input) {
  const words = [];
  const ids = (input.dataset.similarTo || '').split(/\s+/).filter(Boolean);
  for (const id of ids) {
    const el = document.getElementById(id);
    if (el && el.value) words.push(...el.value.toLowerCase().split(/[\s@.+_-]+/));
  }
  if (input.dataset.similarWords) words.push(...input.dataset.similarWords.toLowerCase().split(/[\s@.+_-]+/));
  return words.filter((w) => w.length >= 3);
}

/** The first unmet rule as a short sentence, or '' when the password looks fine. */
export function passwordProblem(input) {
  const value = input.value;
  const min = Number(input.dataset.minLength) || 8;
  if (value.length < min) return `Use at least ${min} characters (${value.length} so far).`;
  if (/^\d+$/.test(value)) return 'Add some letters. A password of only digits is not allowed.';
  const lower = value.toLowerCase();
  if (personalWords(input).some((w) => lower.includes(w))) return 'Avoid your name, username or email inside the password.';
  if (COMMON.has(lower)) return 'That password is very common. Try something less guessable.';
  return '';
}

export function setHint(node, text, ok) {
  if (!node) return;
  node.hidden = !text;
  node.textContent = text;
  node.classList.toggle('ok', Boolean(ok));
  node.classList.toggle('bad', Boolean(text) && !ok);
}

for (const input of document.querySelectorAll('input[type="password"]')) {
  const field = input.closest('.field');
  const button = field && field.querySelector('[data-pw-toggle]');
  if (button) {
    button.hidden = false;
    swap(button, false);
    button.addEventListener('click', () => {
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      swap(button, show);
      input.focus();
    });
  }
  const caps = field && field.querySelector('[data-caps]');
  if (caps) {
    const check = (event) => { if (event.getModifierState) caps.hidden = !event.getModifierState('CapsLock'); };
    input.addEventListener('keydown', check);
    input.addEventListener('keyup', check);
    input.addEventListener('blur', () => { caps.hidden = true; });
  }
  const meter = field && field.querySelector('[data-meter]');
  const message = field && field.querySelector('[data-pw-message]');
  if (input.hasAttribute('data-strength')) {
    const bar = meter && meter.querySelector('.meter-bar');
    const label = meter && meter.querySelector('.meter-label');
    const update = () => {
      if (!input.value) {
        if (meter) meter.hidden = true;
        setHint(message, '', false);
        input.removeAttribute('aria-invalid');
        return;
      }
      const problem = passwordProblem(input);
      setHint(message, problem || 'Looks good.', !problem);
      if (problem) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid');
      if (meter) {
        const s = score(input.value);
        meter.hidden = false;
        meter.dataset.level = String(s);
        bar.style.width = `${(s + 1) * 20}%`;
        label.textContent = `Strength: ${LABELS[s]}`;
      }
    };
    input.addEventListener('input', update);
    // names typed after the password change the verdict
    for (const id of (input.dataset.similarTo || '').split(/\s+/).filter(Boolean)) {
      const other = document.getElementById(id);
      if (other) other.addEventListener('input', () => { if (input.value) update(); });
    }
  }
  const target = input.getAttribute('data-match');
  const note = field && field.querySelector('[data-match-note]');
  if (target && note) {
    const other = document.getElementById(target);
    const update = () => {
      note.hidden = !input.value;
      const same = input.value === other.value;
      note.textContent = same ? 'Passwords match.' : 'The two passwords do not match yet.';
      note.classList.toggle('ok', same);
      if (input.value && !same) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid');
    };
    input.addEventListener('input', update);
    other.addEventListener('input', () => { if (input.value) update(); });
  }
}

/* Block the submit (button stays enabled) and focus the first invalid password field. The server still validates. */
for (const form of document.querySelectorAll('form[data-validate="password"]')) {
  form.addEventListener('submit', (event) => {
    const fields = Array.from(form.querySelectorAll('input[data-strength], input[data-match]'));
    for (const input of fields) {
      let bad = false;
      if (input.hasAttribute('data-strength')) bad = Boolean(passwordProblem(input));
      else bad = input.value !== document.getElementById(input.dataset.match).value;
      if (bad || !input.value) {
        event.preventDefault();
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
        return;
      }
    }
  });
}
