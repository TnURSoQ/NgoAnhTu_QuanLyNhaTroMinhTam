(() => {
  const toggle = document.getElementById('notificationToggle');
  const panel = document.getElementById('notificationPanel');
  const content = document.getElementById('notificationPanelBody');
  const badge = document.getElementById('notificationUnreadCount');
  if (!toggle || !panel || !content) return;

  let controller;
  let currentUrl = toggle.dataset.notificationsUrl;
  let countPending = false;
  let countVersion = 0;
  const syncKey = `notification-read-${toggle.dataset.userId}`;

  const updateCount = (value) => {
    if (value === null || value === undefined) return;
    const count = Number(value);
    if (!Number.isInteger(count) || count < 0) return;
    countVersion += 1;
    if (badge) {
      badge.hidden = count === 0;
      badge.textContent = count > 99 ? '99+' : String(count);
    }
    toggle.setAttribute('aria-label', count ? `Thông báo, ${count} chưa đọc` : 'Thông báo');
  };

  const refreshCount = async () => {
    if (countPending || document.hidden || !toggle.dataset.notificationCountUrl) return;
    countPending = true;
    const version = countVersion;
    try {
      const response = await fetch(toggle.dataset.notificationCountUrl, { credentials: 'same-origin', cache: 'no-store' });
      if (response.ok && !response.redirected) {
        const result = await response.json();
        if (countVersion === version) updateCount(result.unread_count);
      }
    } catch (_) {
      // Giữ số đã nhận gần nhất nếu kết nối tạm thời bị gián đoạn.
    } finally {
      countPending = false;
    }
  };

  const readNotification = async (card, navigate) => {
    if (card.dataset.reading === 'true') return;
    card.dataset.reading = 'true';
    card.setAttribute('aria-busy', 'true');
    content.querySelector('.notification-action-error')?.remove();
    try {
      const response = await fetch(toggle.dataset.notificationReadUrl, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
        headers: { 'X-CSRFToken': toggle.dataset.csrfToken },
        body: new URLSearchParams({ token: card.dataset.readToken }),
      });
      if (!response.ok || response.redirected) throw new Error('Unable to mark notification read');
      const result = await response.json();
      updateCount(result.unread_count);
      if (!result.is_unread) {
        card.classList.remove('is-unread');
        card.dataset.unread = 'false';
        card.querySelector('[data-unread-label]')?.remove();
      }
      try { localStorage.setItem(syncKey, String(Date.now())); } catch (_) { /* Đồng bộ sau khi mở lại trang. */ }
      if (navigate) {
        const target = new URL(result.url, window.location.href);
        if (target.origin !== window.location.origin) throw new Error('Invalid notification target');
        window.location.assign(target.href);
      }
    } catch (_) {
      const message = document.createElement('p');
      message.className = 'notification-action-error';
      message.setAttribute('role', 'alert');
      message.textContent = 'Chưa mở được thông báo. Vui lòng thử lại.';
      content.prepend(message);
    } finally {
      delete card.dataset.reading;
      card.removeAttribute('aria-busy');
    }
  };

  const showMessage = (message, retry = false) => {
    const container = document.createElement('div');
    container.className = 'notification-empty';
    const text = document.createElement('p');
    text.className = 'mb-0';
    text.textContent = message;
    container.append(text);
    if (retry) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-sm btn-outline-brand mt-3';
      button.dataset.notificationRetry = '';
      button.textContent = 'Thử lại';
      container.append(button);
    }
    content.replaceChildren(container);
  };

  const load = async (url) => {
    if (controller) controller.abort();
    const pending = new AbortController();
    controller = pending;
    currentUrl = url;
    content.setAttribute('aria-busy', 'true');
    showMessage('Đang tải thông báo…');
    try {
      const target = new URL(url, window.location.href);
      if (target.origin !== window.location.origin) throw new Error('Invalid notification URL');
      const response = await fetch(target, {
        credentials: 'same-origin', cache: 'no-store', signal: pending.signal,
      });
      if (!response.ok || response.redirected) throw new Error('Unable to load notifications');
      const html = await response.text();
      if (pending.signal.aborted) return;
      content.innerHTML = html;
      updateCount(response.headers.get('X-Notification-Unread-Count'));
      content.scrollTop = 0;
      window.bootstrap.Dropdown.getInstance(toggle)?.update();
    } catch (error) {
      if (pending.signal.aborted) return;
      showMessage('Chưa tải được thông báo. Vui lòng thử lại.', true);
    } finally {
      if (controller === pending) content.setAttribute('aria-busy', 'false');
    }
  };

  toggle.addEventListener('show.bs.dropdown', () => load(toggle.dataset.notificationsUrl));
  toggle.addEventListener('hidden.bs.dropdown', () => {
    if (controller) controller.abort();
    content.setAttribute('aria-busy', 'false');
  });
  panel.addEventListener('click', (event) => {
    const page = event.target.closest('[data-notification-page]');
    if (page) {
      event.preventDefault();
      load(page.href);
    } else if (event.target.closest('[data-notification-retry]')) {
      load(currentUrl);
    } else {
      const card = event.target.closest('.notification-item[data-read-token]');
      if (!card || card.dataset.unread !== 'true') return;
      const newTab = event.ctrlKey || event.metaKey || event.shiftKey || event.altKey;
      if (!newTab) event.preventDefault();
      readNotification(card, !newTab);
    }
  });
  panel.addEventListener('auxclick', (event) => {
    const card = event.target.closest('.notification-item[data-read-token]');
    if (event.button === 1 && card?.dataset.unread === 'true') readNotification(card, false);
  });
  window.addEventListener('pageshow', (event) => {
    refreshCount();
    if (event.persisted && toggle.getAttribute('aria-expanded') === 'true') load(currentUrl);
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshCount(); });
  window.addEventListener('storage', (event) => {
    if (event.key === syncKey) {
      refreshCount();
      if (toggle.getAttribute('aria-expanded') === 'true') load(currentUrl);
    }
  });
  window.setInterval(refreshCount, 30000);
})();
