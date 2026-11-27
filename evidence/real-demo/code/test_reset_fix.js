// 定向检查：重置按钮 id="reset" 遮蔽 el.form.reset 导致 TypeError 的修复（Node vm + 简易 DOM 桩）
const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync('artifacts/index.html','utf8');
const code=html.match(/<script>([\s\S]*?)<\/script>/)[1];

let pass=0,fail=0;const lines=[];
function check(name,cond,detail){const ok=!!cond;ok?pass++:fail++;
  lines.push((ok?'[PASS]  ':'[FAIL]  ')+name+(detail?'  →  '+detail:''));
  if(!ok)console.error('FAIL:',name,detail||'');}

// —— 1. 脚本语法检查 ——
try{new vm.Script(code,{filename:'artifacts/index.html<script>'});check('语法 · 内联脚本可成功编译（vm.Script）',true);}
catch(e){check('语法 · 内联脚本可成功编译（vm.Script）',false,'错误: '+e.message);}

// —— 2. 源码中不再有 el.form.reset() ——
const hasCall=/el\.form\.reset\s*\(/.test(code);
const hasAnyResetCall=/\.reset\s*\(/.test(code);
check('源码 · 脚本中已无 el.form.reset() 调用',!hasCall,'匹配 el.form.reset(: '+(hasCall?'有':'无'));
check('源码 · 脚本中已无任何 .reset() 调用',!hasAnyResetCall,'匹配 .reset(: '+(hasAnyResetCall?'有':'无'));
check('源码 · 重置监听器仍保留手动清空 / render() / focus()',
  /el\.reset\.addEventListener\('click',function\(\)\{el\.total\.value='';el\.people\.value='';render\(\);el\.total\.focus\(\);\}\)/.test(code),
  '监听器: '+(code.match(/el\.reset\.addEventListener[^\n]*/)||['未找到'])[0]);

// —— 3. 运行时：form.reset 被同名按钮元素遮蔽时，点击不再抛 TypeError ——
function makeEl(id){return{id,value:'',textContent:'',innerHTML:'',className:'',
  listeners:{},addEventListener(t,f){(this.listeners[t]=this.listeners[t]||[]).push(f)},
  fire(t){(this.listeners[t]||[]).forEach(f=>f({preventDefault(){}}))},focus(){this.focused=true}};}
const els={};const document={getElementById:id=>els[id]||(els[id]=makeEl(id))};
const ctx={document,console};vm.createContext(ctx);vm.runInContext(code,ctx);
// 模拟浏览器行为：form 内 id="reset" 的按钮遮蔽 form.reset 内置方法（同名属性优先）
els.form.reset=els.reset;   // 该按钮不是函数
els.total.value='100';els.people.value='3';ctx.render();
let threw=null;
try{els.reset.fire('click');}catch(e){threw=e;}
check('运行时 · 点击重置不再抛出 TypeError（form.reset 被按钮遮蔽）',threw===null,
  threw?('异常: '+threw.name+': '+threw.message):'无异常抛出');
check('运行时 · 点击重置后输入被清空、明细清空、回到“等待输入…”',
  els.total.value===''&&els.people.value===''&&els.list.innerHTML===''&&els.per.textContent==='—'&&els.note.textContent==='等待输入…',
  'total="'+els.total.value+'" people="'+els.people.value+'" per="'+els.per.textContent+'" note="'+els.note.textContent+'"');
check('运行时 · 点击重置后焦点回到总金额输入框',els.total.focused===true,'focused='+els.total.focused);

const out=[];
out.push('','='.repeat(64),'补充验证 —— 重置按钮 el.form.reset 遮蔽问题修复（本轮）',
 '生成时间: '+new Date().toISOString(),
 '运行环境: Node '+process.version+'（vm 模块 + 简易 DOM 桩，未使用浏览器/Playwright/服务器）',
 '被测文件: artifacts/index.html（'+html.replace(/\n$/,'').split('\n').length+' 行，内联 CSS/JS，离线可用）',
 '修复内容: 删除重置监听器中的 el.form.reset() 调用，保留手动清空两个输入、render() 与 focus()',
 '本轮用例: '+lines.length+' 项（语法 1 + 源码 3 + 运行时 3），通过 '+pass+' 项，失败 '+fail+' 项','');
lines.forEach(l=>out.push(l));
out.push('','结论: '+(fail===0?'全部通过 ✅':'存在失败 ❌'));
console.log(out.join('\n'));
process.exit(fail===0?0:1);
