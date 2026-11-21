(() => {
  const audience = document.getElementById('id_audience');
  const rooms = document.getElementById('announcementRooms');
  if (!audience || !rooms) return;
  const update = () => { rooms.hidden = audience.value !== 'rooms'; };
  audience.addEventListener('change', update);
  update();
})();
