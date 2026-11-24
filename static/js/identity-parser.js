((root) => {
  const fold = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[đĐ]/g, 'd').toLowerCase();
  const clean = value => value.replace(/\s+/g, ' ').replace(/^[:/\s-]+/, '').trim();
  const isLabel = value => /^(?:so|no|ho(?: va ten|,? chu dem| ten)|full name|ngay|date|gioi tinh|sex|quoc tich|nationality|que quan|nguyen quan|noi|dia chi|place of|permanent|co quan cap|issuing authority|co gia tri|dac diem|dan toc|ton giao)\b/.test(fold(value));

  function dateValue(value, allowFuture = false) {
    const match = value.match(/\b(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})\b/);
    if (!match) return '';
    const day = Number(match[1]), month = Number(match[2]), year = Number(match[3]);
    const date = new Date(year, month - 1, day), now = new Date();
    if (year < 1900 || date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day || (!allowFuture && date > now)) return '';
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
      for (let next = index + 1; next < Math.min(lines.length, index + (multiline ? 7 : 4)); next++) {
        if (!value && /^(?:full name|date of birth|date of issue|date of expiry|place of residence|place of origin|place of birth|sex|nationality)\s*:?$/.test(fold(lines[next]))) continue;
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
      const birthday = after(index, /(?:ngay(?:[,\s]+thang[,\s]+nam)?\s+sinh(?:\s*\/\s*date of birth)?|date of birth)\s*:?[\s]*/);
      if (birthday && dateValue(birthday)) fields.date_of_birth = dateValue(birthday);
      const origin = after(index, /(?:que quan|nguyen quan)(?:\s*\/\s*place of origin)?\s*:?[\s]*/, true);
      if (origin && origin.length <= 255 && !isLabel(origin)) fields.hometown = origin;
      const mappings = [
        ['permanent_address', /(?:noi thuong tru|dia chi thuong tru|permanent residence|noi cu tru|^place of residence)(?:\s*\/\s*place of residence)?\s*:?[\s]*/, 500],
        ['birth_registration_place', /noi dang ky khai sinh(?:\s*\/\s*place of birth)?\s*:?[\s]*/, 255],
        ['place_of_birth', /noi sinh(?:\s*\/\s*place of birth)?\s*:?[\s]*/, 255],
        ['nationality', /(?:quoc tich(?:\s*\/\s*nationality)?|^nationality)\s*:?[\s]*/, 100],
        ['identity_issued_by', /(?:noi cap|co quan cap|issuing authority)\s*:?[\s]*/, 255],
      ];
      for (const [name, pattern, limit] of mappings) {
        const value = after(index, pattern, name !== 'nationality');
        if (value && value.length <= limit && !isLabel(value)) fields[name] = value;
      }
      const sex = fold(after(index, /(?:gioi tinh(?:\s*\/\s*sex)?|^sex)\s*:?[\s]*/));
      if (/^(?:nam|male)\b/.test(sex)) fields.gender = 'male';
      else if (/^(?:nu|female)\b/.test(sex)) fields.gender = 'female';
      const issued = after(index, /(?:ngay(?:[,\s]+thang[,\s]+nam)?\s+cap(?:\s*\/\s*date of issue)?|date of issue)\s*:?[\s]*/);
      if (issued && dateValue(issued)) fields.identity_issued_on = dateValue(issued);
      const expiry = after(index, /(?:co gia tri den|ngay(?:[,\s]+thang[,\s]+nam)?\s+het han|date of expiry)(?:\s*\/\s*date of expiry)?\s*:?[\s]*/);
      if (expiry && dateValue(expiry, true)) fields.identity_expires_on = dateValue(expiry, true);
    }
    return fields;
  }

  const api = { parse, dateValue };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.IdentityCardParser = api;
})(typeof window !== 'undefined' ? window : globalThis);
