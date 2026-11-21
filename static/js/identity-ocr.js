(() => {
  let libraryPromise;
  const loadLibrary = (path) => {
    if (window.Tesseract) return Promise.resolve(window.Tesseract);
    if (!libraryPromise) {
      libraryPromise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = new URL(path, location.href).href;
        script.onload = () => {
          if (window.Tesseract) resolve(window.Tesseract);
          else { libraryPromise = null; script.remove(); reject(new Error('OCR unavailable')); }
        };
        script.onerror = () => { libraryPromise = null; script.remove(); reject(new Error('OCR unavailable')); };
        document.head.append(script);
      });
    }
    return libraryPromise;
  };

  document.querySelectorAll('.identity-scan').forEach(widget => {
    const form = widget.closest('form');
    if (!form || !window.IdentityCardParser) return;
    const field = name => form.elements.namedItem(name);
    const readButton = widget.querySelector('[data-identity-read]');
    const clearButton = widget.querySelector('[data-identity-clear]');
    const applyButton = widget.querySelector('[data-identity-apply]');
    const status = widget.querySelector('[data-identity-status]');
    const results = widget.querySelector('[data-identity-results]');
    const comparison = widget.querySelector('[data-identity-comparison]');
    const comparisonText = widget.querySelector('[data-identity-comparison-text]');
    const recognitionInput = field('identity_recognition');
    const labels = {id_card_number:'Số CCCD/CMND', full_name:'Họ và tên', date_of_birth:'Ngày sinh', hometown:'Quê quán'};
    let recognized = {}, autoFilled = {}, urls = [], busy = false, activeWorker;

    const upload = side => field(`identity_${side}`)?.files?.[0] || field(`identity_${side}_camera`)?.files?.[0];
    const message = (text, error = false) => { status.textContent = text; status.classList.toggle('text-danger', error); };
    const compare = () => {
      const entered = field('id_card_number').value.trim();
      const baseline = recognized.id_card_number || (!upload('front') ? widget.dataset.existingNumber : '');
      const changed = baseline && entered && baseline !== entered;
      comparison.hidden = !changed && !comparison.dataset.serverError;
      if (changed) {
        comparisonText.textContent = field('id_card_number').disabled
          ? `Số đọc được ${baseline} khác số đang lưu ${entered}. Số trong hồ sơ này đang khóa; hãy kiểm tra lại thông tin cá nhân trước khi lưu ảnh.`
          : `Số đọc được hoặc đã lưu là ${baseline}, nhưng hồ sơ đang nhập ${entered}. Hãy đối chiếu trên ảnh và kiểm tra lại.`;
      }
    };
    const revoke = () => { urls.forEach(url => URL.revokeObjectURL(url)); urls = []; };
    const previewImages = () => {
      revoke();
      for (const side of ['front','back']) {
        const container = widget.querySelector(`[data-identity-preview="${side}"]`);
        container.replaceChildren();
        const file = upload(side);
        if (!file) continue;
        const image = document.createElement('img'), url = URL.createObjectURL(file);
        urls.push(url); image.src = url; image.alt = side === 'front' ? 'Ảnh mặt trước đã chọn' : 'Ảnh mặt sau đã chọn';
        container.append(image);
      }
    };
    const resetRecognition = () => {
      for (const [name, value] of Object.entries(autoFilled)) {
        if (field(name)?.value === value && !field(name).disabled) field(name).value = '';
      }
      autoFilled = {}; recognized = {}; recognitionInput.value = '';
      comparison.dataset.serverError = '';
      results.replaceChildren(); results.hidden = true; applyButton.hidden = true;
      field('confirm_identity_correction').checked = false;
      compare();
    };
    const apply = overwrite => {
      let count = 0;
      for (const name of Object.keys(labels)) {
        const input = field(name), value = recognized[name];
        if (!value || !input || input.disabled || (!overwrite && input.value.trim())) continue;
        input.value = value; autoFilled[name] = value; count++;
        input.dispatchEvent(new Event('input', {bubbles:true}));
      }
      compare();
      return count;
    };
    const showResults = () => {
      results.replaceChildren();
      for (const name of Object.keys(labels)) {
        if (!recognized[name]) continue;
        const row = document.createElement('div'), label = document.createElement('span'), value = document.createElement('strong');
        row.className = 'identity-result-row'; label.textContent = labels[name];
        value.textContent = name === 'date_of_birth' ? recognized[name].split('-').reverse().join('/') : recognized[name];
        row.append(label, value); results.append(row);
      }
      results.hidden = !results.childElementCount;
      applyButton.hidden = !results.childElementCount;
    };
    const setBusy = value => {
      busy = value;
      for (const input of widget.querySelectorAll('input[type=file],button')) input.disabled = value;
      widget.setAttribute('aria-busy', String(value));
    };
    const canvasFor = async file => {
      if (file.size > 5 * 1024 * 1024) throw new Error('Mỗi ảnh tối đa 5 MB.');
      const image = await createImageBitmap(file);
      try {
        if (image.width * image.height > 20000000) throw new Error('Ảnh quá lớn. Hãy giảm kích thước trước khi đọc.');
        const scale = Math.min(2400 / image.width, 1800 / image.height, Math.max(1, 1400 / image.width));
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(image.width * scale); canvas.height = Math.round(image.height * scale);
        const context = canvas.getContext('2d');
        context.fillStyle = '#fff'; context.fillRect(0,0,canvas.width,canvas.height);
        context.drawImage(image,0,0,canvas.width,canvas.height);
        return canvas;
      } finally { image.close(); }
    };

    widget.querySelectorAll('[data-identity-camera]').forEach(button => {
      button.addEventListener('click', () => document.getElementById(button.dataset.identityCamera).click());
    });
    for (const side of ['front','back']) {
      for (const type of ['', '_camera']) {
        field(`identity_${side}${type}`).addEventListener('change', () => {
          field(`identity_${side}${type ? '' : '_camera'}`).value = '';
          resetRecognition(); previewImages(); message('Ảnh mới đã chọn. Bấm đọc CCCD để điền thông tin.');
        });
      }
    }
    clearButton.addEventListener('click', () => {
      for (const side of ['front','back']) for (const type of ['', '_camera']) field(`identity_${side}${type}`).value = '';
      resetRecognition(); previewImages(); message('Đã bỏ ảnh mới.');
    });
    applyButton.addEventListener('click', () => {
      const count = apply(true); message(`Đã điền ${count} mục từ ảnh. Hãy kiểm tra lại trước khi lưu.`);
    });
    field('id_card_number').addEventListener('input', compare);
    form.addEventListener('submit', event => { if (busy) { event.preventDefault(); message('Đang đọc ảnh, vui lòng chờ hoàn tất.'); } });
    readButton.addEventListener('click', async () => {
      if (busy) return;
      const front = upload('front'), back = upload('back');
      if (!front) { message('Hãy chọn hoặc chụp ảnh mặt trước CCCD trước.', true); return; }
      setBusy(true); message('Đang chuẩn bị bộ đọc chữ tiếng Việt…');
      let worker, finished = false, timer;
      try {
        const task = (async () => {
          const Tesseract = await loadLibrary(widget.dataset.libraryPath);
          worker = await Tesseract.createWorker('vie', 1, {
            workerPath: new URL(widget.dataset.workerPath,location.href).href,
            corePath: new URL(widget.dataset.corePath,location.href).href,
            langPath: new URL(widget.dataset.langPath,location.href).href,
            workerBlobURL: false, gzip: false,
            logger: entry => { if (!finished && entry.status === 'recognizing text') message(`Đang đọc ảnh CCCD… ${Math.round((entry.progress || 0)*100)}%`); },
          });
          if (finished) { await worker.terminate(); throw new Error('Reading cancelled'); }
          activeWorker = worker;
          await worker.setParameters({tessedit_pageseg_mode:Tesseract.PSM.AUTO,user_defined_dpi:'300',preserve_interword_spaces:'1'});
          const first = await worker.recognize(await canvasFor(front));
          const fields = window.IdentityCardParser.parse(first.data.text);
          if (back) {
            const last = await worker.recognize(await canvasFor(back));
            const other = window.IdentityCardParser.parse(last.data.text);
            for (const name of Object.keys(labels)) if (!fields[name] && other[name]) fields[name] = other[name];
            if (other.id_card_number) fields.back_id_card_number = other.id_card_number;
          }
          return fields;
        })();
        const timeout = new Promise((_,reject) => { timer=setTimeout(()=>reject(new Error('Hết thời gian đọc ảnh. Hãy chọn ảnh rõ hơn hoặc nhập thủ công.')),60000); });
        recognized = await Promise.race([task,timeout]);
        recognitionInput.value = JSON.stringify(recognized);
        showResults();
        const count = apply(false);
        const keys = Object.keys(labels).filter(name=>recognized[name]);
        if (!keys.length) message('Chưa đọc được thông tin chắc chắn. Bạn có thể chọn ảnh rõ hơn hoặc nhập thủ công.', true);
        else message(`Đã đọc ${keys.length} mục và điền ${count} ô đang trống. Hãy kiểm tra thông tin với ảnh trước khi gửi.`);
        if (recognized.back_id_card_number?.length === 12 && recognized.id_card_number?.length === 12 && recognized.back_id_card_number !== recognized.id_card_number) {
          message('Hai mặt ảnh đọc được số CCCD khác nhau. Hãy kiểm tra và chọn đúng hai mặt của một giấy tờ.', true);
        }
      } catch (error) {
        message(error.message?.includes('ảnh') ? error.message : 'Chưa đọc được ảnh. Bạn có thể thử ảnh rõ hơn hoặc nhập thông tin thủ công.', true);
      } finally {
        finished = true; clearTimeout(timer); setBusy(false);
        if (worker) { try { await worker.terminate(); } catch (_) { /* Worker was already stopped. */ } }
        activeWorker = null;
      }
    });
    window.addEventListener('pagehide', () => { revoke(); activeWorker?.terminate(); });
    compare();
  });
})();
