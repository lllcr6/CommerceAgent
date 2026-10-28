const assert=require('assert'),fs=require('fs'),vm=require('vm');
const context={window:{}};vm.createContext(context);vm.runInContext(fs.readFileSync('app/static/usage-cost.js','utf8'),context);
const cost=context.window.agentCostEstimate;
assert(Math.abs(cost(1000,200,0.5,2)-0.0009)<1e-12);
assert.equal(cost(1000,200,0,0),0);
for(const values of [[null,200,1,1],[1000,200,NaN,1],[1000,200,-1,1],[1000,200,Infinity,1]])assert.equal(cost(...values),null);
console.log('Agent cost: separate USD input/output rates, zero price, missing/invalid inputs verified.');
