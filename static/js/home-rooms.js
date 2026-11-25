(() => {
  document.querySelectorAll('[data-room-showcase]').forEach((showcase) => {
    const track = showcase.querySelector('.room-showcase-track');
    const slides = [...track.children];
    const navigation = showcase.querySelector('.room-showcase-nav');
    const previous = navigation.querySelector('[data-room-previous]');
    const next = navigation.querySelector('[data-room-next]');
    const range = navigation.querySelector('.room-showcase-range');
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0;

    const metrics = () => {
      const gap = parseFloat(getComputedStyle(track).columnGap) || 0;
      const step = slides[0].getBoundingClientRect().width + gap;
      const visible = Math.max(1, Math.round((track.clientWidth + gap) / step));
      const last = Math.max(0, slides.length - visible);
      const index = Math.min(last, Math.max(0, Math.round(track.scrollLeft / step)));
      return { step, visible, last, index };
    };

    const update = () => {
      const { visible, index } = metrics();
      const overflowing = track.scrollWidth > track.clientWidth + 1;
      navigation.hidden = !overflowing;
      track.tabIndex = overflowing ? 0 : -1;
      previous.disabled = track.scrollLeft <= 1;
      next.disabled = track.scrollLeft >= track.scrollWidth - track.clientWidth - 1;
      const label = `${index + 1}–${Math.min(slides.length, index + visible)} / ${slides.length} phòng`;
      if (range.textContent !== label) range.textContent = label;
    };

    const scheduleUpdate = () => {
      if (!frame) frame = requestAnimationFrame(() => { frame = 0; update(); });
    };

    const move = (direction) => {
      const { step, index, last } = metrics();
      const target = Math.max(0, Math.min(last, index + direction));
      track.scrollTo({ left: target * step, behavior: reducedMotion.matches ? 'auto' : 'smooth' });
    };

    previous.addEventListener('click', () => move(-1));
    next.addEventListener('click', () => move(1));
    track.addEventListener('scroll', scheduleUpdate, { passive: true });
    track.addEventListener('keydown', (event) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault();
        move(event.key === 'ArrowLeft' ? -1 : 1);
      } else if (event.key === 'Home' || event.key === 'End') {
        event.preventDefault();
        track.scrollTo({ left: event.key === 'Home' ? 0 : track.scrollWidth,
                         behavior: reducedMotion.matches ? 'auto' : 'smooth' });
      }
    });
    if ('ResizeObserver' in window) new ResizeObserver(scheduleUpdate).observe(track);
    else window.addEventListener('resize', scheduleUpdate);
    showcase.classList.add('is-enhanced');
    update();
  });
})();
