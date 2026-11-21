(() => {
  const form = document.getElementById('roomForm');
  if (!form) return;
  const input = form.querySelector('[name="photos"]');
  const coverIndex = form.querySelector('[name="new_cover_index"]');
  const preview = document.getElementById('newPhotoPreviews');
  const clearButton = document.getElementById('clearNewPhotos');
  const counter = document.getElementById('photoSelectionCount');
  const existingCovers = [...form.querySelectorAll('.photo-cover')];
  const deletions = [...form.querySelectorAll('.photo-delete')];
  let urls = [];
  coverIndex.value = '';

  function count() {
    const remaining = deletions.filter(box => !box.checked).length;
    const total = remaining + input.files.length;
    counter.textContent = `${total}/10 ảnh sau khi lưu`;
    counter.classList.toggle('text-danger', total > 10);
    counter.classList.toggle('text-muted', total <= 10);
    deletions.forEach(box => box.closest('.room-photo-edit-card').classList.toggle('opacity-50', box.checked));
  }

  function resetPreview() {
    urls.forEach(url => URL.revokeObjectURL(url));
    urls = [];
    preview.replaceChildren();
    coverIndex.value = '';
    clearButton.hidden = input.files.length === 0;
    [...input.files].forEach((file, index) => {
      const card = document.createElement('figure');
      card.className = 'room-photo-edit-card';
      if (['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
        const photo = document.createElement('img');
        const url = URL.createObjectURL(file);
        urls.push(url);
        photo.src = url;
        photo.alt = `Ảnh mới ${index + 1}: ${file.name}`;
        card.append(photo);
      }
      const caption = document.createElement('figcaption');
      caption.className = 'small text-muted mt-2 text-break';
      caption.textContent = file.name;
      const label = document.createElement('label');
      label.className = 'd-flex gap-2 align-items-center mt-2';
      const radio = document.createElement('input');
      radio.type = 'radio';
      radio.name = 'new_photo_cover';
      radio.className = 'form-check-input';
      radio.value = String(index);
      radio.addEventListener('change', () => {
        existingCovers.forEach(existing => { existing.checked = false; });
        coverIndex.value = String(index);
      });
      if (existingCovers.length === 0 && index === 0) {
        radio.checked = true;
        coverIndex.value = '0';
      }
      label.append(radio, document.createTextNode('Ảnh đại diện'));
      card.append(caption, label);
      preview.append(card);
    });
    count();
  }

  input.addEventListener('change', resetPreview);
  existingCovers.forEach(radio => radio.addEventListener('change', () => {
    coverIndex.value = '';
    preview.querySelectorAll('input[type="radio"]').forEach(newCover => { newCover.checked = false; });
  }));
  deletions.forEach(box => box.addEventListener('change', count));
  clearButton.addEventListener('click', () => { input.value = ''; resetPreview(); });
  window.addEventListener('beforeunload', () => urls.forEach(url => URL.revokeObjectURL(url)));
  count();
})();
