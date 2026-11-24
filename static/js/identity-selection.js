document.querySelectorAll('[data-identity-selection]').forEach(form => {
  const checks = [...form.querySelectorAll('[name=ids]')];
  const all = [...form.querySelectorAll('[data-select-all]')];
  const total = new Set(checks.map(input => input.value)).size;
  const sync = () => {
    const count = new Set(checks.filter(input => input.checked).map(input => input.value)).size;
    for (const input of all) { input.checked = count === total && total > 0; input.indeterminate = count > 0 && count < total; }
    for (const button of form.querySelectorAll('[data-selection-action]')) button.disabled = count === 0;
    form.querySelector('[data-selection-count]').textContent = `Đã chọn ${count}/${total} hồ sơ. Bản in xếp ảnh mặt trước và mặt sau theo từng phòng.`;
  };
  for (const input of checks) input.addEventListener('change', () => {
    for (const other of checks) if (other.value === input.value) other.checked = input.checked;
    sync();
  });
  for (const input of all) input.addEventListener('change', () => { for (const item of checks) item.checked = input.checked; sync(); });
  sync();
});
