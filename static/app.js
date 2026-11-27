'use strict';
const $ = id => document.getElementById(id);
const state = {sessions:[], selected:null, detail:null, source:null, lastEvent:0, config:null, loading:false, drafts:{}};
const labels = {running:'进行中',completed:'已完成',failed:'失败',cancelled:'已停止',interrupted:'已中断'};
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let toastTimer;
function toast(message){$('toast').textContent=message;$('toast').classList.remove('hidden');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.add('hidden'),5000);}
async function api(path, options={}){
  const response = await fetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers}});
  if(response.status===401){if(!$('login-dialog').open)$('login-dialog').showModal();throw new Error('请输入工作台访问密码');}
  const data=await response.json();
  if(!response.ok)throw new Error(data.error||'请求失败，请稍后重试');
  return data;
}
const post=(path,data)=>api(path,{method:'POST',body:JSON.stringify(data)});
function endpoint(action,id=state.selected){return `/api/sessions/${id}/${action}`;}
function running(){return state.detail?.runs.at(-1)?.status==='running';}
function formatSize(n){return n<1024?`${n} B`:n<1048576?`${(n/1024).toFixed(1)} KB`:`${(n/1048576).toFixed(1)} MB`;}
function timeLabel(t){return t?new Date(t).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}):'';}
function markdown(text){
  // Escape first: model output and uploaded content never become trusted HTML.
  const blocks=[];
  let s=esc(text).replace(/```[^\n]*\n([\s\S]*?)```/g,(_,code)=>{blocks.push(`<pre><code>${code}</code></pre>`);return `\n@@BLOCK${blocks.length-1}@@\n`;});
  const inline=s=>s.replace(/`([^`\n]+)`/g,'<code>$1</code>').replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
  const lines=s.split('\n'),html=[];
  const cells=line=>line.trim().replace(/^\||\|$/g,'').split('|').map(c=>inline(c.trim()));
  for(let i=0;i<lines.length;){
    const line=lines[i].trim();
    if(!line){i++;continue;}
    const block=/^@@BLOCK(\d+)@@$/.exec(line);
    if(block){html.push(blocks[Number(block[1])]||'');i++;continue;}
    const heading=/^#{1,6}\s+(.+)$/.exec(line);
    if(heading){html.push(`<h3>${inline(heading[1])}</h3>`);i++;continue;}
    if(line.includes('|')&&i+1<lines.length&&/^[|:\-\s]+$/.test(lines[i+1])&&lines[i+1].includes('-')){
      const header=cells(line);i+=2;let rows='';
      while(i<lines.length&&lines[i].includes('|')&&lines[i].trim()){
        rows+='<tr>'+cells(lines[i++]).map(c=>`<td>${c}</td>`).join('')+'</tr>';
      }
      html.push('<div class="table-wrap"><table><thead><tr>'+header.map(c=>`<th>${c}</th>`).join('')+'</tr></thead><tbody>'+rows+'</tbody></table></div>');continue;
    }
    const list=/^(?:[-*]|\d+\.)\s+/.test(line);
    if(list){
      const ordered=/^\d+\./.test(line),tag=ordered?'ol':'ul';let items='';
      const pattern=ordered?/^\d+\.\s+/:/^[-*]\s+/;
      while(i<lines.length&&pattern.test(lines[i].trim()))items+='<li>'+inline(lines[i++].trim().replace(pattern,''))+'</li>';
      html.push(`<${tag}>${items}</${tag}>`);continue;
    }
    if(line.startsWith('&gt;')){html.push('<blockquote>'+inline(line.replace(/^&gt;\s?/,''))+'</blockquote>');i++;continue;}
    if(/^[-*_]{3,}$/.test(line)){html.push('<hr>');i++;continue;}
    const paragraph=[inline(lines[i++])];
    while(i<lines.length&&lines[i].trim()&&!/^(?:#{1,6}\s|[-*]\s|\d+\.\s|@@BLOCK|&gt;)/.test(lines[i]))paragraph.push(inline(lines[i++]));
    html.push('<p>'+paragraph.join('<br>')+'</p>');
  }
  return html.join('');
}
function renderSessions(){
  const q=$('search').value.trim().toLowerCase();
  const sessions=state.sessions.filter(s=>s.title.toLowerCase().includes(q));
  $('session-count').textContent=state.sessions.length;
  $('sessions').innerHTML=sessions.map(s=>`<button class="session ${s.id===state.selected?'selected':''} ${s.status==='running'?'running':''}" data-session="${s.id}"><span class="session-symbol">${s.status==='running'?'◌':'▧'}</span><span class="session-text"><strong>${esc(s.title)}</strong><small>${labels[s.status]||'等待开始'} · ${timeLabel(s.updated_at)}</small></span></button>`).join('')||`<p class="sidebar-empty">${q?'没有找到相关会话':'还没有会话。<br>新建一个，开始你的工作。'}</p>`;
}
function renderFiles(){
  const files=state.detail?.files||[];$('file-count').textContent=files.length;
  $('files').innerHTML=files.length?files.map(f=>{
    const name=f.path.split('/').at(-1), ext=name.includes('.')?name.split('.').at(-1).toUpperCase().slice(0,4):'FILE';
    const url=endpoint('file')+'?path='+encodeURIComponent(f.path);
    return `<div class="file-row"><span class="file-type">${esc(ext)}</span><button class="file-info" data-preview="${esc(f.path)}"><strong>${esc(name)}</strong><small>${esc(f.path.split('/').slice(0,-1).join('/'))} · ${formatSize(f.size)}</small></button><a class="file-download" href="${url}" download aria-label="下载 ${esc(name)}">↓</a></div>`;
  }).join(''):'<div class="file-empty"><span class="file-empty-icon">▱</span>成果会出现在这里<br>上传材料，或让助手创建文件</div>';
  $('download-all').classList.toggle('hidden',!files.length);$('download-all').href=endpoint('bundle');
}
function eventHTML(e){
  const p=e.payload;
  const names={status:'助手状态',command:'命令执行',files:'文件变更',answer:'助手进展',error:'执行异常',done:labels[p.status]||'执行结束',usage:'本次用量',log:'运行日志'};
  return `<div class="event ${esc(p.kind)}"><div class="event-title">${names[p.kind]||'执行事件'}<span>${timeLabel(e.created_at)}</span></div>${p.kind==='command'?`<code>${esc(p.text)}</code><details ${p.exit_code?'open':''}><summary>${p.status==='completed'?`退出码 ${p.exit_code??0}`:p.status==='failed'?'执行失败':'执行中'}</summary><pre>${esc(p.output||'暂无输出')}</pre></details>`:`<p>${esc(p.text).slice(0,24000)}</p>`}</div>`;
}
function renderActivity(){
  $('activity').innerHTML=(state.detail?.events||[]).map(eventHTML).join('')||'<p class="file-empty">还没有执行记录</p>';
  if(running())$('activity-panel').scrollTop=$('activity-panel').scrollHeight;
}
function renderMessages(){
  const messages=state.detail?.messages||[];
  $('welcome').classList.toggle('hidden',messages.length>0);
  let turn=-1;
  $('messages').innerHTML=messages.map(m=>{
    if(m.role==='user')turn++;
    const run=state.detail?.runs[turn];
    const badge=m.role==='user'&&run&&run.status!=='running'?`<div class="turn-result ${run.status==='completed'?'success':'warning'}">${esc(labels[run.status]||run.status)}${run.error?' · '+esc(run.error):''}</div>`:'';
    return `<article class="message ${m.role}"><div class="message-avatar">${m.role==='user'?'你':'栖'}</div><div class="message-body"><div class="message-label">${m.role==='user'?'你':'栖点助手'} · ${timeLabel(m.created_at)}</div><div class="message-content">${m.role==='user'?esc(m.content):markdown(m.content)}</div>${badge}</div></article>`;
  }).join('');
}
function renderStatus(){
  const active=running(), run=state.detail?.runs.at(-1);
  $('send').classList.toggle('hidden',active);$('cancel').classList.toggle('hidden',!active);
  $('upload').disabled=active||state.loading;
  $('send').disabled=state.loading||!$('prompt').value.trim()||!state.config?.ready;
  $('run-status').classList.toggle('hidden',!run);
  if(run)$('run-status').innerHTML=active?'<span class="pulse"></span> 助手正在执行任务 · 你可以切换到其他会话':`<span>${esc(labels[run.status]||run.status)}</span> ${esc(run.error||'成果和对话已保存')}`;
  $('rename').textContent=state.detail?.title||'新的开始';
}
function scrollBottom(){$('conversation').scrollTop=$('conversation').scrollHeight;}
async function refreshSessions(){state.sessions=await api('/api/sessions');renderSessions();}
async function selectSession(id){
  if(state.selected)state.drafts[state.selected]=$('prompt').value;
  state.selected=id;localStorage.setItem('agent-desk-session',id);state.source?.close();state.source=null;
  $('live').classList.add('hidden');$('live').textContent='';
  $('prompt').value=state.drafts[id]||'';renderSessions();
  const detail=await api(`/api/sessions/${id}`);
  if(state.selected!==id)return;
  state.detail=detail;state.lastEvent=detail.events.at(-1)?.id||0;
  renderMessages();renderFiles();renderActivity();renderStatus();scrollBottom();
  if(running())connect(id);
  document.querySelector('.app').classList.remove('show-nav');
}
function connect(id){
  state.source?.close();const source=new EventSource(endpoint('events',id)+`?after=${state.lastEvent}`);state.source=source;
  source.onopen=()=>{if(state.selected===id&&running())$('run-status').innerHTML='<span class="pulse"></span> 助手正在执行任务 · 进度连接正常';};
  source.onmessage=async message=>{
    if(state.selected!==id)return;
    const e=JSON.parse(message.data);
    if(e.id<=state.lastEvent)return;state.lastEvent=e.id;state.detail.events.push(e);
    const nearBottom=$('conversation').scrollHeight-$('conversation').scrollTop-$('conversation').clientHeight<140;
    if(e.payload.kind==='answer'){
      $('live').classList.remove('hidden');const text=document.createElement('div');text.className='live-text';text.textContent=e.payload.text;$('live').replaceChildren(text);if(nearBottom)scrollBottom();
    }
    if(e.payload.kind==='status')$('run-status').innerHTML='<span class="pulse"></span> '+esc(e.payload.text);
    renderActivity();
    if(e.payload.kind==='files')refreshFiles().catch(()=>{});
    if(e.payload.kind==='done'){
      source.close();if(state.source===source)state.source=null;
      await refreshSessions();if(state.selected===id)await selectSession(id);
    }
  };
  source.onerror=()=>{if(state.selected===id&&running())$('run-status').innerHTML='<span class="pulse"></span> 正在恢复进度连接，后台任务仍在执行…';};
}
async function newSession(){const s=await post('/api/sessions',{title:'新会话'});await refreshSessions();await selectSession(s.id);$('prompt').focus();return s.id;}
async function send(){
  const content=$('prompt').value.trim();if(!content||state.loading||running())return;
  state.loading=true;renderStatus();
  try{
    if(!state.selected){const draft=content;await newSession();$('prompt').value=draft;}
    const id=state.selected;await post(endpoint('messages',id),{content});$('prompt').value='';state.drafts[id]='';
    await refreshSessions();await selectSession(id);
  }catch(e){toast(e.message);}finally{state.loading=false;renderStatus();}
}
async function refreshFiles(){const id=state.selected;if(!id)return;const files=await api(endpoint('files',id));if(state.selected===id){state.detail.files=files;renderFiles();}}
async function upload(files){
  if(!files.length)return;
  try{
    if(!state.selected)await newSession();const id=state.selected;
    for(const file of files){
      if(file.size>10485760)throw new Error(`${file.name} 超过 10 MB`);
      const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=reject;r.readAsDataURL(file);});
      await post(endpoint('upload',id),{name:file.name,data});
      toast(`已上传 ${file.name}`);
    }
    await refreshFiles();
  }catch(e){toast(e.message);}finally{$('file-input').value='';}
}
async function preview(path){
  $('preview-title').textContent=path;$('preview-download').href=endpoint('file')+'?path='+encodeURIComponent(path);
  $('preview-content').replaceChildren();$('preview-dialog').showModal();
  const url=endpoint('preview')+'?path='+encodeURIComponent(path);
  if(/\.html?$/i.test(path)){
    const iframe=document.createElement('iframe');iframe.title='隔离成果预览';iframe.setAttribute('sandbox','allow-scripts');iframe.src=url;$('preview-content').append(iframe);
  }else{
    const content=document.createElement(/\.md$/i.test(path)?'div':'pre');content.className=/\.md$/i.test(path)?'markdown-preview message-content':'';content.textContent='正在加载…';$('preview-content').append(content);
    try{const r=await fetch(url);if(!r.ok)throw new Error('预览加载失败');const text=await r.text();if(/\.md$/i.test(path))content.innerHTML=markdown(text);else content.textContent=text;}catch(e){content.textContent=e.message;}
  }
}
async function boot(){
  try{
    state.config=await api('/api/config');
    $('model-status').innerHTML='<i></i> '+esc(state.config.model||'未配置模型')+' · Codex CLI';
    $('config-banner').classList.toggle('hidden',state.config.ready);
    $('config-banner').textContent='运行环境未就绪：'+state.config.missing.join('、')+'。请按 README 配置服务端环境变量后重启。';
    await refreshSessions();
    const saved=localStorage.getItem('agent-desk-session');
    const id=state.sessions.some(s=>s.id===saved)?saved:state.sessions[0]?.id;
    if(id)await selectSession(id);else{renderFiles();renderStatus();}
  }catch(e){if(!$('login-dialog').open)toast(e.message);}
}
$('new-session').onclick=()=>newSession().catch(e=>toast(e.message));
$('search').oninput=renderSessions;
$('sessions').onclick=e=>{const b=e.target.closest('[data-session]');if(b)selectSession(b.dataset.session).catch(e=>toast(e.message));};
$('prompt').oninput=()=>{if(state.selected)state.drafts[state.selected]=$('prompt').value;renderStatus();};
$('prompt').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();send();}};
$('send').onclick=send;
$('cancel').onclick=async()=>{try{await post(endpoint('cancel'),{});toast('已发送停止请求');}catch(e){toast(e.message);}};
$('upload').onclick=()=>$('file-input').click();$('file-input').onchange=e=>upload([...e.target.files]);
$('refresh-files').onclick=()=>refreshFiles().catch(e=>toast(e.message));
$('files').onclick=e=>{const b=e.target.closest('[data-preview]');if(b)preview(b.dataset.preview);};
$('close-preview').onclick=()=>{$('preview-dialog').close();$('preview-content').replaceChildren();};
$('files-tab').onclick=()=>switchTab('files');$('activity-tab').onclick=()=>switchTab('activity');
function switchTab(tab){for(const name of ['files','activity']){$(name+'-tab').setAttribute('aria-selected',String(name===tab));$(name+'-panel').classList.toggle('hidden',name!==tab);}}
document.querySelectorAll('[data-prompt]').forEach(b=>b.onclick=()=>{$('prompt').value=b.dataset.prompt;renderStatus();$('prompt').focus();});
$('menu').onclick=()=>document.querySelector('.app').classList.toggle('show-nav');
$('workspace-toggle').onclick=()=>document.querySelector('.app').classList.toggle('show-workspace');
$('workspace-close').onclick=()=>document.querySelector('.app').classList.remove('show-workspace');
$('rename').onclick=()=>{if(!state.selected)return;$('session-title').value=state.detail.title;$('rename-dialog').showModal();$('session-title').focus();};
$('cancel-rename').onclick=()=>$('rename-dialog').close();
$('rename-form').onsubmit=async e=>{e.preventDefault();try{await post(endpoint('rename'),{title:$('session-title').value});$('rename-dialog').close();await refreshSessions();await selectSession(state.selected);}catch(err){toast(err.message);}};
$('login-form').onsubmit=async e=>{e.preventDefault();try{await post('/api/login',{token:$('access-token').value});$('access-token').value='';$('login-dialog').close();await boot();}catch(err){$('login-error').textContent=err.message;}};
document.addEventListener('keydown',e=>{if(e.key==='n'&&!e.metaKey&&!e.ctrlKey&&!e.altKey&&!['INPUT','TEXTAREA'].includes(document.activeElement.tagName)&&!document.querySelector('dialog[open]')){e.preventDefault();newSession().catch(err=>toast(err.message));}});
setInterval(()=>{if(!document.hidden)refreshSessions().catch(()=>{});},15000);
boot();
