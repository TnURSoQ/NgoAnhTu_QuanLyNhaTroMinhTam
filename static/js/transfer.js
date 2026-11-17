(() => {
  'use strict';
  function fallbackCopy(text) {
    const input = document.createElement('textarea');
    input.value = text;
    input.style.position = 'fixed';
    input.style.opacity = '0';
    document.body.appendChild(input);
    input.focus();
    input.select();
    try {
      if (!document.execCommand('copy')) throw new Error('copy failed');
    } finally {
      input.remove();
    }
  }
  document.querySelectorAll('[data-copy-text]').forEach(button => {
    button.addEventListener('click', async () => {
      const feedback = button.closest('section').querySelector('.copy-feedback');
      try {
        const text = button.dataset.copyText;
        if (navigator.clipboard && window.isSecureContext) {
          try { await navigator.clipboard.writeText(text); }
          catch { fallbackCopy(text); }
        } else fallbackCopy(text);
        feedback.classList.remove('text-danger');
        feedback.classList.add('text-success');
        feedback.textContent = 'Đã sao chép.';
      } catch {
        feedback.classList.remove('text-success');
        feedback.classList.add('text-danger');
        feedback.textContent = 'Chưa sao chép được. Vui lòng chọn và sao chép nội dung trực tiếp.';
      } finally {
        button.focus();
      }
    });
  });
})();
