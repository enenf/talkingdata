const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2],'utf8');
const nodes={};
const document={getElementById(id){const node=nodes[id]??=( {value:'',textContent:'',className:'',innerHTML:'',handlers:{},addEventListener(e,f){this.handlers[e]=f},focus(){this.focused=true},reset(){for(const n of Object.values(nodes))n.value=''}}); if(id==='reset'&&nodes.form)nodes.form.reset=node; return node;}};
const context=vm.createContext({document,console});
for(const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi))vm.runInContext(m[1],context);
let passed=0,failed=0;
function test(name,fn){try{fn();passed++;console.log('PASS',name)}catch(e){failed++;console.log('FAIL',name,e.message)}}
for(const [t,n,want]of [['100',3,[3334,3333,3333]],['0',2,[0,0]],['10.01',2,[501,500]]])test(`${t} / ${n}`,()=>assert.deepEqual(Array.from(context.split(context.parseMoney(t).cents,n)),want));
test('invalid dot amount',()=>assert.equal(context.parseMoney('.').ok,false));
test('unsafe integer amount rejected',()=>assert.equal(context.parseMoney('99999999999999999999999999').ok,false));
for(const input of ['abc','NaN','Infinity','-1','1.005'])test('invalid amount '+input,()=>assert.equal(context.parseMoney(input).ok,false));
for(const input of ['0','-1','2.5','abc'])test('invalid people '+input,()=>assert.equal(context.parsePeople(input).ok,false));
test('sum invariant across 1000 deterministic cases',()=>{for(let i=0;i<1000;i++){let cents=(i*7919)%100001,n=i%50+1,a=Array.from(context.split(cents,n));assert.equal(a.reduce((a,b)=>a+b,0),cents);assert.equal(a.length,n);assert.ok(Math.max(...a)-Math.min(...a)<=1)}});
test('remainder note says one cent extra per person',()=>{nodes.total.value='100';nodes.people.value='7';context.render();assert.ok(nodes.note.textContent.includes('¥0.01'),nodes.note.textContent)});
test('reset returns to initial state',()=>{nodes.reset.handlers.click();assert.equal(nodes.total.value,'');assert.equal(nodes.people.value,'');assert.equal(nodes.list.innerHTML,'');assert.equal(nodes.per.textContent,'—')});
console.log(`Independent review: ${passed} passed, ${failed} failed`);process.exitCode=failed?1:0;
