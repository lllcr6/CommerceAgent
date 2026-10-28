const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync('app/static/observability.html', 'utf8');
const start = source.indexOf('      const judge = d.judge;');
const end = source.indexOf('      p.appendChild(el("p", "lede", "Input and output tokens', start);
assert(start >= 0 && end > start);
function node(tag, cls, text) { return {tag, cls, text: text || '', textContent: '', children: [], appendChild(x) { this.children.push(x); }}; }
const root = node('div');
const context = {p: root, d: {judge: {model: 'model', pass_rate: null, pass: 0, assessed: 0, uncertain: 1, failed_calls: 1, judged: 1, planned: 2,
  scope: 'Synthetic only.', cases: [{scenario: 'sample', repeat: 0, status: 'completed', overall: 'uncertain',
    dimensions: {grounding: {verdict: 'uncertain', reason: 'Not visible'}}, turns: [{turn: 1, prompt: '<unsafe>', answer: 'Hello', tools: []}]}]}},
  el: node, document: {createElement: tag => node(tag)}};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
const flatten = n => [n.text, n.textContent, ...n.children.map(flatten)].join(' ');
const text = flatten(root);
assert(text.includes('Pass rate: Not available'));
assert(text.includes('1 uncertain'));
assert(text.includes('1 judge calls failed'));
assert(text.includes('Not visible'));
assert(text.includes('<unsafe>'));
assert(!text.includes('0%'));
console.log('Agent judge: uncertainty, failed calls, and case details render safely.');
