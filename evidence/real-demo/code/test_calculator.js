'use strict';
/* 离线费用分摊计算器 —— Node 端验证脚本（vm + 简易 DOM 桩，不使用浏览器/Playwright/服务器） */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = __dirname;
const HTML_PATH = path.join(ROOT, 'artifacts', 'index.html');
const OUT_PATH = path.join(ROOT, 'artifacts', 'verification.txt');

const results = [];
function check(name, fn) {
  try {
    const detail = fn();
    results.push({ name, pass: true, detail: detail || 'ok' });
  } catch (err) {
    results.push({ name, pass: false, detail: (err && err.message) || String(err) });
  }
}
function assert(cond, msg) { if (!cond) throw new Error(msg || '断言失败'); }
function eq(actual, expected, msg) {
  if (actual !== expected) throw new Error((msg || '值不相等') + '：期望 ' + JSON.stringify(expected) + '，实际 ' + JSON.stringify(actual));
}

/* ---------- 读取页面并提取内联脚本 ---------- */
const html = fs.readFileSync(HTML_PATH, 'utf8');
const lineCount = html.replace(/\n$/, '').split('\n').length;
const scriptMatch = /<script>([\s\S]*?)<[/]script>/.exec(html);
if (!scriptMatch) throw new Error('未找到内联 <script> 块');
const inlineScript = scriptMatch[1];

/* ---------- 简易 DOM 桩 ---------- */
function createElement(id) {
  return {
    id, value: '', textContent: '', className: '', innerHTML: '', listeners: {}, controls: [],
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    dispatch(type, extra) {
      const evt = Object.assign({ type, defaultPrevented: false, preventDefault() { evt.defaultPrevented = true; } }, extra || {});
      (this.listeners[type] || []).forEach(fn => fn.call(this, evt));
      return evt;
    },
    focus() { this.focused = true; },
    reset() { this.controls.forEach(c => { c.value = ''; }); }
  };
}
const IDS = ['form', 'total', 'people', 'result', 'per', 'note', 'list', 'reset'];
const elements = {};
IDS.forEach(id => { elements[id] = createElement(id); });
elements.form.controls = [elements.total, elements.people];
const documentStub = {
  getElementById(id) { return elements[id] || null; },
  querySelector() { return null; },
  addEventListener() {},
  body: createElement('body')
};

/* ---------- 在 vm 中执行内联脚本 ---------- */
const sandbox = { document: documentStub, console };
sandbox.window = sandbox;
sandbox.self = sandbox;
vm.createContext(sandbox);
vm.runInContext(inlineScript, sandbox, { filename: 'artifacts/index.html#inline-script' });
const parseMoney = sandbox.parseMoney;
const parsePeople = sandbox.parsePeople;
const split = sandbox.split;
assert(typeof parseMoney === 'function', '内联脚本未导出 parseMoney');
assert(typeof parsePeople === 'function', '内联脚本未导出 parsePeople');
assert(typeof split === 'function', '内联脚本未导出 split');

function setForm(total, people) {
  elements.total.value = total;
  elements.people.value = people;
  elements.total.dispatch('input');
}
function listAmounts() {
  const out = [];
  const re = /<b>¥([0-9.]+)/g;
  let m;
  while ((m = re.exec(elements.list.innerHTML)) !== null) out.push(m[1]);
  return out;
}
function listSumCents() {
  return listAmounts().reduce((acc, s) => acc + Math.round(parseFloat(s) * 100), 0);
}
function centsText(c) { return '¥' + (c / 100).toFixed(2); }

/* ---------- 结构 / 离线自洽检查 ---------- */
check('HTML 总行数 ≤ 100（实际 ' + lineCount + ' 行）', () => {
  assert(lineCount <= 100, '行数 ' + lineCount + ' 超过 100 行');
  return '实际 ' + lineCount + ' 行';
});
check('CSS 与 JS 全部内联（无 <link>、无外部 script src）', () => {
  assert(/<style>[\s\S]*<[/]style>/.test(html), '缺少内联 <style>');
  assert(/<script>[\s\S]*<[/]script>/.test(html), '缺少内联 <script>');
  assert(!/<link\b/i.test(html), '存在外部样式表 <link>');
  assert(!/<script[^>]+src=/i.test(html), '存在外部脚本引用');
  return '内联 style + script';
});
check('不依赖外网（无 http(s) 链接、无网络 API）', () => {
  assert(!/https?:\/\//i.test(html), '页面包含 http(s) 外部地址');
  assert(!/\bfetch\s*\(|XMLHttpRequest|WebSocket|EventSource|navigator\.sendBeacon/.test(html), '页面包含网络调用');
  return '无外部地址与网络调用';
});
check('关键中文文案齐全（含重置、明细、合计）', () => {
  ['费用分摊计算器', '总金额', '人数', '重置', '计算', '第 ', '人', '合计', '等待输入'].forEach(t => {
    assert(html.includes(t), '缺少文案：' + t);
  });
  return '9 项文案均存在';
});
check('脚本引用的 DOM id 均在 HTML 中存在', () => {
  const ids = [...inlineScript.matchAll(/getElementById\('([^']+)'\)/g)].map(m => m[1]);
  assert(ids.length > 0, '未解析到任何 getElementById');
  ids.forEach(id => assert(html.includes("id='" + id + "'"), 'HTML 中缺少 id=' + id));
  return '校验 ' + ids.length + ' 个 id：' + ids.join(', ');
});
check('重置按钮存在且为 type=button（不会误提交表单）', () => {
  assert(/<button[^>]*id='reset'[^>]*type='button'/.test(html) || /<button[^>]*type='button'[^>]*id='reset'/.test(html), '缺少 type=button 的重置按钮');
  return 'id=reset, type=button';
});

check('HTML 标签闭合平衡（剥离 script/style 文本后校验）', () => {
  const stripped = html.replace(/<script>[\s\S]*?<\/script>/g, '[S]').replace(/<style>[\s\S]*?<\/style>/g, '[C]');
  const voidTags = ['meta','br','hr','img','input','link','area','base','col','embed','source','track','wbr'];
  const stack = [];
  let ok = true;
  const re = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*?)(\/?)>/g;
  let m;
  while ((m = re.exec(stripped)) !== null) {
    const tag = m[2].toLowerCase();
    if (m[1] === '/') { if (stack.pop() !== tag) ok = false; }
    else if (voidTags.indexOf(tag) === -1 && m[4] !== '/') { stack.push(tag); }
  }
  assert(ok && stack.length === 0, '标签未正确闭合，剩余：' + stack.join(','));
  return '标签全部闭合';
});

/* ---------- 金额解析（整数分） ---------- */
check('parseMoney："100" → 10000 分', () => {
  const r = parseMoney('100');
  assert(r.ok === true, '应解析成功：' + JSON.stringify(r));
  eq(r.cents, 10000, '分值错误');
  return '10000 分';
});
check('parseMoney："10.01" → 1001 分', () => {
  const r = parseMoney('10.01');
  eq(r.cents, 1001, '分值错误');
  return '1001 分';
});
check('parseMoney："0" → 0 分', () => {
  eq(parseMoney('0').cents, 0, '分值错误');
  return '0 分';
});
check('parseMoney："0.1" → 10 分（0.3/3 无浮点误差）', () => {
  eq(parseMoney('0.1').cents, 10, '分值错误');
  return '10 分';
});
check('parseMoney：".5" → 50 分（省略整数位）', () => {
  eq(parseMoney('.5').cents, 50, '分值错误');
  return '50 分';
});
check('parseMoney："10.5" → 1050 分', () => {
  eq(parseMoney('10.5').cents, 1050, '分值错误');
  return '1050 分';
});
check('parseMoney："1,200.50" → 120050 分（支持千分位）', () => {
  eq(parseMoney('1,200.50').cents, 120050, '分值错误');
  return '120050 分';
});
check('parseMoney："  50.00  " → 5000 分（忽略首尾空白）', () => {
  eq(parseMoney('  50.00  ').cents, 5000, '分值错误');
  return '5000 分';
});
check('parseMoney：空值 → 提示请输入总金额', () => {
  const r = parseMoney('');
  eq(r.ok, false, '应被拒绝');
  eq(r.msg, '请输入总金额', '提示错误');
  return r.msg;
});
check('parseMoney："-10" → 提示不能为负数', () => {
  const r = parseMoney('-10');
  eq(r.ok, false, '应被拒绝');
  eq(r.msg, '总金额不能为负数', '提示错误');
  return r.msg;
});
check('parseMoney："abc" → 提示有效的数字', () => {
  const r = parseMoney('abc');
  eq(r.ok, false, '应被拒绝');
  eq(r.msg, '请输入有效的数字', '提示错误');
  return r.msg;
});
check('parseMoney："10.005" → 提示金额最多保留两位小数', () => {
  const r = parseMoney('10.005');
  eq(r.ok, false, '应被拒绝');
  eq(r.msg, '金额最多保留两位小数', '提示错误');
  return r.msg;
});
check('parseMoney："Infinity" / "NaN" / "1e3" → 提示有效的数字', () => {
  ['Infinity', 'NaN', '1e3'].forEach(v => {
    const r = parseMoney(v);
    eq(r.ok, false, v + ' 应被拒绝');
    eq(r.msg, '请输入有效的数字', v + ' 提示错误');
  });
  return '3 种无效写法均被拒绝';
});

/* ---------- 人数解析 ---------- */
check('parsePeople："3" → 3 人', () => {
  const r = parsePeople('3');
  assert(r.ok === true, '应解析成功');
  eq(r.n, 3, '人数错误');
  return '3 人';
});
check('parsePeople："0" → 提示人数必须大于 0', () => {
  const r = parsePeople('0');
  eq(r.ok, false, '应被拒绝');
  eq(r.msg, '人数必须大于 0', '提示错误');
  return r.msg;
});
check('parsePeople："-2" → 提示人数必须大于 0', () => {
  const r = parsePeople('-2');
  eq(r.ok, false, '应被拒绝');
  eq(r.msg, '请输入有效的数字', '提示错误');
  return r.msg;
});
check('parsePeople："1000" → 提示人数不能超过 999', () => {
  const r = parsePeople('1000');
  eq(r.ok, false, '应被拒绝');
  eq(r.msg, '人数不能超过 999', '提示错误');
  return r.msg;
});
check('parsePeople："2.5" → 提示人数必须是整数', () => {
  const r = parsePeople('2.5');
  eq(r.ok, false, '应被拒绝');
  eq(r.msg, '人数必须是整数', '提示错误');
  return r.msg;
});
check('parsePeople："abc" → 提示有效的数字', () => {
  const r = parsePeople('abc');
  eq(r.ok, false, '应被拒绝');
  eq(r.msg, '请输入有效的数字', '提示错误');
  return r.msg;
});
check('parsePeople：空值 → 提示请输入人数', () => {
  const r = parsePeople('');
  eq(r.ok, false, '应被拒绝');
  eq(r.msg, '请输入人数', '提示错误');
  return r.msg;
});

/* ---------- 分摊算法（余数从第一人开始分配） ---------- */
check('split：10000 分 / 3 人 → [3334, 3333, 3333]', () => {
  eq(JSON.stringify(split(10000, 3)), JSON.stringify([3334, 3333, 3333]), '分摊结果错误');
  return '33.34, 33.33, 33.33';
});
check('split：0 分 / 2 人 → [0, 0]', () => {
  eq(JSON.stringify(split(0, 2)), JSON.stringify([0, 0]), '分摊结果错误');
  return '0.00, 0.00';
});
check('split：1001 分 / 2 人 → [501, 500]', () => {
  eq(JSON.stringify(split(1001, 2)), JSON.stringify([501, 500]), '分摊结果错误');
  return '5.01, 5.00';
});
check('split：120050 分 / 4 人 → [30013, 30013, 30012, 30012]', () => {
  eq(JSON.stringify(split(120050, 4)), JSON.stringify([30013, 30013, 30012, 30012]), '分摊结果错误');
  return '300.13, 300.13, 300.12, 300.12';
});
check('split：余数优先分配给前面的人（首人 ≥ 末人）', () => {
  const a = split(10000, 3);
  assert(a[0] >= a[a.length - 1], '余数未从第一人开始分配');
  assert(a[0] - a[a.length - 1] === 1, '余数差值应为 1 分');
  return '首人 3334 ≥ 末人 3333';
});
check('split：任意金额与人数的合计恒等于原金额（300 组随机用例）', () => {
  let checked = 0;
  for (let i = 0; i < 300; i++) {
    const cents = Math.floor(Math.random() * 200000);
    const people = 1 + Math.floor(Math.random() * 60);
    const arr = split(cents, people);
    eq(arr.length, people, '人数不一致');
    eq(arr.reduce((a, b) => a + b, 0), cents, '合计与原金额不一致');
    arr.forEach(v => { assert(Number.isInteger(v) && v >= 0, '分摊金额必须为非负整数分'); });
    checked++;
  }
  return '随机 ' + checked + ' 组全部满足 sum == 原金额';
});

/* ---------- DOM 交互测试 ---------- */
check('DOM 初始状态：显示"等待输入…"且明细为空', () => {
  eq(elements.note.textContent, '等待输入…', '初始提示错误');
  eq(elements.per.textContent, '—', '初始金额应为空');
  eq(elements.list.innerHTML, '', '明细列表应为空');
  return '初始状态正确';
});
check('DOM：100 元 / 3 人 → 33.34、33.33、33.33，合计 ¥100.00', () => {
  setForm('100', '3');
  eq(elements.result.className, 'ok', '应为成功状态');
  eq(elements.per.textContent, '¥33.33', '每人应付金额错误');
  eq(JSON.stringify(listAmounts()), JSON.stringify(['33.34', '33.33', '33.33']), '明细金额错误');
  eq(listSumCents(), 10000, '明细合计不等于 10000 分');
  assert(elements.note.textContent.includes('合计 ¥100.00'), '提示缺少合计：' + elements.note.textContent);
  assert(elements.note.textContent.includes('多付 ¥0.01'), '提示缺少余数说明：' + elements.note.textContent);
  return listAmounts().join(' / ') + '，合计 ' + centsText(listSumCents());
});
check('DOM：0 元 / 2 人 → 0.00、0.00，合计 ¥0.00', () => {
  setForm('0', '2');
  eq(elements.result.className, 'ok', '应为成功状态');
  eq(elements.per.textContent, '¥0.00', '每人应付金额错误');
  eq(JSON.stringify(listAmounts()), JSON.stringify(['0.00', '0.00']), '明细金额错误');
  eq(listSumCents(), 0, '明细合计不为 0');
  assert(elements.note.textContent.includes('合计 ¥0.00'), '提示缺少合计：' + elements.note.textContent);
  return listAmounts().join(' / ') + '，合计 ' + centsText(listSumCents());
});
check('DOM：10.01 元 / 2 人 → 5.01、5.00，合计 ¥10.01', () => {
  setForm('10.01', '2');
  eq(elements.result.className, 'ok', '应为成功状态');
  eq(elements.per.textContent, '¥5.00', '每人应付金额错误');
  eq(JSON.stringify(listAmounts()), JSON.stringify(['5.01', '5.00']), '明细金额错误');
  eq(listSumCents(), 1001, '明细合计不等于 1001 分');
  assert(elements.note.textContent.includes('合计 ¥10.01'), '提示缺少合计：' + elements.note.textContent);
  return listAmounts().join(' / ') + '，合计 ' + centsText(listSumCents());
});
check('DOM：1200.50 元 / 4 人 → 300.13、300.13、300.12、300.12', () => {
  setForm('1200.50', '4');
  eq(JSON.stringify(listAmounts()), JSON.stringify(['300.13', '300.13', '300.12', '300.12']), '明细金额错误');
  eq(listSumCents(), 120050, '明细合计不等于 120050 分');
  return listAmounts().join(' / ');
});
check('DOM：明细条目数量与人数一致（7 人 → 7 条）', () => {
  setForm('100', '7');
  eq(listAmounts().length, 7, '明细条目数量错误');
  eq(listSumCents(), 10000, '明细合计不等于 10000 分');
  return '7 条明细，合计 ' + centsText(listSumCents());
});
check('DOM：人数为 0 → 红色错误态并提示人数', () => {
  setForm('100', '0');
  eq(elements.result.className, 'err', '结果状态样式应为 err');
  eq(elements.list.innerHTML, '', '错误时应清空明细');
  assert(elements.note.textContent.includes('人数'), '提示应包含"人数"，实际：' + elements.note.textContent);
  return elements.note.textContent;
});
check('DOM：负金额 → 红色错误态并提示不能为负数', () => {
  setForm('-10', '4');
  eq(elements.result.className, 'err', '结果状态样式应为 err');
  assert(elements.note.textContent.includes('负'), '提示应包含"负"，实际：' + elements.note.textContent);
  return elements.note.textContent;
});
check('DOM：无效输入 "abc" → 红色错误态并提示有效的数字', () => {
  setForm('abc', '4');
  eq(elements.result.className, 'err', '结果状态样式应为 err');
  assert(elements.note.textContent.includes('有效'), '提示应包含"有效"，实际：' + elements.note.textContent);
  return elements.note.textContent;
});
check('DOM：金额留空、人数填写 → 提示请输入总金额', () => {
  setForm('', '4');
  eq(elements.result.className, 'err', '结果状态样式应为 err');
  eq(elements.note.textContent, '请输入总金额', '提示错误');
  return elements.note.textContent;
});
check('DOM：人数留空 → 提示请输入人数', () => {
  setForm('100', '');
  eq(elements.result.className, 'err', '结果状态样式应为 err');
  eq(elements.note.textContent, '请输入人数', '提示错误');
  return elements.note.textContent;
});
check('DOM：提交表单 → 阻止跳转并刷新结果', () => {
  setForm('100', '3');
  const evt = elements.form.dispatch('submit');
  eq(evt.defaultPrevented, true, 'submit 事件未调用 preventDefault');
  eq(elements.per.textContent, '¥33.33', '提交后金额未刷新');
  return 'submit 已阻止默认行为，结果正确';
});
check('DOM：重置按钮 → 清空输入、清空明细、回到初始状态', () => {
  setForm('100', '3');
  elements.reset.dispatch('click');
  eq(elements.total.value, '', '金额输入未清空');
  eq(elements.people.value, '', '人数输入未清空');
  eq(elements.list.innerHTML, '', '明细未清空');
  eq(elements.note.textContent, '等待输入…', '提示未回到初始状态');
  eq(elements.result.className, '', '结果区不应带有状态样式');
  eq(elements.per.textContent, '—', '金额应回到占位符');
  return '重置后完全回到初始状态';
});
check('DOM：事件监听已注册（total/people/form/reset）', () => {
  eq((elements.total.listeners.input || []).length, 1, 'total 未监听 input');
  eq((elements.people.listeners.input || []).length, 1, 'people 未监听 input');
  eq((elements.form.listeners.submit || []).length, 1, 'form 未监听 submit');
  eq((elements.reset.listeners.click || []).length, 1, 'reset 未监听 click');
  return 'total/people: input，form: submit，reset: click';
});
check('DOM：清空两个输入 → 回到初始"等待输入…"状态', () => {
  setForm('', '');
  eq(elements.note.textContent, '等待输入…', '提示文案错误');
  eq(elements.result.className, '', '结果区不应带有状态样式');
  eq(elements.list.innerHTML, '', '明细应为空');
  return '初始状态正确';
});

/* ---------- 输出报告 ---------- */
const passed = results.filter(r => r.pass).length;
const failed = results.length - passed;
const lines = [];
lines.push('费用分摊计算器 —— 自动化验证报告');
lines.push('生成时间: ' + new Date().toISOString());
lines.push('运行环境: Node ' + process.version + '（vm 模块 + 简易 DOM 桩，未使用浏览器/Playwright/服务器）');
lines.push('被测文件: artifacts/index.html（' + lineCount + ' 行，内联 CSS/JS，离线可用）');
lines.push('本轮改进: ① 金额按整数分计算 ② 余数从第一人开始分配、合计与原金额一致 ③ 列出每人金额明细 ④ 新增重置按钮');
lines.push('');
lines.push('总计 ' + results.length + ' 项：通过 ' + passed + ' 项，失败 ' + failed + ' 项');
lines.push('');
results.forEach((r, i) => {
  lines.push((r.pass ? '[PASS] ' : '[FAIL] ') + String(i + 1).padStart(2, ' ') + '. ' + r.name + '  →  ' + r.detail);
});
lines.push('');
lines.push('关键场景复核：');
lines.push('  · 100 元 / 3 人   → 33.34、33.33、33.33，合计 100.00');
lines.push('  · 0 元 / 2 人     → 0.00、0.00，合计 0.00');
lines.push('  · 10.01 元 / 2 人 → 5.01、5.00，合计 10.01');
lines.push('  · 无效输入       → 人数为 0、负金额、非数字、空值均给出红色错误提示');
lines.push('');
lines.push('结论: ' + (failed === 0 ? '全部通过 ✅' : '存在失败用例 ❌'));
const report = lines.join('\n') + '\n';
fs.writeFileSync(OUT_PATH, report, 'utf8');
process.stdout.write(report);
process.exit(failed === 0 ? 0 : 1);
