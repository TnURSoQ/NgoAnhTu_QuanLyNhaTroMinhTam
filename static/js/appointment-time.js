document.querySelectorAll('[data-appointment-form]').forEach(form => {
  const select = form.querySelector('[data-appointment-start]');
  if (!select) return;
  const slot = form.querySelector('[name=slot]');
  const update = () => {
    const current = slot?.value || form.dataset.fixedSlot;
    for (const option of select.options) {
      const available = !option.value || option.dataset.slot === current;
      option.hidden = !available;
      option.disabled = !available;
      if (option.selected && !available) select.value = '';
    }
    for (const group of select.querySelectorAll('optgroup')) {
      group.hidden = !Array.from(group.children).some(option => !option.hidden);
    }
  };
  slot?.addEventListener('change', update);
  update();
});
