(function () {
  'use strict';
  const modal = document.getElementById('loginModal');
  const form = document.getElementById('modalLoginForm');
  if (!modal || !form) return;

  const errorBox = form.querySelector('.login-modal-errors');
  const submit = form.querySelector('[type="submit"]');
  const submitLabel = submit.querySelector('span');
  const password = form.elements.password;
  const toggle = form.querySelector('.modal-password-toggle');

  function clearErrors() {
    errorBox.replaceChildren();
    errorBox.classList.add('d-none');
    form.querySelectorAll('[data-login-error]').forEach(node => node.remove());
    form.querySelectorAll('.is-invalid').forEach(node => {
      node.classList.remove('is-invalid');
      node.removeAttribute('aria-invalid');
      node.removeAttribute('aria-describedby');
    });
  }

  function showErrors(errors) {
    const globalMessages = [];
    Object.entries(errors).forEach(([name, entries]) => {
      const input = form.elements.namedItem(name);
      const wrapper = input && input.closest('[data-login-field]');
      if (wrapper) {
        input.classList.add('is-invalid');
        input.setAttribute('aria-invalid', 'true');
        const feedback = document.createElement('div');
        feedback.className = 'invalid-feedback d-block';
        feedback.id = input.id + '-error';
        feedback.dataset.loginError = '';
        feedback.textContent = entries.map(entry => entry.message).join(' ');
        input.setAttribute('aria-describedby', feedback.id);
        wrapper.appendChild(feedback);
      } else {
        globalMessages.push(...entries.map(entry => entry.message));
      }
    });
    if (globalMessages.length) {
      errorBox.textContent = globalMessages.join(' ');
      errorBox.classList.remove('d-none');
      errorBox.focus();
    } else {
      form.querySelector('.is-invalid')?.focus();
    }
  }

  function hidePassword() {
    password.type = 'password';
    toggle.setAttribute('aria-pressed', 'false');
    toggle.setAttribute('aria-label', 'Hiện mật khẩu');
    toggle.querySelector('i').className = 'bi bi-eye';
  }

  toggle.addEventListener('click', function () {
    const visible = password.type === 'password';
    password.type = visible ? 'text' : 'password';
    toggle.setAttribute('aria-pressed', String(visible));
    toggle.setAttribute('aria-label', visible ? 'Ẩn mật khẩu' : 'Hiện mật khẩu');
    toggle.querySelector('i').className = visible ? 'bi bi-eye-slash' : 'bi bi-eye';
  });

  modal.addEventListener('shown.bs.modal', function () {
    form.elements.next.value = window.location.pathname + window.location.search + window.location.hash;
    form.elements.username.focus();
  });
  modal.addEventListener('hidden.bs.modal', function () {
    password.value = '';
    hidePassword();
    clearErrors();
  });

  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    if (submit.disabled) return;
    clearErrors();
    submit.disabled = true;
    form.setAttribute('aria-busy', 'true');
    submitLabel.textContent = 'Đang đăng nhập…';
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        credentials: 'same-origin',
        headers: {Accept: 'application/json'}
      });
      // Một tab khác có thể đã đăng nhập trong lúc cửa sổ này còn mở.
      if (response.redirected) {
        window.location.assign(response.url);
        return;
      }
      const data = await response.json();
      if (response.ok && data.redirect_url) {
        window.location.assign(data.redirect_url);
      } else if (data.errors) {
        showErrors(data.errors);
      } else {
        throw new Error('Unexpected login response');
      }
    } catch (_) {
      showErrors({__all__: [{message: 'Chưa thể đăng nhập. Vui lòng kiểm tra kết nối và thử lại.'}]});
    } finally {
      submit.disabled = false;
      form.removeAttribute('aria-busy');
      submitLabel.textContent = 'Đăng nhập';
    }
  });
})();
