import {state,project,t,e,icon,button,badge,head,card} from './shared.js';
import {renderResearch,handleResearch} from './research.js';
import {renderWriting,handleWriting,discardWritingChanges,writingRouteItem} from './writing.js';

const names={home:['工作台','Workspace'],projects:['我的项目','My projects'],overview:['项目概览','Overview'],files:['项目文件','Files'],analysis:['数据分析','Analysis'],artifacts:['图表与报告','Figures & reports'],literature:['文献','Literature'],manuscripts:['SCI 写作','SCI writing'],reviews:['意见修改','Review revisions'],journals:['期刊建议','Journal suggestions'],'school-templates':['学校模板','School templates'],tasks:['项目任务','Project tasks'],usage:['本人用量','My usage'],admin:['运营管理','Operations'],login:['登录预览','Login preview']};
const pageName=page=>page==='manuscripts'&&project().type==='thesis'?t('毕业论文写作','Thesis writing'):t(...(names[page]||names.home));
const app=document.getElementById('app'),dialog=document.getElementById('dialog');
let toastTimer,focusBeforeDialog,pendingNavigation=null,expanded=false,guardedDialog=false,dialogSnapshot="";
let openedGroup="", committedRoute="";
let historyIndex=Number.isInteger(history.state?.previewIndex)?history.state.previewIndex:0, historyRecovery=null;
const api={render,toast,modal,closeModal,navigate,view:(view)=>navigate(state.page,undefined,view),addTask:(title,status,projectId=project().id)=>state.tasks.unshift({id:`demo-${Date.now()}-${state.tasks.length}`,title,detail:t('本地合成样例操作，不是正式业务任务。','Local synthetic action, not a production task.'),status,page:'analysis',time:t('刚刚','Just now'),project:projectId})};
function statusInfo(status){return ({waiting_confirmation:[t('待确认','To confirm'),'warning'],waiting_input:[t('待补充资料','Needs input'),'warning'],succeeded:[t('已完成','Completed'),'success'],failed:[t('执行失败','Failed'),'danger'],unknown:[t('结果待核实','Outcome unknown'),'warning'],running:[t('运行中','Running'),'info'],queued:[t('待执行','Queued'),'neutral']})[status]||[t('状态未知','Unknown'),'neutral'];}
function projectTasks(){return state.tasks.filter(x=>x.project?x.project===project().id:project().id==='metabolism');}
function previewBar(){return `<div class="preview-bar"><div class="preview-label"><i></i><strong>${t('交互预览','Interactive preview')}</strong><span class="dot-divider">/</span><span>${t('合成数据','Synthetic data')}</span><span class="preview-extra">· ${t('所有操作仅在当前页面演示','All actions are local demonstrations')}</span></div><div class="preview-tools"><a href="responsive.html" class="preview-extra">${t('尺寸预览','View sizes')}</a><button data-act="login">${t('登录页','Login page')}</button><button data-act="reset">${t('重置','Reset')}</button></div></div>`;}
function navItem(page,ic){return `<button class="nav-item ${state.page===page?'active':''}" data-act="nav" data-page="${page}" ${state.page===page?'aria-current="page"':''} aria-label="${e(pageName(page))}" title="${e(pageName(page))}">${icon(ic)}<span class="nav-text">${e(pageName(page))}</span>${page==='tasks'&&projectTasks().some(x=>x.status==='waiting_confirmation')?'<span class="nav-count">1</span>':''}</button>`;}
function taskGroups(){
  return [
    {id:'materials',title:t('材料准备','Materials'),icon:'folder',description:t('整理原始材料与引用来源','Organize materials and references'),items:[['files','folder'],['literature','book']]},
    {id:'analysis',title:t('分析与成果','Analysis & outputs'),icon:'chart',description:t('从分析方案到统计与图表','From analysis plans to figures'),items:[['analysis','chart'],['artifacts','layers']]},
    {id:'writing',title:t('稿件写作','Writing'),icon:'pen',description:t('按章节写作，单独核对依据','Write by section; review sources separately'),items:[['manuscripts','pen'],[project().type==='sci'?'journals':'school-templates','book']]},
    {id:'revision',title:t('评审与修改','Review & revision'),icon:'message',description:t('逐条处理意见，跟踪任务','Address comments and follow tasks'),items:[['reviews','message'],['tasks','clock']]},
  ];
}
function groupFor(page){return taskGroups().find(group=>group.items.some(([item])=>item===page))?.id||'';}
function sidebar(){
  return `<aside class="sidebar" id="sidebar" aria-label="${t('主要导航','Main navigation')}">
    <button class="brand" data-act="nav" data-page="home" aria-label="${t('返回工作台','Back to workspace')}"><span class="brand-symbol">${icon('book',21)}</span><span class="brand-name">PaperAssist<small>by Arviva Therapeutics</small></span></button>
    <div class="sidebar-scroll">${button(t('新建项目','New project'),'new-project','secondary sidebar-new','plus')}
      <nav>${navItem('home','grid')}${navItem('projects','folder')}
        <div class="current-project"><p class="eyebrow">${t('当前项目','Current project')}</p><button data-act="choose-project"><span>${e(project().name)}</span>${icon('chevron',14)}</button></div>
        <div class="project-navigation">${navItem('overview','grid')}
          ${taskGroups().map(group=>`<div class="nav-group ${groupFor(state.page)===group.id?'current':''}">
            <button class="nav-group-toggle" data-act="nav-group" data-group="${group.id}" aria-expanded="${openedGroup===group.id}" aria-controls="group-${group.id}" title="${e(group.title)}" aria-label="${e(group.title)}">${icon(group.icon)}<span class="nav-text">${e(group.title)}</span><span class="group-chevron">${icon('chevron',14)}</span></button>
            <div class="nav-group-children" id="group-${group.id}" ${openedGroup===group.id?'':'hidden'}>${group.items.map(([page,ic])=>navItem(page,ic)).join('')}</div>
          </div>`).join('')}
        </div>
      </nav>
    </div>
    <div class="sidebar-bottom">${navItem('usage','chart')}${state.role==='admin'?navItem('admin','settings'):''}<p class="brand-credit">${t('一步一事，让研究更清楚。','One focused step at a time.')}</p></div>
  </aside>`;
}
function topbar(){
  const inProject=!['home','projects','usage','admin'].includes(state.page);
  return `<header class="topbar"><div class="topbar-left">
    <button class="icon-button" data-act="toggle-sidebar" aria-label="${t('切换侧栏','Toggle sidebar')}" aria-controls="sidebar" aria-expanded="${window.innerWidth<1024?state.mobile:window.innerWidth<1280?expanded:!state.collapsed}">${icon('collapse')}</button>
    <nav class="breadcrumbs" aria-label="${t('面包屑导航','Breadcrumb')}"><button data-act="nav" data-page="projects">${t('我的项目','My projects')}</button>${icon('chevron')}${inProject&&state.page!=='overview'?`<button class="breadcrumb-project" data-act="nav" data-page="overview" title="${e(project().name)}">${e(project().name)}</button><span class="breadcrumb-project">${icon('chevron')}</span>`:''}<strong aria-current="page">${e(pageName(state.page))}</strong></nav>
  </div><div class="topbar-right"><button class="language-button" data-act="language" aria-label="${t('切换到英语','Switch to Chinese')}">${icon('globe',15)}${state.lang==='en'?'中文':'EN'}</button><span class="top-divider"></span><button class="avatar" data-act="account" aria-label="${t('账号与预览角色','Account and preview role')}">${state.role==='admin'?t('管','A'):t('研','R')}</button></div></header>`;
}
function heroGraphic(){return `<svg class="hero-graphic" viewBox="0 0 200 180" aria-hidden="true"><path d="M15 165H195M30 25V165" stroke="#d7e1cc" fill="none"/><path d="M30 70H195M30 115H195" stroke="#dfe8d6" stroke-dasharray="4 5"/><rect x="52" y="95" width="23" height="70" rx="4" fill="#c4d7af"/><rect x="91" y="60" width="23" height="105" rx="4" fill="#a9c68d"/><rect x="130" y="80" width="23" height="85" rx="4" fill="#769b59"/><path d="m40 105 30-24 36 9 35-44 33 15" stroke="#8cae70" stroke-width="2" fill="none"/><circle cx="141" cy="46" r="4" fill="#d99c63"/></svg>`;}
function tableProjects(items){return `<div class="table-scroll" tabindex="0" role="region" aria-label="${t('项目列表','Projects table')}"><table class="project-table"><thead><tr><th>${t('项目名称','PROJECT')}</th><th>${t('类型','TYPE')}</th><th>${t('文件','FILES')}</th><th>${t('最近更新','UPDATED')}</th><th><span class="sr-only">${t('操作','Actions')}</span></th></tr></thead><tbody>${items.map(p=>`<tr><td><div class="project-cell"><span class="project-monogram ${p.color}">${e(p.mark)}</span><div><button class="project-name" data-act="open-project" data-id="${e(p.id)}">${e(p.name)}</button><p class="project-subtitle">${e(p.topic)}</p></div></div></td><td>${badge(p.type==='sci'?'SCI':t('毕业论文','Thesis'))}</td><td class="muted">${p.files} ${t('份','files')}</td><td class="date">${e(p.date)}</td><td><button class="icon-button" data-act="open-project" data-id="${e(p.id)}" aria-label="${e(t('打开项目：','Open project: ')+p.name)}">${icon('arrow',16)}</button></td></tr>`).join('')}</tbody></table></div>`;}
function switcher(items,current,label=t('切换视图','Switch view')){
  return `<div class="view-switcher" role="group" aria-label="${e(label)}">${items.map(([value,title])=>`<button class="view-button ${value===current?'active':''}" data-act="view" data-view="${value}" aria-pressed="${value===current}">${e(title)}</button>`).join('')}</div>`;
}
function home(){
  const current=state.view==='attention'?'attention':'projects';
  const heading=head('WORKSPACE',t('你的研究空间','Your research workspace'),t('先选项目，再进入当前要做的任务。','Choose a project, then focus on one task.'),button(t('新建项目','New project'),'new-project','primary','plus'));
  const tabs=switcher([['projects',t('最近项目','Recent projects')],['attention',t('当前项目待办','Current project actions')]],current);
  if(current==='attention')return heading+tabs+card(t('当前项目：','Current project: ')+project().name,`<div class="task-entry-list">
    ${taskEntry('analysis',t('核对分析方案','Review the analysis plan'),t('选择变量、确认方法，再开始分析。','Choose variables and review the method.'),'chart','plan')}
    ${taskEntry('reviews',t('处理本轮评审意见','Address review comments'),t('一次处理一条意见和一个阶段。','One comment and one step at a time.'),'message','comment')}
    ${taskEntry('tasks',t('查看任务状态','View task status'),t('运行结果与待确认事项集中查看。','Track outcomes and pending decisions.'),'clock')}
  </div>`);
  return heading+tabs+`<section class="continue-card compact-continue"><div><span class="mini-label">${icon('clock',14)}${t('继续当前项目','CONTINUE CURRENT PROJECT')}</span><h2>${e(project().name)}</h2><p>${e(project().topic)}</p></div><div class="continue-actions">${button(t('进入项目','Open project'),'nav','primary','arrow','data-page="overview"')}${badge(project().type==='sci'?'SCI':t('毕业论文','Thesis'),'success')}</div>${heroGraphic()}</section>
  <div class="section-title"><h2>${t('最近打开','Recently opened')}</h2><button class="text-button" data-act="nav" data-page="projects">${t('全部项目','All projects')}${icon('arrow',14)}</button></div>
  <div class="project-cards">${state.projects.slice(0,3).map(p=>`<button class="project-tile" data-act="open-project" data-id="${e(p.id)}"><span class="project-monogram ${p.color}">${e(p.mark)}</span><strong>${e(p.name)}</strong><span class="muted">${p.type==='sci'?'SCI':t('毕业论文','Thesis')} · ${p.files} ${t('份材料','materials')}</span>${icon('arrow',16)}</button>`).join('')}</div>`;
}
function taskEntry(page,title,description,ic,view=''){
  return `<button class="task-entry" data-act="nav" data-page="${page}" data-view="${view}"><span class="quick-icon">${icon(ic)}</span><span><strong>${e(title)}</strong>${description?`<small>${e(description)}</small>`:''}</span>${icon('arrow',16)}</button>`;
}
function projects(){const items=state.projects.filter(p=>(state.projectFilter==='all'||p.type===state.projectFilter)&&`${p.name} ${p.topic}`.toLowerCase().includes(state.search.toLowerCase()));return head('PROJECTS',t('我的项目','My projects'),t('将每个研究的材料、分析和成果放在一起。','Keep each project’s materials, analyses and outputs together.'),button(t('新建项目','New project'),'new-project','primary','plus'))+`<div class="toolbar"><label class="search-field">${icon('search')}<span class="sr-only">${t('搜索项目','Search projects')}</span><input id="project-search" data-input="project-search" placeholder="${t('搜索项目名称或研究主题','Search projects or topics')}" value="${e(state.search)}"></label><select class="filter-select" data-change="project-type" aria-label="${t('项目类型','Project type')}">${[['all',t('全部类型','All types')],['sci','SCI'],['thesis',t('毕业论文','Thesis')]].map(([v,l])=>`<option value="${v}" ${state.projectFilter===v?'selected':''}>${l}</option>`).join('')}</select></div><section class="card">${items.length?tableProjects(items):`<div class="empty">${icon('search',30)}<h3>${t('没有匹配的项目','No matching projects')}</h3><p>${t('试试其他关键词，或清除筛选条件。','Try another keyword or clear your filters.')}</p>${button(t('清除筛选','Clear filters'),'clear-projects')}</div>`}<div class="table-footer"><span>${t(`共 ${items.length} 个项目`,`${items.length} projects`)}</span><span>${t('本地交互预览','Local interactive preview')}</span></div></section>`;}
function overview(){
  const p=project(), current=['details','activity'].includes(state.view)?state.view:'tasks';
  const heading=head(t('项目空间','PROJECT SPACE'),p.name,p.topic,button(t('项目设置','Project settings'),'project-settings','secondary','settings'));
  const tabs=switcher([['tasks',t('研究任务','Research tasks')],['details',t('项目资料','Project details')],['activity',t('活动记录','Activity')]],current);
  if(current==='details')return heading+tabs+card(t('项目资料','Project details'),`<dl class="details-list project-details"><dt>${t('项目类型','Type')}</dt><dd>${p.type==='sci'?'SCI':t('毕业论文','Thesis')}</dd><dt>${t('输出语言','Output language')}</dt><dd>${p.output==='en'?'English':t('简体中文','Simplified Chinese')}</dd><dt>${t('研究材料','Materials')}</dt><dd>${p.files} ${t('份示例','sample files')}</dd><dt>${t('最近更新','Updated')}</dt><dd>${p.date}</dd></dl>`);
  if(current==='activity')return heading+tabs+card(t('活动记录','Activity'),p.isNew?`<p class="muted">${t('这是刚创建的预览项目，尚无历史活动。','This new preview project has no activity history.')}</p>`:`<ul class="timeline"><li><time>${t('合成记录 · 今天','Synthetic record · Today')}</time>${t('打开研究工作区','Opened the research workspace')}</li><li><time>${t('合成记录 · 昨天','Synthetic record · Yesterday')}</time>${t('整理研究材料','Organized research materials')}</li></ul>`);
  return heading+tabs+`${p.isNew?`<p class="compact-status">${icon('info',16)}${t('新项目已就绪。先添加示例材料，或选择任务查看布局。','New project ready. Add sample material or explore a task.')}</p>`:''}<div class="task-groups">${taskGroups().map(group=>`<section class="task-group-card"><header><span class="group-symbol">${icon(group.icon,21)}</span><div><h2>${e(group.title)}</h2><p>${e(group.description)}</p></div></header><div class="task-entry-list">${group.items.map(([page,ic])=>taskEntry(page,pageName(page),'',ic)).join('')}</div></section>`).join('')}</div>`;
}
function tasks(){if(state.view.startsWith('detail-'))return taskDetail(state.view.slice(7));const list=projectTasks().filter(x=>state.taskFilter==='all'||x.status===state.taskFilter);return head('PROJECT TASKS',t('项目任务','Project tasks'),t('每个阶段、每次等待和每份成果，都有清楚的去向。','Follow each stage, decision and saved result.'))+`<div class="toolbar"><div class="tabs" style="margin:0">${[['all',t('全部任务','All tasks')],['waiting_confirmation',t('待确认','Needs confirmation')],['succeeded',t('已完成','Completed')],['failed',t('失败','Failed')]].map(([v,l])=>`<button class="tab ${state.taskFilter===v?'active':''}" data-act="task-filter" data-value="${v}">${l}</button>`).join('')}</div></div><section class="card task-list">${list.length?list.map(x=>`<div class="task-row"><span class="task-icon">${icon(x.status==='succeeded'?'check':x.status==='failed'?'alert':'clock')}</span><div class="task-row-content"><h3>${e(x.title)}</h3><p>${e(x.detail)}</p></div>${badge(...statusInfo(x.status))}<time>${e(x.time)}</time>${button(t('查看详情','View details'),'task-detail','secondary','',`data-id="${e(x.id)}"`)}</div>`).join(''):`<div class="empty">${icon('clock',30)}<h3>${t('当前没有这类任务','No tasks in this view')}</h3><p>${t('可先进入数据分析，运行一次合成样例演示。','Run a synthetic sample in Analysis to create a demo task.')}</p>${button(t('前往分析','Go to analysis'),'nav','secondary','arrow','data-page="analysis"')}</div>`}</section><p class="muted" style="font-size:11px;margin-top:16px">${t('所有记录都是界面演示。结果待核实的请求不会显示“重新发送”。','All records are demonstrations. Requests with unknown outcomes cannot be resent.')}</p>`;}

function taskDetail(id){
  const task=state.tasks.find(task=>task.id===id);
  if(!task||!projectTasks().includes(task))return head('PROJECT TASKS',t('没有找到这条任务','Task not found'),'',button(t('返回任务列表','Back to tasks'),'view','secondary','arrow','data-view="list"'));
  const follow=task.page==='analysis'?'plan':task.page==='manuscripts'?'text':'';
  return head(t('任务详情','TASK DETAILS'),task.title,t('当前项目的合成任务记录','Synthetic task for the current project'),button(t('返回任务列表','Back to tasks'),'view','secondary','arrow','data-view="list"'))+card(t('任务状态','Task status'),`<div class="stack">${badge(...statusInfo(task.status))}<p>${e(task.detail)}</p><div class="notice ${task.status==='unknown'?'warning':''}">${icon('info')}${task.status==='unknown'?t('提交结果尚未核实，不能重新发送。','The submission outcome is unknown. Resending is blocked.'):t('此处仅展示合成任务，没有连接后台。','Synthetic demonstration; no backend connection.')}</div>${task.status!=='unknown'?button(t('进入相关任务','Open related task'),'nav','primary','arrow',`data-page="${task.page}" data-view="${follow}"`):''}</div>`);
}
function usage(){return head('MY USAGE',t('本人用量','My usage'),t('了解预算与使用情况，区分估算、预留和待核对记录。','Understand estimates, reservations and unresolved usage.'))+`<div class="notice admin-note">${icon('info')}${t('以下金额仅为合成界面样例，没有发生真实调用或扣费。','Amounts below are synthetic UI examples. No real calls or charges occurred.')}</div><div class="usage-cards"><section class="card"><p class="usage-label">${t('内部估算 · 合成示例','Internal estimate · Synthetic')}</p><p class="usage-value"><small>USD</small> 2.60</p><p class="muted">${t('不是供应商账单','Not a provider invoice')}</p></section><section class="card"><p class="usage-label">${t('预留预算 · 合成示例','Reserved budget · Synthetic')}</p><p class="usage-value"><small>USD</small> 0.40</p><p class="muted">${t('预留不代表已消耗','Reserved, not consumed')}</p></section><section class="card"><p class="usage-label">${t('待核对记录','Unresolved records')}</p><p class="usage-value">1 <small>${t('条','record')}</small></p>${badge(t('费用尚未确定','Cost not confirmed'),'warning')}</section></div>${card(t('示例用量记录','Sample usage records'),`<div class="table-scroll"><table><thead><tr><th>${t('操作','Operation')}</th><th>${t('口径','Basis')}</th><th>${t('金额','Amount')}</th><th>${t('状态','Status')}</th></tr></thead><tbody><tr><td>${t('稿件内容整理','Draft organization')}</td><td>${t('内部估算','Internal estimate')}</td><td>USD 2.60</td><td>${badge(t('合成示例','Synthetic'),'neutral')}</td></tr><tr><td>${t('图表解释请求','Figure explanation')}</td><td>${t('待核对','Unresolved')}</td><td>${t('未知','Unknown')}</td><td>${badge(t('提交结果待核实','Submission unconfirmed'),'warning')}</td></tr></tbody></table></div>`)}`;}
function admin(){if(state.role!=='admin')return head('OPERATIONS',t('需要管理员视角','Administrator preview required'),t('可在账号菜单中切换预览角色，不改变任何真实权限。','Switch the preview role in the account menu. No real permissions are changed.'),button(t('切换预览角色','Switch preview role'),'account'));return head('OPERATIONS',t('运营管理','Operations'),t('跨账号仅查看运营元数据，研究内容遵循原有所有权。','Operational metadata only. Research content retains its ownership rules.'))+`<div class="notice admin-note">${icon('lock')}${t('管理员视角演示，不连接实际用户、系统任务或运行日志。','Administrator-view demonstration; no real accounts, tasks or logs are connected.')}</div><div class="tabs">${[['accounts',t('账号管理','Accounts')],['tasks',t('系统任务','System tasks')],['usage',t('用量统计','Usage')],['logs',t('运行日志','Logs')]].map(([v,l])=>`<button class="tab ${(state.adminTab||'accounts')===v?'active':''}" data-act="admin-tab" data-value="${v}">${l}</button>`).join('')}</div>${(state.adminTab||'accounts')==='accounts'?card(t('演示账号','Demo accounts'),`<div class="table-scroll"><table><thead><tr><th>${t('账号','Account')}</th><th>${t('角色','Role')}</th><th>${t('状态','Status')}</th><th>${t('操作','Action')}</th></tr></thead><tbody><tr><td>researcher@example.test</td><td>${t('研究者','Researcher')}</td><td>${badge(t('正常 · 样例','Active · Sample'),'success')}</td><td>${button(t('查看权限','View permissions'),'demo-permissions','secondary')}</td></tr></tbody></table></div>`):state.adminTab==='usage'?usage().replace(/<header[\s\S]*?<\/header>/,''):state.adminTab==='tasks'?card(t('系统任务摘要','System task summary'),`<p class="muted">${t('此处仅展示合成运营元数据，不包含其他用户的研究正文。','Synthetic operational metadata only; other users’ research content is not shown.')}</p><div class="artifact-row">${icon('clock')}<span>${t('1 条请求结果待核实','1 request requires outcome verification')}</span>${badge(t('需要核对','Needs review'),'warning')}</div>`):card(t('运行记录摘要','Runtime summary'),`<ul class="timeline"><li><time>2026-10-25 10:42</time>${t('示例任务等待用户确认','Demo task awaiting user confirmation')}</li><li><time>2026-10-25 10:18</time>${t('示例稿件保存完成','Demo manuscript saved')}</li></ul><p class="muted" style="margin-top:20px">${t('此处不是服务器真实日志。','This is not a live server log.')}</p>`)}`;}
function login(){return `${previewBar()}<main class="login-scene"><section class="login-brand"><div class="logo-frame"><img src="assets/arviva-logo.jpg" alt="Arviva Therapeutics"></div><div class="login-brand-copy"><p class="eyebrow">PAPERASSIST</p><h1>${t('专注研究，<br>让思路成为成果。','Focus on research.<br>Give ideas a clear path.')}</h1><p>${t('从第一份材料，到下一版稿件。<br>让研究的每一步，清晰而有据。','From your first dataset to your next draft.<br>A thoughtful space for every step.')}</p></div><p>Arviva Therapeutics · ${t('科研论文辅助系统','Research paper assistant')}</p><div class="login-brand-decoration"></div></section><section class="login-form-side"><div class="login-form"><img class="login-mobile-logo" style="display:none" src="assets/arviva-logo.jpg" alt="Arviva Therapeutics"><p class="eyebrow">WELCOME TO PAPERASSIST</p><h2>${t('欢迎回到你的研究空间','Welcome to your workspace')}</h2><p>${t('这是登录页视觉预览，无需输入真实账号或密码。','This is a login preview. Do not enter real credentials.')}</p><label class="field">${t('演示邮箱','Demo email')}<input type="email" value="researcher@example.test" readonly autocomplete="off"></label><label class="field">${t('演示密码','Demo password')}<input type="password" value="preview-only" readonly autocomplete="off"></label>${button(t('进入交互预览','Enter interactive preview'),'enter-preview','primary','arrow')}<button class="text-button" data-act="recovery">${t('账号恢复入口','Account recovery')}</button><div class="notice">${icon('info',16)}${t('本页仅展示界面布局。不会验证账号、保存密码或连接后台。','Layout demonstration only. No account validation, password storage or backend connection.')}</div></div></section></main>`;}
function render(){document.documentElement.lang=state.lang==='en'?'en':'zh-CN';document.title=`PaperAssist · ${pageName(state.page)} · ${t('交互预览','Interactive preview')}`;if(state.page==='login'){app.innerHTML=login();return;}let content=({home,projects,overview,tasks,usage,admin})[state.page]?.()||renderResearch(state.page)||renderWriting(state.page)||home();app.innerHTML=`${previewBar()}<div class="shell ${state.collapsed?'collapsed':''} ${state.mobile?'mobile-open':''} ${expanded?'expanded':''}">${sidebar()}<button class="nav-backdrop" data-act="close-sidebar" aria-label="${t('关闭导航','Close navigation')}"></button><div class="main-column">${topbar()}<main class="content" id="content" tabindex="-1">${content}</main><footer class="footer"><span><b>PaperAssist</b> <span style="margin:0 8px;color:#b0bba5">/</span> Arviva Therapeutics</span><span>${t('合成数据 · 仅用于界面与交互评审','Synthetic data · For visual and interaction review')}</span></footer></div></div>`;syncNavigation();}
function routeHash(page,id,view='',item=''){
  const path=`#${page}${view?'/'+encodeURIComponent(view):''}`;
  if(['home','projects','usage','admin','login'].includes(page))return path;
  const query=new URLSearchParams({project:id});
  if(item!=='')query.set('item',item);
  return `${path}?${query}`;
}
function readRoute(){
  const [path,query='']=location.hash.slice(1).split('?');
  const [page,encodedView='']=path.split('/');
  let view='';try{view=decodeURIComponent(encodedView);}catch{}
  const params=new URLSearchParams(query),id=params.get('project');
  return {page:Object.hasOwn(names,page)?page:'home',id:state.projects.some(p=>p.id===id)?id:state.selected,view,item:params.get('item')};
}
function needsWritingConfirmation(page,id){return state.writing.dirty&&(page!==state.page||(id&&id!==state.selected));}
function confirmNavigation(destination){
  pendingNavigation=destination;
  modal({title:t('还有未保存的修改','You have unsaved changes'),body:`<p>${t('当前稿件或意见处理计划尚未保存。可以继续编辑，或放弃这些修改后离开。','Your manuscript or revision plan has unsaved edits. Continue editing, or discard them before leaving.')}</p>`,footer:button(t('继续编辑','Keep editing'),'close-modal')+button(t('放弃修改并离开','Discard and leave'),'discard-leave','danger')});
}
function navigate(page,id,view='',historyMode='push',item){
  if(!Object.hasOwn(names,page))return;
  if(needsWritingConfirmation(page,id)){
    confirmNavigation({page,id,view,historyMode,item});return;
  }
  if(id&&state.projects.some(p=>p.id===id))state.selected=id;
  if((page==='journals'&&project().type!=='sci')||(page==='school-templates'&&project().type!=='thesis')){page='overview';view='';}
  if(page==='admin'&&state.role!=='admin'){page='home';view='';}
  state.page=page;state.view=view;state.mobile=false;expanded=false;openedGroup=groupFor(page);
  const target=routeHash(page,state.selected,view,writingRouteItem(page,item));
  if(historyMode==='replace')history.replaceState({previewIndex:historyIndex},'',target);
  else if(target!==committedRoute)history.pushState({previewIndex:++historyIndex},'',target);
  committedRoute=target;
  render();window.scrollTo({top:0,behavior:'instant'});
  document.getElementById('page-title')?.focus({preventScroll:true});
}
function toast(message){clearTimeout(toastTimer);const box=document.getElementById('toast');box.innerHTML=`${icon('check',16)}<span>${e(message)}</span>`;box.hidden=false;toastTimer=setTimeout(()=>box.hidden=true,4200);}
function modal({title,body,footer='',guard=false}){guardedDialog=guard;focusBeforeDialog=document.activeElement;dialog.innerHTML=`<div class="dialog-head"><h2 id="dialog-title">${e(title)}</h2><button class="icon-button" data-act="close-modal" aria-label="${t('关闭','Close')}">${icon('close')}</button></div><div class="dialog-body">${body}</div>${footer?`<div class="dialog-footer">${footer}</div>`:''}`;if(!dialog.open)dialog.showModal();const input=dialog.querySelector('input:not([readonly]),textarea');if(input)input.focus();dialogSnapshot=dialogValues();}
function closeModal(){guardedDialog=false;pendingNavigation=null;dialog.close();if(focusBeforeDialog?.isConnected)focusBeforeDialog.focus();else document.getElementById('page-title')?.focus({preventScroll:true});}
function newProject(){modal({guard:true,title:t('新建研究项目','Create a research project'),body:`<form id="new-project-form"><label class="field">${t('项目名称','Project name')}<input id="new-name" name="name" maxlength="80" required placeholder="${t('例如：代谢表型研究','e.g. Metabolic phenotype study')}"></label><label class="field">${t('研究主题','Research topic')}<textarea id="new-topic" name="topic" rows="3" maxlength="300" required placeholder="${t('用一句话描述你的研究方向','Briefly describe the focus of your research')}"></textarea></label><div class="field" style="margin-top:18px"><span>${t('项目类型','Project type')}</span><div class="type-options"><label class="type-option"><input type="radio" name="type" value="sci" checked> ${t('SCI 科研论文','SCI paper')}</label><label class="type-option"><input type="radio" name="type" value="thesis"> ${t('毕业论文','Thesis')}</label></div></div><p class="muted" style="font-size:11px;margin-top:18px">${t('仅在当前预览中创建，刷新后恢复合成示例。','Created in this preview only. Reloading restores the sample data.')}</p><p id="new-error" class="form-error" role="alert"></p></form>`,footer:button(t('取消','Cancel'),'close-modal')+`<button class="button primary" type="submit" form="new-project-form">${icon('plus')}${t('创建项目','Create project')}</button>`});}
function createProject(){const form=document.getElementById('new-project-form');if(!form.reportValidity())return;const name=form.elements.name.value.trim(),topic=form.elements.topic.value.trim();if(!name||!topic){document.getElementById('new-error').textContent=t('请填写项目名称和研究主题。','Enter a project name and research topic.');return;}const id=`preview-${Date.now()}`;state.projects.unshift({id,name,topic,type:form.elements.type.value,isNew:true,files:0,date:'2026-10-25',mark:name[0].toUpperCase(),color:'sage',next:'files'});closeModal();navigate('overview',id);toast(t('示例项目已创建，仅保存在当前预览。','Demo project created in this preview only.'));}
function account(){modal({title:t('账号与预览角色','Account & preview role'),body:`<div class="account-profile"><span class="avatar large">${t('研','R')}</span><div><h3>${t('演示研究者','Demo researcher')}</h3><p class="account-meta">researcher@example.test</p></div></div><div class="account-links">${button(t('本人用量','My usage'),'account-usage','secondary','chart')}${button(state.role==='admin'?t('切换为研究者视角','Switch to researcher view'):t('体验管理员视角','Try administrator view'),'switch-role','secondary','settings')}${button(t('查看登录页','View login page'),'account-login','ghost','logout')}</div><p class="muted" style="font-size:11px;margin-top:20px">${t('这里切换的是演示视角，不改变任何真实账号权限。','This changes the demo view only, not real account permissions.')}</p>`});}
function settings(){const p=project();modal({guard:true,title:t('项目设置','Project settings'),body:`<label class="field">${t('项目名称','Project name')}<input id="edit-name" value="${e(p.name)}" maxlength="80" required></label><label class="field">${t('研究主题','Research topic')}<textarea id="edit-topic" rows="3" required>${e(p.topic)}</textarea></label><label class="field">${t('项目输出语言','Project output language')}<select id="edit-output"><option value="zh" ${p.output!=='en'?'selected':''}>简体中文</option><option value="en" ${p.output==='en'?'selected':''}>English</option></select><small>${t('影响后续输出的设计设置，不翻译当前合成正文。','A setting for future outputs; current sample text is not translated.')}</small></label><p class="muted" style="margin-top:18px">${t('项目类型创建后只读。','Project type is read-only after creation.')}</p>`,footer:button(t('取消','Cancel'),'close-modal')+button(t('保存设置','Save settings'),'save-settings','primary','save')});}
function action(act,el,event){if(handleResearch(act,el,api)||handleWriting(act,el,api))return;switch(act){
case'nav':navigate(el.dataset.page,undefined,el.dataset.view||'');break;
case'view':api.view(el.dataset.view||'');break;
case'nav-group':openedGroup=openedGroup===el.dataset.group?'':el.dataset.group;if(window.innerWidth>=1024&&window.innerWidth<1280)expanded=true;else if(window.innerWidth>=1280)state.collapsed=false;render();document.querySelector(`[data-group="${el.dataset.group}"]`)?.focus();break;
case'open-project':closeModalIfOpen();navigate('overview',el.dataset.id);break;
case'new-project':if(state.writing.dirty){toast(t('请先保存当前稿件，再创建项目。','Save your manuscript before creating a project.'));break;}newProject();break;
case'choose-project':modal({title:t('切换研究项目','Switch project'),body:state.projects.map(p=>`<div class="artifact-row"><span class="project-monogram ${p.color}">${e(p.mark)}</span><div style="min-width:0;flex:1"><h3 style="overflow-wrap:anywhere">${e(p.name)}</h3><p>${p.type==='sci'?'SCI':t('毕业论文','Thesis')}</p></div>${button(t('打开','Open'),'open-project','secondary','',`data-id="${e(p.id)}"`)}</div>`).join('')});break;
case'toggle-sidebar':if(window.innerWidth<1024)state.mobile=!state.mobile;else if(window.innerWidth<1280)expanded=!expanded;else state.collapsed=!state.collapsed;render();if(state.mobile)document.querySelector('.sidebar button')?.focus();else document.querySelector('[data-act="toggle-sidebar"]')?.focus();break;
case'close-sidebar':state.mobile=false;render();document.querySelector('[data-act="toggle-sidebar"]')?.focus();break;
case'language':state.lang=state.lang==='zh'?'en':'zh';render();break;
case'new-confirm':createProject();break;
case'close-modal':requestCloseModal();break;
case'keep-dialog':dialog.querySelector('.dialog-unsaved')?.remove();dialog.querySelector('input,textarea')?.focus();break;
case'discard-dialog':closeModal();break;
case'account':account();break;
case'account-usage':closeModal();navigate('usage');break;
case'account-login':closeModal();navigate('login');break;
case'switch-role':state.role=state.role==='admin'?'researcher':'admin';closeModal();navigate(state.role==='admin'?'admin':'home');toast(t('已切换预览角色。','Preview role changed.'));break;
case'login':navigate('login');break;
case'enter-preview':navigate('home');break;
case'recovery':modal({title:t('账号恢复 · 界面示例','Account recovery · UI sample'),body:`<p>${t('正式界面将在这里连接现有的账号恢复流程。当前预览不验证账号，也不会发送邮件。','The production UI will connect to the existing recovery flow here. This preview does not validate accounts or send email.')}</p>`,footer:button(t('返回登录页','Back to login'),'close-modal','primary')});break;
case'reset':modal({title:t('重置交互预览','Reset the preview'),body:`<p>${t('将恢复内置合成样例，并清除当前页面中新增的项目和编辑内容。正式数据不受影响。','Restore bundled synthetic samples and clear projects and edits from this page. Production data is unaffected.')}</p>`,footer:button(t('保留当前预览','Keep current preview'),'close-modal')+button(t('重置预览','Reset preview'),'reset-confirm','primary')});break;
case'reset-confirm':location.href='index.html';break;
case'project-search':{state.search=el.value;const caret=el.selectionStart;render();const input=document.getElementById('project-search');input.focus();input.setSelectionRange(caret,caret);break;}
case'project-type':state.projectFilter=el.value;render();break;
case'clear-projects':state.search='';state.projectFilter='all';render();break;
case'project-settings':settings();break;
case'save-settings':{const name=document.getElementById('edit-name'),topic=document.getElementById('edit-topic');if(!name.reportValidity()||!topic.reportValidity()||!name.value.trim()||!topic.value.trim())return;Object.assign(project(),{name:name.value.trim(),topic:topic.value.trim(),output:document.getElementById('edit-output').value});closeModal();render();toast(t('项目设置已保存到预览。','Project settings saved in the preview.'));break;}
case'task-filter':state.taskFilter=el.dataset.value;render();break;
case'task-detail':api.view(`detail-${el.dataset.id}`);break;
case'task-go':closeModal();navigate(el.dataset.page);break;
case'admin-tab':state.adminTab=el.dataset.value;render();break;
case'demo-permissions':modal({title:t('研究者权限 · 合成示例','Researcher permissions · Synthetic sample'),body:`<p>${t('可使用本人项目、资料和成果。管理员运营身份不会自动获得其他账号的研究内容。','Access own projects, materials and outputs. Operations privileges do not grant access to another account’s research content.')}</p>`,footer:button(t('知道了','Got it'),'close-modal','primary')});break;
case'discard-leave':{const destination=pendingNavigation;discardWritingChanges();closeModal();if(destination){if(Number.isInteger(destination.historyIndex))history.go(destination.historyIndex-historyIndex);else navigate(destination.page,destination.id,destination.view,destination.historyMode,destination.item);}break;}
default:console.warn('Unhandled preview action:',act);
}}
function dialogValues(){return JSON.stringify([...dialog.querySelectorAll('input,textarea,select')].map(el=>[el.id||el.name,el.value,el.checked]));}
function requestCloseModal(){if(guardedDialog&&dialogValues()!==dialogSnapshot){if(!dialog.querySelector('.dialog-unsaved')){const box=document.createElement('div');box.className='dialog-unsaved';box.setAttribute('role','alert');box.innerHTML=`<p>${t('有未保存的输入，是否放弃？','Discard the unsaved form input?')}</p><div class="row">${button(t('继续编辑','Keep editing'),'keep-dialog')}${button(t('放弃输入并关闭','Discard and close'),'discard-dialog','danger')}</div>`;dialog.querySelector('.dialog-body').append(box);box.querySelector('button').focus();}return;}closeModal();}
dialog.addEventListener('cancel',event=>{event.preventDefault();requestCloseModal();});
function syncNavigation(){const narrow=window.innerWidth<1024;const sidebarEl=document.getElementById('sidebar'),main=document.querySelector('.main-column');if(sidebarEl)sidebarEl.inert=narrow&&!state.mobile;if(main)main.inert=narrow&&state.mobile;const toggle=document.querySelector('[data-act="toggle-sidebar"]');if(toggle)toggle.setAttribute('aria-expanded',String(narrow?state.mobile:window.innerWidth<1280?expanded:!state.collapsed));}
window.addEventListener('resize',syncNavigation);
function closeModalIfOpen(){if(dialog.open)closeModal();}
document.addEventListener('click',event=>{if(event.target.closest('a[href="#content"]')){event.preventDefault();document.getElementById('content')?.focus();return;}const el=event.target.closest('[data-act]');if(!el||el.disabled)return;action(el.dataset.act,el,event);});
document.addEventListener('change',event=>{const el=event.target.closest('[data-change]');if(el)action(el.dataset.change,el,event);});
document.addEventListener('input',event=>{const el=event.target.closest('[data-input]');if(el)action(el.dataset.input,el,event);});
document.addEventListener('submit',event=>{event.preventDefault();if(event.target.id==='new-project-form')createProject();});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&state.mobile&&!dialog.open){state.mobile=false;render();document.querySelector('[data-act="toggle-sidebar"]')?.focus();}});
window.addEventListener('beforeunload',event=>{if(state.writing.dirty){event.preventDefault();event.returnValue='';}});

function restoreRoute(){
  if(historyRecovery){
    if(history.state?.previewIndex===historyIndex&&location.hash===committedRoute){
      const destination=historyRecovery;historyRecovery=null;confirmNavigation(destination);
    }
    return;
  }
  const incomingIndex=Number.isInteger(history.state?.previewIndex)?history.state.previewIndex:historyIndex+1;
  if(location.hash==='#content'){
    historyIndex=incomingIndex;history.replaceState({previewIndex:historyIndex},'',committedRoute);
    document.getElementById('content')?.focus();return;
  }
  if(location.hash===committedRoute){historyIndex=incomingIndex;return;}
  if(!Number.isInteger(history.state?.previewIndex))history.replaceState({previewIndex:incomingIndex},'',location.hash);
  const route=readRoute();
  if(needsWritingConfirmation(route.page,route.id)){
    historyRecovery={...route,historyIndex:incomingIndex};
    history.go(historyIndex-incomingIndex);return;
  }
  historyIndex=incomingIndex;
  navigate(route.page,route.id,route.view,'replace',route.item);
}
window.addEventListener('popstate',restoreRoute);
window.addEventListener('hashchange',restoreRoute);
const initial=readRoute();
navigate(initial.page,initial.id,initial.view,'replace',initial.item);
