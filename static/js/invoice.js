(() => {
  'use strict';
  const form = document.getElementById('invoiceForm');
  const field = name => form.elements.namedItem(name);
  const defaults = JSON.parse(document.getElementById('roomDefaults').textContent);
  const rates = {electric: Number(JSON.parse(document.getElementById('electricRate').textContent)),
                 water: Number(JSON.parse(document.getElementById('waterRate').textContent))};
  const fmt = value => Number(value).toLocaleString('vi-VN', {maximumFractionDigits: 2});
  const moneyFmt = value => Math.trunc(Number(value)).toLocaleString('vi-VN', {maximumFractionDigits: 0});
  const money = value => Math.trunc(Number(value.trim().replace(/\s|\./g, '').replace(',', '.'))) || 0;
  const decimal = value => value === '' ? NaN : Number(value.replace(',', '.'));
  function preview() {
    let total = money(field('room_fee').value);
    for (const utility of ['electric', 'water']) {
      const oldValue = decimal(field('old_' + utility).value);
      const newValue = decimal(field('new_' + utility).value);
      const usage = newValue - oldValue;
      const target = document.getElementById(utility + 'Preview');
      target.classList.toggle('text-danger', Number.isFinite(usage) && usage < 0);
      if (!Number.isFinite(usage)) target.textContent = 'Nhập đủ chỉ số để tính tiền.';
      else if (usage < 0) target.textContent = 'Chỉ số mới không được nhỏ hơn chỉ số cũ.';
      else {
        const usageHundredths = Math.round(newValue * 100) - Math.round(oldValue * 100);
        const amount = Math.floor(usageHundredths * rates[utility] / 100);
        total += amount;
        target.textContent = fmt(usage) + (utility === 'electric' ? ' kWh' : ' m³') + ' x ' +
          moneyFmt(rates[utility]) + ' đ = ' + moneyFmt(amount) + ' đ';
      }
    }
    document.querySelectorAll('.invoice-line').forEach(row => {
      const removed = row.querySelector('[name$="-DELETE"]').checked;
      row.classList.toggle('opacity-50', removed);
      const amount = money(row.querySelector('[name$="-unit_price"]').value) *
        Number(row.querySelector('[name$="-quantity"]').value || 0);
      row.querySelector('.line-subtotal').textContent = moneyFmt(amount);
      if (!removed) total += amount;
    });
    document.getElementById('totalPreview').textContent = moneyFmt(total) + ' đ';
  }
  field('room').addEventListener('change', () => {
    const data = defaults[field('room').value];
    field('room_fee').value = data ? moneyFmt(data.price) : '';
    for (const utility of ['electric', 'water']) {
      field('old_' + utility).value = data ? data['old_' + utility] : '';
      field('old_' + utility).disabled = Boolean(data && data.has_previous_reading);
      field('new_' + utility).value = '';
    }
    document.getElementById('invoiceLines').replaceChildren();
    field('items-TOTAL_FORMS').value = '0';
    (data ? data.service_items || [] : []).forEach((item, index) => {
      const html = document.getElementById('emptyLine').innerHTML.replace(/__prefix__/g, String(index));
      document.getElementById('invoiceLines').insertAdjacentHTML('beforeend', html);
      for (const name of ['service', 'description', 'quantity', 'unit_price']) {
        field('items-' + index + '-' + name).value = name === 'unit_price' ? moneyFmt(item[name]) : item[name];
      }
      field('items-TOTAL_FORMS').value = index + 1;
    });
    preview();
  });
  for (const name of ['month', 'year']) field(name).addEventListener('change', () => {
    const month = Number(field('month').value), year = Number(field('year').value);
    if (month >= 1 && month <= 12 && year >= 2000 && year <= 2100) {
      const params = new URLSearchParams({month, year, room: field('room').value});
      window.location.assign(window.location.pathname + '?' + params.toString());
    }
  });
  document.getElementById('addLine').addEventListener('click', () => {
    const count = field('items-TOTAL_FORMS');
    const index = Number(count.value);
    if (index >= 200) return;
    const html = document.getElementById('emptyLine').innerHTML.replace(/__prefix__/g, String(index));
    document.getElementById('invoiceLines').insertAdjacentHTML('beforeend', html);
    count.value = index + 1;
    preview();
    field('items-' + index + '-description').focus();
  });
  form.addEventListener('input', preview);
  form.addEventListener('change', preview);
  preview();
})();
