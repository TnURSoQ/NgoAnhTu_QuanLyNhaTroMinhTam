(() => {
  const method = document.getElementById('id_contact_method');
  const group = document.getElementById('maintenanceContactPhone');
  const phone = document.getElementById('id_contact_phone');
  if (!method || !group || !phone) return;
  const update = () => {
    const byPhone = method.value === 'dien_thoai';
    group.hidden = !byPhone;
    phone.required = byPhone;
    phone.disabled = !byPhone;
  };
  method.setAttribute('aria-controls', group.id);
  method.addEventListener('change', update);
  window.addEventListener('pageshow', update);
  update();
})();
