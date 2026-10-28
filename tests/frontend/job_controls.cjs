// Offline DOM unit test: no browser, network, API keys, or model calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag) { this.tagName=tag;this.children=[];this.listeners={};this.style={};this.classList={add(){}}; }
  appendChild(child) {this.children.push(child);return child;}
  addEventListener(type,handler) {this.listeners[type]=handler;}
  async click() {if (!this.disabled) await this.listeners.click();}
}
async function main() {
  const calls=[];let refreshes=0;let poll;let nextStatus='running';
  const document={createElement:tag=>new Element(tag),getElementById:()=>null,body:new Element('body')};
  const context={document,window:{},confirm:()=>true,
    setInterval:callback=>{poll=callback;return 1;},clearInterval:()=>{},setTimeout:()=>1,clearTimeout:()=>{},
    fetch:async(path,opts)=>{
      calls.push({path,method:opts?.method||'GET'});
      return {ok:true,json:async()=>({status:path.endsWith('/stop')?'stopped':nextStatus,returncode:null})};
    }};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('app/static/acceptance.js','utf8'),context);
  const log=new Element('pre');
  const controls=context.jobButton({name:'bench-agent',title:'Agent evaluation',status:'idle',heavy:true},log,()=>{refreshes++;});
  const [run,stop]=controls.children;
  assert.equal(stop.disabled,true);
  assert.equal(stop.textContent,'Stop evaluation');
  await run.click();
  assert.equal(run.disabled,true);assert.equal(stop.disabled,false);
  assert.equal(calls[0].path,'/api/jobs/bench-agent');
  await stop.click();
  assert.equal(calls[1].path,'/api/jobs/bench-agent/stop');
  assert.equal(calls[1].method,'POST');
  assert.equal(stop.disabled,true);assert.equal(run.disabled,false);assert.equal(refreshes,1);
  await run.click();nextStatus='ok';await poll();
  assert.equal(refreshes,2);assert.equal(stop.disabled,true);assert.equal(run.disabled,false);
  const active=context.jobButton({name:'eval-rag',title:'RAG evaluation',status:'running'},new Element('pre'),()=>{});
  assert.equal(active.children[1].disabled,false); // Refreshing a running page still offers Stop.
  console.log('Job controls: start, stop, completion refresh, and running-page recovery passed (offline).');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
