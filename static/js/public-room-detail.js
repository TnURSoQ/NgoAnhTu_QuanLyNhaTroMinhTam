(() => {
  const gallery = document.querySelector('[data-room-gallery]');
  if (gallery) {
    const slides = [...gallery.querySelectorAll('.carousel-item')];
    const count = document.querySelector('[data-gallery-count]');
    const caption = document.querySelector('[data-gallery-caption]');
    if (slides.length > 1) bootstrap.Carousel.getOrCreateInstance(gallery, {interval: false, ride: false, wrap: true, touch: true});
    gallery.addEventListener('slid.bs.carousel', event => {
      if (count) count.textContent = `${event.to + 1} / ${slides.length}`;
      if (caption) {
        caption.textContent = slides[event.to].dataset.caption || '';
        caption.hidden = !caption.textContent;
      }
    });
  }
  const modal = document.getElementById('roomBookingModal');
  if (!modal) return;
  modal.addEventListener('shown.bs.modal', () => {
    const input = modal.querySelector('.is-invalid') || modal.querySelector('[name=visitor_name]');
    input?.focus({preventScroll: true});
    if (input?.classList.contains('is-invalid')) {
      const body = modal.querySelector('.modal-body');
      const bounds = body.getBoundingClientRect(), target = input.getBoundingClientRect();
      if (target.top < bounds.top || target.bottom > bounds.bottom) body.scrollTop += target.top - bounds.top - 24;
    }
  });
  if (modal.dataset.openOnLoad === 'true') bootstrap.Modal.getOrCreateInstance(modal).show();
})();
