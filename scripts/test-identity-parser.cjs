const assert = require('node:assert/strict');
const {parse, dateValue} = require('../static/js/identity-parser.js');
const text = `MẪU KIỂM THỬ ĐỌC CHỮ
CĂN CƯỚC CÔNG DÂN
Số / No.: 099999999991
Họ và tên / Full name:
NGUYỄN VĂN THỬ
Ngày sinh / Date of birth: 12/05/2001
Giới tính / Sex: Nam
Quốc tịch / Nationality: Việt Nam
Quê quán / Place of origin:
Hải Châu, Đà Nẵng
Nơi thường trú / Place of residence:
Địa chỉ thường trú khác quê quán
Có giá trị đến: 12/05/2041`;
assert.deepEqual(parse(text), {id_card_number:'099999999991', full_name:'NGUYỄN VĂN THỬ', date_of_birth:'2001-05-12', hometown:'Hải Châu, Đà Nẵng'});
assert.equal(parse('Số: 099 999 999 991').id_card_number,'099999999991');
assert.equal(parse('Số: 123456789').id_card_number,'123456789');
assert.equal(parse('012345678901\n012345678902').id_card_number,undefined);
assert.equal(parse('Ngày sinh: 12/05/2001\nCó giá trị đến: 12/05/2041').id_card_number,undefined);
assert.equal(parse('Có giá trị đến: 12/05/2041').date_of_birth,undefined);
assert.equal(parse('Nơi thường trú: Đà Nẵng').hometown,undefined);
assert.equal(parse('Full name: TEST PERSON\nDate of birth: 3-2-2000').full_name,'TEST PERSON');
assert.equal(parse('Họ, chữ đệm và tên khai sinh: LÊ VĂN THỬ').full_name,'LÊ VĂN THỬ');
assert.equal(parse('Họ và tên: HỒ VĂN THỬ').full_name,'HỒ VĂN THỬ');
assert.equal(dateValue('31/02/2001'),'');
assert.equal(dateValue('01/01/2100'),'');
assert.deepEqual(parse(''),{});
console.log('Identity parser: 13 real-data-shape checks passed.');
