(() => {
  const inputs = ['id_photos', 'id_camera_photo'].map(id => document.getElementById(id));
  const previews = document.getElementById('maintenancePhotoPreviews');
  const count = document.getElementById('maintenancePhotoCount');
  const clear = document.getElementById('clearMaintenancePhotos');
  if (inputs.some(input => !input) || !previews || !count || !clear) return;
  let urls = [];
  const release = () => { urls.forEach(url => URL.revokeObjectURL(url)); urls = []; };
  const update = () => {
    release();
    previews.replaceChildren();
    const files = inputs.flatMap(input => Array.from(input.files || []));
    count.textContent = files.length ? `Đã chọn ${files.length}/5 ảnh${files.length > 5 ? '. Hãy giảm còn tối đa 5 ảnh.' : '.'}` : '';
    clear.hidden = !files.length;
    for (const file of files) {
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) continue;
      const img = document.createElement('img');
      const figure = document.createElement('figure');
      const caption = document.createElement('figcaption');
      const url = URL.createObjectURL(file);
      urls.push(url);
      img.src = url;
      img.alt = 'Ảnh sự cố đã chọn';
      img.style.cssText = 'width:100%;height:160px;object-fit:cover;border-radius:12px';
      caption.textContent = file.name;
      caption.className = 'small text-muted text-break mt-2';
      figure.append(img, caption);
      previews.append(figure);
    }
  };
  inputs.forEach(input => input.addEventListener('change', update));
  clear.addEventListener('click', () => { inputs.forEach(input => { input.value = ''; }); update(); });
  window.addEventListener('pagehide', release);
  update();
})();
