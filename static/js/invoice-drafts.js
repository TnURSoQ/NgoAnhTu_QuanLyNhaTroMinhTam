(() => {
  const form = document.getElementById('draftsForm');
  if (!form) return;
  const money = value => Math.trunc(value).toLocaleString('vi-VN') + ' đ';
  const field = (row, name) => row.querySelector(`[name$="-${name}"]`);
  const number = input => {
    const value = input.value.trim().replace(',', '.');
    return /^\d+(\.\d{1,2})?$/.test(value) ? Number(value) : null;
  };
  function preview(row) {
    let total = 0, complete = true, invalid = false;
    for (const utility of ['electric', 'water']) {
      const old = number(field(row, 'old_' + utility));
      const next = number(field(row, 'new_' + utility));
      const priceText = row.dataset[utility + 'Price'];
      const price = priceText === '' ? null : Number(priceText);
      const target = row.querySelector('.' + utility + '-preview');
      if (old === null || next === null || price === null) {
        complete = false;
        target.textContent = 'Chờ nhập đủ chỉ số và đơn giá';
      } else if (next < old || price <= 0) {
        invalid = true;
        target.textContent = next < old ? 'Chỉ số mới phải ≥ chỉ số cũ' : 'Cần đơn giá lớn hơn 0';
      } else {
        const hundredths = Math.round(next * 100) - Math.round(old * 100);
        const fee = Math.trunc(hundredths * price / 100);
        total += fee;
        target.textContent = (hundredths / 100).toLocaleString('vi-VN') +
          (utility === 'electric' ? ' kWh · ' : ' m³ · ') + money(fee);
      }
    }
    const roomText = field(row, 'room_fee').value.trim().replaceAll('.', '');
    const roomFee = /^\d+$/.test(roomText) ? Number(roomText) : null;
    if (roomFee === null) invalid = true;
    total += (roomFee || 0) + Number(row.dataset.services);
    if (total > 99999999) invalid = true;
    row.querySelector('.draft-total').textContent = invalid ? 'Kiểm tra số liệu' :
      complete ? money(total) : 'Chờ nhập đủ chỉ số';
    const badge = row.querySelector('.draft-status');
    badge.textContent = invalid ? 'Cần kiểm tra' : complete ? 'Đủ thông tin' : 'Chờ chỉ số / đơn giá';
    badge.className = 'badge draft-status ' + (invalid ? 'text-bg-danger' :
      complete ? 'text-bg-success' : 'text-bg-secondary');
  }
  const rows = [...form.querySelectorAll('.draft-row')];
  const selectAll = document.getElementById('selectAllDrafts');
  const boxes = rows.map(row => field(row, 'selected'));
  function selection() {
    const count = boxes.filter(box => box.checked).length;
    document.getElementById('draftSelectionCount').textContent = `Đã chọn ${count}/${boxes.length} phòng`;
    selectAll.checked = count === boxes.length;
    selectAll.indeterminate = count > 0 && count < boxes.length;
  }
  rows.forEach(row => {
    row.addEventListener('input', () => preview(row));
    preview(row);
  });
  boxes.forEach(box => box.addEventListener('change', selection));
  selectAll.addEventListener('change', () => {
    boxes.forEach(box => { box.checked = selectAll.checked; });
    selection();
  });
  selection();
})();
