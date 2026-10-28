const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const c={window:{},document:{readyState:'loading',addEventListener(){}}};vm.createContext(c);vm.runInContext(fs.readFileSync('app/static/english-ui.js','utf8'),c);
assert.equal(c.window.petMoney(499,'USD'),'$499.00');
assert.equal(c.window.petMoney(39,'USD'),'$39.00');
assert.match(c.window.petMoney(1999,'CNY'),/^CNY/);
assert.equal(c.window.petMoney(499),'Price unavailable');
assert.equal(c.window.petMoney(null,'USD'),'Price unavailable');
console.log('Explicit USD, preserved CNY, and unknown-currency formatting passed.');
