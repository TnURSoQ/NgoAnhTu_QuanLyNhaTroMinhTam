(() => {
  'use strict';
  const form = document.getElementById('invoiceForm');
  const field = name => form.elements.namedItem(name);
  const defaults = JSON.parse(document.getElementById('roomDefaults').textContent);
  const rates = {electric: Number(JSON.parse(document.getElementById('electricRate').textContent)),
                 water: Number(JSON.parse(document.getElementById('waterRate').textContent))};
  const fmt = (value, digits = 2) => Number(value).toLocaleString('vi-VN', {maximumFractionDigits: digits});
  const moneyFmt = value => Math.trunc(Number(value)).toLocaleString('vi-VN', {maximumFractionDigits: 0});
  const money = value => Math.trunc(Number(value.trim().replace(/\s|\./g, '').replace(',', '.'))) || 0;
  const decimal = value => value === '' ? NaN : Number(value.replace(',', '.'));
  const electric = value => {
    let text = value.trim();
    if (text.includes(',')) {
      if (!/^(?:\d+|\d{1,3}(?:\.\d{3})+),\d$/.test(text)) return NaN;
      text = text.replaceAll('.', '').replace(',', '.');
    } else if (/^\d{1,3}(?:\.\d{3})+$/.test(text)) text = text.replaceAll('.', '');
    if (!/^\d+(?:\.\d)?$/.test(text)) return NaN;
    const number = Number(text);
    return number <= 99999.9 ? number : NaN;
  };
  function preview() {
    let total = money(field('room_fee').value), complete = true, invalid = false;
    for (const utility of ['electric', 'water']) {
      if (utility === 'water' && form.dataset.waterMethod === 'per_person') {
        const people = Number(field('water_people_count').value);
        const target = document.getElementById('waterPreview');
        const valid = Number.isInteger(people) && people > 0;
        target.classList.toggle('text-danger', !valid);
        if (valid) {
          const amount = people * rates.water;
          total += amount;
          target.textContent = people + ' người × ' + moneyFmt(rates.water) + ' đ = ' + moneyFmt(amount) + ' đ/tháng';
        } else { complete = false; target.textContent = 'Nhập số người tính tiền nước từ 1 trở lên.'; }
        continue;
      }
      const parse = utility === 'electric' ? electric : decimal;
      const oldValue = parse(field('old_' + utility).value);
      const newValue = parse(field('new_' + utility).value);
      const usage = newValue - oldValue;
      const target = document.getElementById(utility + 'Preview');
      const invalidElectric = utility === 'electric' && ['old_electric', 'new_electric'].some(name => field(name).value.trim() && !Number.isFinite(electric(field(name).value)));
      if (invalidElectric || usage < 0) invalid = true;
      if (!Number.isFinite(usage)) complete = false;
      target.classList.toggle('text-danger', invalidElectric || Number.isFinite(usage) && usage < 0);
      if (invalidElectric) target.textContent = 'Điện: 0–99.999,9 kWh, tối đa 1 số lẻ. Ví dụ: 1.611,1.';
      else if (!Number.isFinite(usage)) target.textContent = 'Nhập đủ chỉ số để tính tiền.';
      else if (usage < 0) target.textContent = 'Chỉ số mới không được nhỏ hơn chỉ số cũ.';
      else {
        const scale = utility === 'electric' ? 10 : 100;
        const usageUnits = Math.round(newValue * scale) - Math.round(oldValue * scale);
        const amount = Math.floor(usageUnits * rates[utility] / scale);
        total += amount;
        target.textContent = fmt(usageUnits / scale, utility === 'electric' ? 1 : 2) + (utility === 'electric' ? ' kWh' : ' m³') + ' x ' +
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
    document.getElementById('totalPreview').textContent = invalid ? 'Kiểm tra chỉ số điện nước' : complete ? moneyFmt(total) + ' đ' : 'Chờ đủ thông tin tính tiền';
  }
  field('room').addEventListener('change', () => {
    const data = defaults[field('room').value];
    field('room_fee').value = data ? moneyFmt(data.price) : '';
    for (const utility of ['electric', 'water']) {
      if (utility === 'water' && form.dataset.waterMethod === 'per_person') {
        field('water_people_count').value = data && data.water_people_count ? data.water_people_count : '';
        continue;
      }
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
