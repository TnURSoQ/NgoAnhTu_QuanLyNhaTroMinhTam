(() => {
  const source = document.getElementById('reportChartData');
  if (!source) return;
  const data = JSON.parse(source.textContent);
  const money = value => `${new Intl.NumberFormat('vi-VN').format(value)} đ`;
  const compact = new Intl.NumberFormat('vi-VN', {notation: 'compact', maximumFractionDigits: 1});
  const percent = new Intl.NumberFormat('vi-VN', {maximumFractionDigits: 1});
  const colors = {cash: '#b9563a', bank: '#5d8776', rooms: ['#5d8776', '#93afc8', '#d5a253'],
    debt: ['#5d8776', '#bda15b', '#cf9259', '#c66f4c', '#b94e4e']};
  const tooltip = document.createElement('div');
  tooltip.className = 'report-chart-tooltip';
  tooltip.setAttribute('aria-hidden', 'true');
  tooltip.hidden = true;
  document.body.append(tooltip);
  let focusedTip = null;

  function element(tag, attrs = {}, text = '', parent = null, svg = false) {
    const node = svg ? document.createElementNS('http://www.w3.org/2000/svg', tag) : document.createElement(tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    if (text) node.textContent = text;
    parent?.append(node);
    return node;
  }
  const shape = (tag, attrs, parent, text = '') => element(tag, attrs, text, parent, true);

  function attachTip(node, text) {
    node.setAttribute('data-chart-tip', text);
    node.setAttribute('tabindex', '0');
    node.setAttribute('aria-label', text.replaceAll('\n', '. '));
    function show(event) {
      const rect = node.getBoundingClientRect();
      tooltip.textContent = text;
      tooltip.hidden = false;
      const x = event.clientX ?? rect.left + rect.width / 2;
      const y = event.clientY ?? rect.top;
      tooltip.style.left = `${Math.max(12, Math.min(x + 12, innerWidth - tooltip.offsetWidth - 12))}px`;
      tooltip.style.top = `${Math.max(12, Math.min(y - tooltip.offsetHeight - 12, innerHeight - tooltip.offsetHeight - 12))}px`;
    }
    ['pointerenter', 'pointermove', 'pointerdown'].forEach(name => node.addEventListener(name, show));
    node.addEventListener('focus', () => {
      focusedTip = () => show({});
      show({});
    });
    node.addEventListener('pointerleave', event => { if (event.pointerType !== 'touch') tooltip.hidden = true; });
    node.addEventListener('blur', () => { focusedTip = null; tooltip.hidden = true; });
  }
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') { focusedTip = null; tooltip.hidden = true; }
  });
  document.addEventListener('scroll', () => {
    if (focusedTip) focusedTip();
    else tooltip.hidden = true;
  }, true);
  document.addEventListener('pointerdown', event => {
    if (!event.target.closest('[data-chart-tip]')) tooltip.hidden = true;
  });

  function empty(container, message) {
    const box = element('div', {class: 'report-chart-empty'}, '', container);
    element('i', {class: 'bi bi-bar-chart', 'aria-hidden': 'true'}, '', box);
    element('p', {}, message, box);
  }

  function collections(container) {
    const series = data.collections;
    const totals = series.cash.map((value, index) => value + series.bank[index]);
    const invoices = series.invoice || totals.map(() => 0);
    const max = Math.max(...totals, ...invoices, 0);
    if (!max) return empty(container, series.daily ? 'Chưa có tiền thực thu hóa đơn trong kỳ này.' : 'Chưa có hóa đơn hoặc khoản thu trong kỳ này.');
    const width = Math.max(container.clientWidth, series.daily ? 740 : 540);
    const height = 270, left = 65, right = 20, top = 20, bottom = 40;
    const plotHeight = height - top - bottom;
    const roughStep = max / 4;
    const power = 10 ** Math.floor(Math.log10(roughStep));
    const step = [1, 2, 2.5, 5, 10].find(value => value * power >= roughStep) * power;
    const ticks = Math.ceil(max / step);
    const ceiling = step * ticks;
    const svg = shape('svg', {width, height, viewBox: `0 0 ${width} ${height}`, role: 'group',
      'aria-label': `Biểu đồ đường tiền thực thu${series.daily ? ' theo ngày' : ' và giá trị hóa đơn theo tháng'}`}, container);
    for (let tick = 0; tick <= ticks; tick++) {
      const y = height - bottom - tick * plotHeight / ticks;
      shape('line', {x1: left, x2: width - right, y1: y, y2: y, class: tick ? 'chart-grid' : 'chart-axis'}, svg);
      shape('text', {x: left - 12, y: y + 4, 'text-anchor': 'end'}, svg, compact.format(step * tick));
    }
    const stride = (width - left - right) / (totals.length - 1);
    const observed = series.observed_count || totals.length;
    const yFor = value => height - bottom - value / ceiling * plotHeight;
    const points = values => values.slice(0, observed).map((value, index) => `${left + index * stride},${yFor(value)}`).join(' ');
    shape('polygon', {points: `${left},${height - bottom} ${points(totals)} ${left + (observed - 1) * stride},${height - bottom}`, fill: '#426b5810'}, svg);
    if (!series.daily) shape('polyline', {points: points(invoices), fill: 'none', stroke: '#b9563a', 'stroke-width': 2, 'stroke-dasharray': '5 5', 'stroke-linejoin': 'round'}, svg);
    shape('polyline', {points: points(totals), fill: 'none', stroke: '#426b58', 'stroke-width': 2.5, 'stroke-linejoin': 'round'}, svg);
    totals.forEach((total, index) => {
      const x = left + index * stride;
      const group = shape('g', {}, svg);
      shape('rect', {x: x - stride / 2, y: top, width: stride, height: plotHeight, fill: 'transparent', class: 'chart-hit'}, group);
      if (index < observed) shape('circle', {cx: x, cy: yFor(total), r: 3, fill: '#426b58', stroke: 'white', 'stroke-width': 1.5}, group);
      attachTip(group, index >= observed ? `${series.labels[index]}\nChưa đến kỳ báo cáo` : `${series.labels[index]}\nTiền mặt: ${money(series.cash[index])}\nChuyển khoản: ${money(series.bank[index])}\nTổng tiền mới nhận: ${money(total)}${series.daily ? '' : `\nGiá trị hóa đơn: ${money(invoices[index])}`}`);
      if (!series.daily || index % 5 === 0 && index < totals.length - 3 || index === totals.length - 1) {
        const label = series.daily ? series.labels[index] : `T${index + 1}`;
        shape('text', {x, y: height - bottom + 24, 'text-anchor': 'middle'}, svg, label);
      }
    });
  }

  function debt(container) {
    const max = Math.max(...data.debt.map(row => row.value), 0);
    if (!max) return empty(container, 'Không có công nợ tại thời điểm hiện tại.');
    data.debt.forEach((row, index) => {
      const group = element('div', {class: 'report-debt-row'}, '', container);
      const label = element('div', {class: 'report-debt-label'}, '', group);
      element('span', {}, `${row.label} · ${row.count} hóa đơn`, label);
      element('strong', {}, money(row.value), label);
      const track = element('div', {class: 'report-debt-track', 'aria-hidden': 'true'}, '', group);
      element('div', {style: `width:${row.value / max * 100}%;background:${colors.debt[index]}`}, '', track);
      attachTip(group, `${row.label}\n${row.count} hóa đơn\nCòn phải thu: ${money(row.value)}`);
    });
  }

  function rooms(container) {
    const total = data.rooms.reduce((sum, row) => sum + row.value, 0);
    if (!total) return empty(container, 'Chưa có phòng để thống kê tình trạng.');
    const svg = shape('svg', {width: 220, height: 220, viewBox: '0 0 220 220', role: 'group',
      'aria-label': `Tình trạng hiện tại của ${total} phòng`}, container);
    shape('circle', {cx: 110, cy: 110, r: 76, fill: 'none', stroke: '#edf0ec', 'stroke-width': 28}, svg);
    let offset = 0;
    const legend = element('ul', {class: 'report-room-legend', 'aria-label': 'Số phòng theo tình trạng'}, '', container);
    data.rooms.forEach((row, index) => {
      const ratio = row.value / total * 100;
      if (row.value) {
        const segment = shape('circle', {cx: 110, cy: 110, r: 76, fill: 'none', stroke: colors.rooms[index],
          'stroke-width': 28, pathLength: 100, 'stroke-dasharray': `${ratio} ${100 - ratio}`,
          'stroke-dashoffset': -offset, transform: 'rotate(-90 110 110)'}, svg);
        attachTip(segment, `${row.label}\n${row.value} phòng · ${percent.format(ratio)}%`);
      }
      offset += ratio;
      const item = element('li', {}, '', legend);
      element('i', {style: `--chart-color:${colors.rooms[index]}`, 'aria-hidden': 'true'}, '', item);
      element('span', {}, row.label, item);
      const value = element('strong', {}, `${row.value} phòng `, item);
      element('small', {}, `(${percent.format(ratio)}%)`, value);
    });
    shape('text', {x: 110, y: 112, 'text-anchor': 'middle', class: 'chart-donut-total'}, svg, `${percent.format(data.rooms[0].value / total * 100)}%`);
    shape('text', {x: 110, y: 136, 'text-anchor': 'middle', class: 'chart-donut-unit'}, svg, 'đang thuê');
  }

  const renderers = {collections, debt, rooms};
  const widths = new WeakMap();
  function draw(container) {
    const width = Math.round(container.clientWidth);
    if (!width || widths.get(container) === width) return;
    widths.set(container, width);
    container.replaceChildren();
    renderers[container.dataset.reportChart](container);
  }
  const charts = [...document.querySelectorAll('[data-report-chart]')];
  charts.forEach(draw);
  if (window.ResizeObserver) {
    const observer = new ResizeObserver(entries => entries.forEach(entry => draw(entry.target)));
    charts.forEach(chart => observer.observe(chart));
  }
  window.addEventListener('resize', () => charts.forEach(draw));
  document.addEventListener('shown.bs.tab', () => charts.forEach(draw));
  document.querySelectorAll('.report-debt-details').forEach(details => {
    details.addEventListener('toggle', () => charts.forEach(draw));
  });

  const search = document.getElementById('reportInvoiceSearch');
  const status = document.getElementById('reportInvoiceStatus');
  const rows = [...document.querySelectorAll('[data-report-invoice]')];
  const pageSize = document.getElementById('reportInvoicePageSize');
  const previousPage = document.getElementById('reportInvoicePrevious');
  const nextPage = document.getElementById('reportInvoiceNext');
  let currentPage = 1;
  const normalize = text => text.normalize('NFD').replace(/\p{Diacritic}/gu, '').replace(/[đĐ]/g, 'd').toLowerCase();
  function filterInvoices(resetPage = false) {
    if (resetPage) currentPage = 1;
    const query = normalize(search.value.trim());
    const visible = rows.filter(row => normalize(row.dataset.search).includes(query) && (!status.value || status.value === row.dataset.state));
    const size = Number(pageSize.value);
    const pages = Math.max(1, Math.ceil(visible.length / size));
    currentPage = Math.min(currentPage, pages);
    const start = (currentPage - 1) * size;
    rows.forEach(row => { row.hidden = true; });
    visible.slice(start, start + size).forEach(row => { row.hidden = false; });
    document.querySelector('[data-invoice-count]').textContent = `${visible.length}/${rows.length} hóa đơn`;
    document.querySelector('[data-invoice-no-results]').hidden = !rows.length || visible.length > 0;
    document.querySelectorAll('[data-invoice-total]').forEach(cell => {
      cell.textContent = new Intl.NumberFormat('vi-VN').format(visible.reduce((sum, row) => sum + Number(row.dataset[cell.dataset.invoiceTotal]), 0));
    });
    document.querySelector('[data-invoice-pagination]').hidden = !rows.length;
    document.querySelector('[data-invoice-range]').textContent = visible.length ? `${start + 1}–${Math.min(start + size, visible.length)} / ${visible.length} hóa đơn` : '0 hóa đơn';
    document.querySelector('[data-invoice-page]').textContent = `${currentPage} / ${pages}`;
    previousPage.disabled = currentPage === 1;
    nextPage.disabled = currentPage === pages;
  }
  search?.addEventListener('input', () => filterInvoices(true));
  status?.addEventListener('change', () => filterInvoices(true));
  pageSize?.addEventListener('change', () => filterInvoices(true));
  previousPage?.addEventListener('click', () => { currentPage -= 1; filterInvoices(); });
  nextPage?.addEventListener('click', () => { currentPage += 1; filterInvoices(); });
  if (search && pageSize) filterInvoices();
  document.querySelector('[data-open-debt]')?.addEventListener('click', event => {
    event.preventDefault();
    const details = document.getElementById('reportCurrentDebt');
    details.open = true;
    if (window.bootstrap?.Tab) bootstrap.Tab.getOrCreateInstance(document.getElementById('invoices-tab')).show();
    setTimeout(() => details.scrollIntoView({block: 'start', behavior: 'auto'}), 200);
  });
})();
