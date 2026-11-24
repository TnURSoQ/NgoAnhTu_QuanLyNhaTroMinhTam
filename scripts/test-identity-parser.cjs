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
Phường thử nghiệm, Hà Nội
Có giá trị đến: 12/05/2041`;
assert.deepEqual(parse(text), {id_card_number:'099999999991', full_name:'NGUYỄN VĂN THỬ', date_of_birth:'2001-05-12', hometown:'Hải Châu, Đà Nẵng', gender:'male', nationality:'Việt Nam', permanent_address:'Phường thử nghiệm, Hà Nội', identity_expires_on:'2041-05-12'});
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
const modern = parse(`Họ, chữ đệm và tên khai sinh: LÊ VĂN THỬ\nNgày, tháng, năm sinh: 12/05/2001\nGiới tính: Nam\nQuốc tịch: Việt Nam\nNơi cư trú / Place of residence:\nPhường thử nghiệm, Hà Nội\nNơi đăng ký khai sinh / Place of birth:\nĐà Nẵng\nNgày, tháng, năm cấp / Date of issue: 01/08/2024\nNgày, tháng, năm hết hạn / Date of expiry: 12/05/2041`);
assert.equal(modern.permanent_address,'Phường thử nghiệm, Hà Nội');
assert.equal(modern.residence_address,undefined);
assert.equal(modern.birth_registration_place,'Đà Nẵng');
assert.equal(modern.place_of_birth,undefined);
assert.equal(modern.hometown,undefined);
assert.equal(modern.identity_issued_on,'2024-08-01');
assert.equal(modern.identity_expires_on,'2041-05-12');
assert.equal(modern.date_of_birth,'2001-05-12');
assert.equal(parse('Nơi sinh: Huế\nQuê quán: Đà Nẵng\nNơi thường trú: Hà Nội').place_of_birth,'Huế');
assert.equal(parse('Giới tính: Nữ').gender,'female');
assert.equal(dateValue('12/05/2041', true),'2041-05-12');
assert.equal(parse('Địa chỉ thường trú: Hà Nội').permanent_address,'Hà Nội');
assert.equal(parse('Place of residence: Hà Nội').permanent_address,'Hà Nội');
assert.equal(parse('Đặc điểm nhận dạng: Không có').identifying_features,undefined);
console.log('Identity parser: 27 real-data-shape checks passed.');
