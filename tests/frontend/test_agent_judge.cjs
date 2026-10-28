const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
function node(tag) {
  return {tag, className: '', textContent: '', children: [], attributes: {}, hidden: false, listeners: {},
    append(...nodes) { this.children.push(...nodes); }, appendChild(child) { this.children.push(child); return child; },
    replaceChildren(...nodes) { this.children = nodes; }, setAttribute(key, value) { this.attributes[key] = value; },
    addEventListener(event, fn) { this.listeners[event] = fn; }};
}
const context = {window: {}, document: {createElement: node}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('app/static/agent-judge.js', 'utf8'), context);
const flatten = n => [n.textContent, ...n.children.map(flatten)].join(' ');
const find = (n, predicate) => predicate(n) ? n : n.children.map(x => find(x, predicate)).find(Boolean);
const cases = [
  {scenario: 'policy_return', repeat: 0, overall: 'pass', turns: []},
  {scenario: 'safety_issue', repeat: 1, overall: 'fail', dimensions: {safety: {verdict:'fail', reason:'Needs review'}},
    turns:[{turn:1,prompt:'<unsafe>',answer:'A safe reply',tools:['lookup'],actions:[]}]},
  {scenario: 'orders_status', repeat: 0, overall: 'uncertain', turns:[]},
  {scenario: 'timeout', repeat: 0, status:'error', error:'TimeoutError', turns:[]},
  ...Array.from({length:5}, (_, i) => ({scenario:'other_'+i, repeat:0, overall:'pass', turns:[]})),
];
const root = context.window.renderAgentJudge({model:'model', pass_rate:null, pass:6, assessed:7,
  fail:1, uncertain:1, failed_calls:1, judged:8, planned:9, scope:'Synthetic only.', cases});
let text = flatten(root);
assert(text.includes('Pass rate') && text.includes('—'));
assert(text.includes('6 of 7 assessed') && text.includes('1 judge calls failed'));
assert(text.includes('Safety Issue') && text.includes('Needs review'));
assert(text.includes('<unsafe>') && text.includes('Tools observed: lookup'));
assert(text.indexOf('Safety Issue') < text.indexOf('Policy Return'));
const more = find(root, n => n.className === 'judge-more');
assert(!more.hidden); more.listeners.click(); assert(more.hidden);
const passed = find(root, n => n.className === 'judge-filter' && n.textContent === 'Passed');
passed.listeners.click(); text = flatten(root);
assert(text.includes('Policy Return') && !text.includes('Safety Issue'));
assert.equal(passed.attributes['aria-pressed'], 'true');
const uncertain = find(root, n => n.className === 'judge-filter' && n.textContent === 'Uncertain');
uncertain.listeners.click(); text = flatten(root);
assert(text.includes('Orders Status') && !text.includes('Policy Return'));
const missing = context.window.renderAgentJudge(null);
assert(flatten(missing).includes('No judge results yet'));
console.log('Agent judge: results, safe text, filtering, pagination, and missing states passed.');
