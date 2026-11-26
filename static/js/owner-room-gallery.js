(() => {
  const gallery = document.querySelector('[data-owner-room-gallery]');
  const main = gallery?.querySelector('[data-photo-main]');
  if (!main) return;

  const open = gallery.querySelector('[data-photo-open]');
  const full = gallery.querySelector('[data-photo-full]');
  const modal = gallery.querySelector('.modal');
  const thumbnails = [...gallery.querySelectorAll('[data-photo-thumb]')];
  const photos = thumbnails.length ? thumbnails.map(thumb => ({
    url: thumb.href,
    alt: thumb.querySelector('img').alt,
    caption: thumb.dataset.caption,
  })) : [{url: open.href, alt: main.alt, caption: gallery.querySelector('[data-photo-caption]').textContent}];
  let current = 0;

  function show(index) {
    current = (index + photos.length) % photos.length;
    const photo = photos[current];
    main.src = photo.url;
    main.alt = photo.alt;
    full.src = photo.url;
    full.alt = photo.alt;
    open.href = photo.url;
    gallery.querySelectorAll('[data-photo-count]').forEach(count => {
      count.textContent = `${current + 1} / ${photos.length}`;
    });
    gallery.querySelectorAll('[data-photo-caption]').forEach(caption => {
      caption.textContent = photo.caption;
      caption.title = photo.caption;
      caption.hidden = !photo.caption;
    });
    thumbnails.forEach((thumb, index) => {
      if (index === current) thumb.setAttribute('aria-current', 'true');
      else thumb.removeAttribute('aria-current');
    });
    // Only scroll the thumbnail strip; keep the page at the user's position.
    const selected = thumbnails[current];
    if (selected) {
      const strip = selected.parentElement;
      const left = selected.offsetLeft;
      if (left < strip.scrollLeft) strip.scrollLeft = left;
      else if (left + selected.offsetWidth > strip.scrollLeft + strip.clientWidth) {
        strip.scrollLeft = left + selected.offsetWidth - strip.clientWidth;
      }
    }
  }

  thumbnails.forEach((thumb, index) => thumb.addEventListener('click', event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    show(index);
  }));
  gallery.querySelectorAll('[data-photo-prev]').forEach(button => {
    button.addEventListener('click', () => show(current - 1));
  });
  gallery.querySelectorAll('[data-photo-next]').forEach(button => {
    button.addEventListener('click', () => show(current + 1));
  });
  open.addEventListener('click', event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || !window.bootstrap?.Modal) return;
    event.preventDefault();
    bootstrap.Modal.getOrCreateInstance(modal).show();
  });
  modal.addEventListener('hidden.bs.modal', () => open.focus({preventScroll: true}));
  gallery.addEventListener('keydown', event => {
    if (photos.length < 2 || !['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    show(current + (event.key === 'ArrowRight' ? 1 : -1));
  });
})();
