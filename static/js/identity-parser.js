((root) => {
  const fold = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[đĐ]/g, 'd').toLowerCase();
  const clean = value => value.replace(/\s+/g, ' ').replace(/^[:/\s-]+/, '').trim();
  const isLabel = value => /^(?:so|no|ho(?: va ten|,? chu dem| ten)|full name|ngay|date|gioi tinh|sex|quoc tich|nationality|que quan|nguyen quan|noi|place of|co gia tri|dac diem|dan toc|ton giao)\b/.test(fold(value));

  function dateValue(value) {
    const match = value.match(/\b(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})\b/);
    if (!match) return '';
    const day = Number(match[1]), month = Number(match[2]), year = Number(match[3]);
    const date = new Date(year, month - 1, day), now = new Date();
    if (year < 1900 || date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day || date > now) return '';
    return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  }

  function parse(text) {
    const lines = String(text || '').normalize('NFC').split(/\r?\n/).map(clean).filter(Boolean);
    const fields = {};
    const candidates = new Set(), labelled = new Set();
    for (const line of lines) {
      const runs = line.match(/[0-9][0-9 .]{6,}[0-9]/g) || [];
      for (const run of runs) {
        const number = run.replace(/[ .]/g, '');
        if (/^(?:[0-9]{9}|[0-9]{12})$/.test(number)) {
          if (number.length === 12) candidates.add(number);
          if (/\b(?:so|no|number)\b/.test(fold(line))) labelled.add(number);
        }
      }
    }
    const ids = labelled.size ? labelled : candidates;
    if (ids.size === 1) fields.id_card_number = [...ids][0];

    const after = (index, pattern, multiline = false) => {
      const line = lines[index], match = pattern.exec(fold(line));
      if (!match) return '';
      let value = clean(line.slice(match.index + match[0].length));
      for (let next = index + 1; next < Math.min(lines.length, index + (multiline ? 4 : 3)); next++) {
        if (isLabel(lines[next])) break;
        if (value && !multiline) break;
        value = clean(value + ' ' + lines[next]);
        if (!multiline) break;
      }
      return value;
    };
    for (let index = 0; index < lines.length; index++) {
      const name = after(index, /(?:\bho\b.*?\bten\b(?: khai sinh)?(?:\s*\/\s*full name)?|full name)\s*:?[\s]*/);
      if (name && name.length <= 100 && !/[0-9]/.test(name) && !isLabel(name)) fields.full_name = name;
      const birthday = after(index, /(?:ngay(?: thang nam)? sinh(?:\s*\/\s*date of birth)?|date of birth)\s*:?[\s]*/);
      if (birthday && dateValue(birthday)) fields.date_of_birth = dateValue(birthday);
      const origin = after(index, /(?:que quan|nguyen quan)(?:\s*\/\s*place of origin)?\s*:?[\s]*/, true);
      if (origin && origin.length <= 255 && !isLabel(origin)) fields.hometown = origin;
    }
    return fields;
  }

  const api = { parse, dateValue };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.IdentityCardParser = api;
})(typeof window !== 'undefined' ? window : globalThis);
