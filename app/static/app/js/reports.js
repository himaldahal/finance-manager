const form = document.getElementById('report-form');
if (form) {
  const preset = form.elements.preset;
  const custom = [form.elements.start, form.elements.end];
  const sync = () => custom.forEach((el) => { el.disabled = preset.value !== 'custom'; });
  sync();
  preset.addEventListener('change', () => {
    sync();
    if (preset.value !== 'custom') form.submit();
  });
}
document.querySelectorAll('[data-print]').forEach((button) => button.addEventListener('click', () => window.print()));
