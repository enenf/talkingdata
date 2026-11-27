// 精简回归测试：仅覆盖本轮三处修复 + 必要场景（Node 内置 vm + 简易 DOM 桩，无浏览器/服务器）
const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync('artifacts/index.html','utf8');
const code=html.match(/<script>([\s\S]*?)<\/script>/)[1];

function makeEl(id){return{id,value:'',textContent:'',innerHTML:'',className:'',
  listeners:{},addEventListener(t,f){(this.listeners[t]=this.listeners[t]||[]).push(f)},
  fire(t){(this.listeners[t]||[]).forEach(f=>f({preventDefault(){}}))},focus(){this.focused=true},reset(){this.value=''}};}
function load(){const els={};const document={getElementById:id=>els[id]||(els[id]=makeEl(id))};
  const ctx={document,console};vm.createContext(ctx);vm.runInContext(code,ctx);return{els,ctx};}
const amounts=html2=>{const m=String(html2).match(/<b>([^<]*)<\/b>/g)||[];return m.map(s=>s.replace(/<\/?b>/g,''));};

let pass=0,fail=0;const lines=[];
function check(name,cond,detail){const ok=!!cond;ok?pass++:fail++;lines.push((ok?'[PASS]  ':'[FAIL]  ')+name+(detail?'  →  '+detail:''));if(!ok)console.error('FAIL:',name,detail||'');}

function render(els,ctx,t,p){els.total.value=t;els.people.value=p;ctx.render();}
const sums=a=>a.map(x=>Math.round(parseFloat(x.replace('¥',''))*100)).reduce((x,y)=>x+y,0);

// —— 三处新检查 ——
{const{ctx}=load();
 check('新检查1 · parseMoney(".") 必须被拒绝（金额至少含一个数字）',ctx.parseMoney('.').ok===false,'结果: '+JSON.stringify(ctx.parseMoney('.')));
 check('新检查1b · parseMoney(".5") 仍有效（50 分）',ctx.parseMoney('.5').ok===true&&ctx.parseMoney('.5').cents===50,'结果: '+JSON.stringify(ctx.parseMoney('.5')));
 const big=ctx.parseMoney('99999999999999999999.99');
 check('新检查2 · 超出安全整数的金额被拒绝',big.ok===false&&big.msg==='金额过大，无法精确计算','结果: '+JSON.stringify(big));
 const over=ctx.parseMoney('90071992547409.92');
 check('新检查2b · 超过 Number.MAX_SAFE_INTEGER 分值被拒绝',over.ok===false&&over.msg==='金额过大，无法精确计算','结果: '+JSON.stringify(over));
 const okMax=ctx.parseMoney('90071992547409.91');
 check('新检查2c · 恰在安全整数上限内的金额仍可计算',okMax.ok===true&&okMax.cents===9007199254740991,'结果: '+JSON.stringify(okMax));
}
{const{els,ctx}=load();render(els,ctx,'100','7');
 const note=els.note.textContent,a=amounts(els.list.innerHTML);
 check('新检查3 · 100 元 7 人提示“每人各多付 ¥0.01”',note.includes('前 4 人各多付 ¥0.01')&&!note.includes('¥0.04'),'提示: '+note);
 check('新检查3b · 100 元 7 人逐人金额为 4×14.29 + 3×14.28（合计 100.00）',a.filter(x=>x==='¥14.29').length===4&&a.filter(x=>x==='¥14.28').length===3&&sums(a)===10000,'明细: '+a.join(', '));
}

// —— 必要回归 ——
{const{els,ctx}=load();render(els,ctx,'100','3');const a=amounts(els.list.innerHTML);
 check('回归 · 100 元 / 3 人 → 33.34、33.33、33.33，合计 100.00',a.join(',')==='¥33.34,¥33.33,¥33.33'&&sums(a)===10000,'明细: '+a.join(', ')+'，合计 '+(sums(a)/100).toFixed(2));}
{const{els,ctx}=load();render(els,ctx,'0','2');const a=amounts(els.list.innerHTML);
 check('回归 · 0 元 / 2 人 → 0.00、0.00，合计 0.00',a.join(',')==='¥0.00,¥0.00'&&sums(a)===0,'明细: '+a.join(', ')+'，合计 '+(sums(a)/100).toFixed(2));}
{const{els,ctx}=load();render(els,ctx,'10.01','2');const a=amounts(els.list.innerHTML);
 check('回归 · 10.01 元 / 2 人 → 5.01、5.00，合计 10.01',a.join(',')==='¥5.01,¥5.00'&&sums(a)===1001,'明细: '+a.join(', ')+'，合计 '+(sums(a)/100).toFixed(2));}
{const{els,ctx}=load();render(els,ctx,'100','3');els.reset.fire('click');
 check('回归 · 重置按钮清空输入/明细并回到初始状态',els.total.value===''&&els.people.value===''&&els.list.innerHTML===''&&els.per.textContent==='—'&&els.note.textContent==='等待输入…'&&els.result.className==='',
  'total="'+els.total.value+'" people="'+els.people.value+'" per="'+els.per.textContent+'" note="'+els.note.textContent+'"');
 check('回归 · 无效输入（人数 0 / 负金额 / "." / 超大金额）均给出红色错误提示',
  (render(els,ctx,'10','0'),els.result.className==='err'&&els.note.textContent==='人数必须大于 0')&&
  (render(els,ctx,'-1','2'),els.note.textContent==='总金额不能为负数')&&
  (render(els,ctx,'.','2'),els.note.textContent==='请输入有效的数字')&&
  (render(els,ctx,'99999999999999999999','2'),els.note.textContent==='金额过大，无法精确计算'),
  '人数0/负金额/"."/超大金额 四种错误提示均已验证');}

const out=[];
out.push('','='.repeat(64),'补充验证 —— 三处缺陷修复复核（本轮）',
 '生成时间: '+new Date().toISOString(),
 '运行环境: Node '+process.version+'（vm 模块 + 简易 DOM 桩，未使用浏览器/Playwright/服务器）',
 '被测文件: artifacts/index.html（'+html.replace(/\n$/,'').split('\n').length+' 行，内联 CSS/JS，离线可用）',
 '修复内容: ① 金额字符串须至少含一个数字（"." 被拒绝） ② 分值超出 Number.isSafeInteger 时拒绝 ③ 余数提示改为“每人各多付 ¥0.01”',
 '本轮用例: 8 项（新检查 3 处 + 必要回归），通过 '+pass+' 项，失败 '+fail+' 项','');
lines.forEach(l=>out.push(l));
out.push('','结论: '+(fail===0?'全部通过 ✅':'存在失败 ❌'));
console.log(out.join('\n'));
process.exit(fail===0?0:1);
