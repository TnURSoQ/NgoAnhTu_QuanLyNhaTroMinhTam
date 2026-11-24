document.querySelectorAll('[data-payment-correction]').forEach(form => {
  const action = form.elements.namedItem('action');
  const fields = form.querySelector('[data-replacement-fields]');
  const update = () => {
    const adjust = action.value === 'adjust';
    fields.hidden = !adjust;
    for (const input of fields.querySelectorAll('input,select,textarea')) input.disabled = !adjust;
  };
  action.addEventListener('change', update);
  update();
});
