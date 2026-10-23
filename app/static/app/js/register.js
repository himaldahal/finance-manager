// Sign-up form: per-field inline checks and a debounced username availability lookup.
import { api, debounce } from './core.js';
import { passwordProblem, setHint } from './password.js';

const form = document.querySelector('form[data-validate="register"]');
if (form) {
  const el = (id) => document.getElementById(id);
  const hintOf = (input) => input.closest('.field').querySelector('[data-hint]');
  const touched = new Set();
  let usernameState = { value: '', ok: null };

  const checks = {
    id_full_name(input) {
      if (!input.value.trim()) return 'Enter your name. One word is fine.';
      return '';
    },
    id_username(input) {
      const value = input.value.trim();
      if (!value) return 'Choose a username.';
      if (value.length > 150) return 'Use 150 characters or fewer.';
      if (!/^[\w.@+-]+$/.test(value)) return 'Use letters, numbers and @ . + - _ only.';
      if (usernameState.value === value.toLowerCase() && usernameState.ok === false) return 'That username is already taken.';
      return '';
    },
    id_email(input) {
      const value = input.value.trim();
      if (!value) return 'Enter your email address.';
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return 'That does not look like an email address.';
      return '';
    },
    id_password1: (input) => (input.value ? passwordProblem(input) : 'Choose a password.'),
    id_password2: (input) => (input.value !== el('id_password1').value ? 'The two passwords do not match yet.' : (input.value ? '' : 'Repeat the password.')),
  };

  function show(input, quiet = false) {
    const problem = checks[input.id](input);
    if (input.id === 'id_password1' || input.id === 'id_password2') return problem; // password.js renders these
    if (!touched.has(input.id) && !quiet) return problem;
    const ok = !problem && input.value.trim() !== '';
    setHint(hintOf(input), problem || (ok ? (input.id === 'id_username' && usernameState.ok ? 'Username is available.' : 'Looks good.') : ''), ok);
    if (problem) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid');
    return problem;
  }

  const lookup = debounce(async (input) => {
    const value = input.value.trim().toLowerCase();
    if (!value || !/^[\w.@+-]+$/.test(value)) return;
    try {
      const data = await api(form.dataset.availabilityUrl, { query: { u: value } });
      usernameState = { value, ok: data.available };
      if (input.value.trim().toLowerCase() === value) show(input, true);
    } catch (error) {
      // availability is a convenience; the server decides on submit
    }
  }, 450);

  for (const id of ['id_full_name', 'id_username', 'id_email']) {
    const input = el(id);
    input.addEventListener('input', () => {
      touched.add(id);
      show(input);
      if (id === 'id_username') lookup(input);
    });
    input.addEventListener('blur', () => { touched.add(id); show(input); });
  }

  form.addEventListener('submit', (event) => {
    const order = ['id_full_name', 'id_username', 'id_email', 'id_password1', 'id_password2'];
    for (const id of order) {
      const input = el(id);
      touched.add(id);
      if (show(input, true)) {
        event.preventDefault();
        if (id.startsWith('id_password')) input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
        return;
      }
    }
  });
}
