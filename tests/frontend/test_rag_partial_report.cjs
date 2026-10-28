const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('app/static/rageval.html','utf8');
const el=(tag,cls,text)=>({tag,cls,text:text??'',style:{},children:[],innerHTML:'',appendChild(child){this.children.push(child);}});
const c={el,document:{createTextNode:text=>el('text',null,text)},STRAT:[{key:'vector',label:'Dense',v:'green'}],faithCases:()=>el('div')};
vm.createContext(c);
vm.runInContext(source.match(/const fmt = .*;/)[0],c);
vm.runInContext(source.slice(source.indexOf('function valFn('),source.indexOf('function drawChart(')),c);
vm.runInContext(source.slice(source.indexOf('function tablePanel('),source.indexOf('function notesPanel(')),c);
const flatten=node=>[node.text,node.innerHTML,...node.children.map(flatten)].join(' ');
for(const rate of [null,0,0.8]){
  const d={best:{strategy:'vector'},retrieval:{vector:{overall:{mrr:0.9}}},evidence_coverage:{},generation_done:true,
    generation:{answer_coverage:{vector:{overall:null}},refusal:{rate,correct:0,total:0}}};
  const text=flatten(c.tablePanel(d));
  assert(text.includes('—'));
  assert(text.includes(rate===null?'refusal rate is unavailable':rate===0?'0% Correctly refused':'80% Correctly refused'));
}
console.log('Partial report: null coverage renders safely; missing refusal differs from a measured zero.');
