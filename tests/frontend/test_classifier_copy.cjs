const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const html = fs.readFileSync('app/static/acceptance.html', 'utf8');
function node(tag, cls, text) {
  return {tag, cls, text: text || '', children: [], appendChild(x) { this.children.push(x); return x; }};
}
const box = node('div');
const context = {el:node, $:()=>box, jobSpecs:{}, jobRow:()=>node('div'), load:()=>{},
  PILL:{pass:['pass','Approve'],missing:['missing','Missing artifact']}};
vm.createContext(context);
vm.runInContext(html.slice(html.indexOf('    function renderCards('), html.indexOf('    mountAdminNav(', html.indexOf('    function renderCards('))), context);
context.renderCards({blocks:[
  {key:'data',no:1,status:'pass',title:'English dataset',headline:'100 examples',note:'',jobs:[]},
  {key:'golden',no:2,status:'missing',title:'Independent annotation review',headline:'No independently reviewed English gold set yet',note:'',jobs:[]},
  {key:'train',no:3,status:'pass',title:'English model',headline:'English weights, tokenizer, threshold and provenance',note:'',jobs:[]},
]});
const flatten = n => [n.text, ...n.children.map(flatten)].join(' ');
const text = flatten(box);
assert(text.includes('Topic dataset') && text.includes('Topic classifier'));
assert(text.includes('No independently reviewed gold set yet'));
assert(text.includes('Model weights, tokenizer, threshold and provenance'));
assert(!text.includes('English'));
console.log('Classifier overview: concise labels render with existing backend responses.');
