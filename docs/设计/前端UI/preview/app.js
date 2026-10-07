'use strict';

const state = {
  scene: 'workspace', locale: 'zh', projectIndex: 0, projectTab: 'overview',
  step: 'fields', search: '', metric: 'C反应蛋白', group: '治疗分组', unit: 'mg/L',
  selectedFile: '炎症指标研究数据.xlsx', sheet: '研究数据', fieldSaved: true,
  projects: [
    { name: '炎症指标与治疗响应研究', type: 'sci', theme: '探索不同治疗组炎症指标的分布特征与治疗响应。', date: '2026-10-06', status: 'analysis', files: 3 },
    { name: '社区慢病患者的生活质量分析', type: 'thesis', theme: '分析慢病管理与生活质量的相关因素。', date: '2026-10-05', status: 'ready', files: 2 },
    { name: '运动干预与代谢指标', type: 'sci', theme: '观察运动干预前后的代谢指标变化。', date: '2026-10-03', status: 'report', files: 1 },
  ],
};

const content = document.querySelector('#content');
const dialog = document.querySelector('#project-dialog');
const t = (zh, en) => state.locale === 'zh' ? zh : en;
const esc = value => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const icon = (name, cls = '') => `<svg class="icon ${cls}" aria-hidden="true"><use href="#icon-${name}"></use></svg>`;
const project = () => state.projects[state.projectIndex];
const typeLabel = type => type === 'sci' ? t('SCI 科研论文', 'SCI research paper') : t('毕业论文', 'Thesis');
const statusLabel = status => ({ analysis: t('分析进行中', 'Analysis in progress'), ready: t('待开始分析', 'Ready to analyze'), report: t('报告已生成', 'Report available') })[status];
const dateLabel = date => new Intl.DateTimeFormat(state.locale === 'zh' ? 'zh-CN' : 'en', { month: 'short', day: 'numeric' }).format(new Date(date + 'T12:00:00'));
const steps = [
  ['excel', 'Excel 数据', 'Excel data'], ['fields', '字段配置', 'Configure fields'], ['statistics', '描述统计', 'Statistics'],
  ['figure', '箱线图', 'Boxplot'], ['explanation', '分析解释', 'Explanation'], ['report', 'Word 报告', 'Word report'],
];

function renderShell() {
  const inProject = ['project', 'analysis'].includes(state.scene);
  document.documentElement.lang = state.locale === 'zh' ? 'zh-CN' : 'en';
  document.body.classList.toggle('login-mode', state.scene === 'login');
  document.querySelectorAll('[data-scene]').forEach(button => button.classList.toggle('active', button.dataset.scene === state.scene));
  document.querySelector('#sidebar').innerHTML = `
    <button class="brand" data-action="workspace" aria-label="PaperAssist ${t('工作台', 'workspace')}"><span class="brand-mark"><i></i><i></i><i></i></span><span>PaperAssist<span class="brand-caption">${t('让研究有条不紊', 'A clearer path for research')}</span></span></button>
    <button class="button primary sidebar-create" data-action="new-project">${icon('plus')}${t('新建项目', 'New project')}</button>
    <div class="nav-label">${t('工作空间', 'WORKSPACE')}</div>
    <nav class="main-nav" aria-label="${t('工作空间', 'Workspace')}">
      <button class="nav-item ${state.scene === 'workspace' ? 'active' : ''}" data-action="workspace">${icon('grid')}${t('工作台', 'Workspace')}</button>
      <button class="nav-item ${inProject ? 'active' : ''}" data-action="projects">${icon('folder')}${t('我的项目', 'My projects')}<span class="nav-count">${state.projects.length}</span></button>
    </nav>
    ${inProject ? `<div class="project-nav"><div class="nav-label">${t('当前项目', 'CURRENT PROJECT')}</div><div class="sidebar-project-name">${esc(project().name)}</div><nav aria-label="${t('当前项目', 'Current project')}">
      ${[['overview', 'grid', '项目概览', 'Overview'], ['files', 'file', '项目文件', 'Files'], ['analysis', 'chart', '数据分析', 'Data analysis'], ['results', 'folder', '研究成果', 'Results']].map(([tab, glyph, zh, en]) => `<button class="nav-item nested ${(state.scene === 'analysis' ? tab === 'analysis' : state.projectTab === tab) ? 'active' : ''}" data-project-tab="${tab}">${icon(glyph)}${t(zh, en)}</button>`).join('')}
    </nav></div>` : `<div class="sidebar-note"><span class="small-icon violet">${icon('file')}</span><strong>${t('从一份数据开始', 'Start with your data')}</strong><p>${t('在项目中整理文件，让分析与成果始终有据可循。', 'Keep files, analysis and results together in your project.')}</p><button class="text-button" data-action="guide">${t('了解分析流程', 'Explore the workflow')}${icon('arrow')}</button></div>`}
    <div class="sidebar-bottom"><button class="nav-item" data-action="help">${icon('help')}${t('使用帮助', 'Help & guidance')}</button><button class="profile-button" data-action="account"><span class="avatar">林</span><span><strong>${t('林研究员', 'Researcher Lin')}</strong><small>${t('个人工作空间', 'Personal workspace')}</small></span>${icon('down')}</button></div>`;
  document.querySelector('#topbar').innerHTML = `<div class="breadcrumb"><button class="icon-button mobile-menu" data-action="menu" aria-label="${t('打开导航', 'Open navigation')}">${icon('menu')}</button><span>${t('个人工作空间', 'Personal workspace')}</span>${inProject ? `<span class="crumb-separator">/</span><strong>${state.scene === 'analysis' ? t('数据分析', 'Data analysis') : t('我的项目', 'My projects')}</strong>` : '<span class="crumb-separator">/</span><strong>' + t('工作台', 'Workspace') + '</strong>'}</div><div class="topbar-actions"><button class="language-button" data-action="language">${icon('globe')}${state.locale === 'zh' ? '简体中文' : 'English'}${icon('down')}</button><button class="avatar small" data-action="account" aria-label="${t('账号', 'Account')}">林</button></div>`;
  document.querySelector('#app-footer').innerHTML = `<span>PaperAssist</span><span>${t('以清晰的过程，支持严谨的研究。', 'A clear process for thoughtful research.')}</span>`;
}

function render() {
  renderShell();
  content.innerHTML = ({ workspace: renderWorkspace, project: renderProject, analysis: renderAnalysis, login: renderLogin })[state.scene]();
  document.body.classList.remove('menu-open');
}

function renderWorkspace() {
  return `<section class="page workspace-page"><header class="welcome page-header"><div><div class="eyebrow">${t('你的科研工作空间', 'YOUR RESEARCH WORKSPACE')}</div><h1>${t('下午好，林研究员', 'Good afternoon, Researcher Lin')}</h1><p>${t('把研究资料、分析过程和成果，放在同一个地方。', 'Bring your research files, analysis and results together.')}</p></div><button class="button primary" data-action="new-project">${icon('plus')}${t('新建项目', 'New project')}</button></header>
    <section class="continue-banner" aria-labelledby="continue-title"><div class="banner-visual" aria-hidden="true"><div class="paper-shape">${icon('chart')}<i></i><i></i></div><span class="floating-check">${icon('check')}</span></div><div class="continue-copy"><span class="eyebrow">${t('继续上次的研究', 'PICK UP WHERE YOU LEFT OFF')}</span><h2 id="continue-title">${esc(project().name)}</h2><p>${t('字段配置已就绪，下一步查看描述统计与数据分布。', 'Your fields are ready. Explore the statistics and distribution next.')}</p><div class="inline-meta"><span>${icon('file')}${esc(state.selectedFile)}</span><span>${t('最近更新', 'Updated')} ${dateLabel(project().date)}</span></div></div><button class="button secondary" data-action="continue-analysis">${t('继续分析', 'Continue analysis')}${icon('arrow')}</button></section>
    <section class="projects-section" aria-labelledby="recent-title"><div class="section-toolbar"><div><h2 id="recent-title">${t('最近项目', 'Recent projects')}<span class="heading-count">${state.projects.length}</span></h2><p class="section-subtitle">${t('每一个研究，都有清晰的起点与进展。', 'A clear view of every research project.')}</p></div><div class="search-field">${icon('search')}<label class="sr-only" for="project-search">${t('搜索项目', 'Search projects')}</label><input id="project-search" type="search" placeholder="${t('搜索项目名称或主题', 'Search project or topic')}" value="${esc(state.search)}" autocomplete="off"></div></div><div id="project-list">${renderProjectList()}</div></section>
    <section class="quick-start" aria-label="${t('快捷入口', 'Quick actions')}"><button class="quick-action" data-action="new-project"><span class="small-icon violet">${icon('folder')}</span><span><strong>${t('开始一项新研究', 'Start a new research project')}</strong><small>${t('建立项目，整理研究主题与资料', 'Create a home for your topic and files')}</small></span>${icon('arrow')}</button><button class="quick-action" data-action="guide"><span class="small-icon green">${icon('chart')}</span><span><strong>${t('从 Excel 到分析报告', 'From Excel to a research report')}</strong><small>${t('查看完整的数据分析流程', 'Explore the complete analysis workflow')}</small></span>${icon('arrow')}</button></section>
  </section>`;
}

function renderProjectList() {
  const matches = state.projects.map((item, index) => ({ ...item, index })).filter(item => `${item.name} ${item.theme}`.toLowerCase().includes(state.search.toLowerCase()));
  if (!matches.length) return `<div class="empty-state">${icon('search')}<h3>${t('没有找到相关项目', 'No matching projects')}</h3><p>${t('试试其它名称或研究关键词。', 'Try another name or research keyword.')}</p><button class="button secondary" data-action="clear-search">${t('清除搜索', 'Clear search')}</button></div>`;
  return `<div class="table-scroll"><table class="project-table"><caption class="sr-only">${t('最近项目列表', 'Recent project list')}</caption><thead><tr><th>${t('项目名称', 'Project')}</th><th>${t('类型', 'Type')}</th><th>${t('当前进展', 'Progress')}</th><th>${t('最近更新', 'Updated')}</th><th><span class="sr-only">${t('操作', 'Actions')}</span></th></tr></thead><tbody>${matches.map(item => `<tr><td><button class="project-name" data-open-project="${item.index}"><span class="project-symbol ${item.type === 'thesis' ? 'teal' : 'violet'}">${icon(item.type === 'thesis' ? 'file' : 'folder')}</span><span><strong>${esc(item.name)}</strong><small>${esc(item.theme)}</small></span></button></td><td><span class="type-badge">${typeLabel(item.type)}</span></td><td><span class="status-dot ${item.status}"></span>${statusLabel(item.status)}</td><td class="muted">${dateLabel(item.date)}</td><td><button class="icon-button row-open" data-open-project="${item.index}" aria-label="${t('打开', 'Open')} ${esc(item.name)}">${icon('arrow')}</button></td></tr>`).join('')}</tbody></table></div>`;
}

function projectHeader() {
  return `<button class="back-link" data-action="workspace">${icon('back')}${t('返回工作台', 'Back to workspace')}</button><header class="page-header project-header"><div><div class="title-with-badge"><h1>${esc(project().name)}</h1><span class="type-badge">${typeLabel(project().type)}</span></div><p>${esc(project().theme)}</p><div class="inline-meta"><span>${icon('clock')}${t('更新于', 'Updated')} ${dateLabel(project().date)}</span><span>${t('项目输出语言：简体中文', 'Output language: Simplified Chinese')}</span></div></div><button class="button secondary" data-action="edit-project">${icon('edit')}${t('编辑项目', 'Edit project')}</button></header>`;
}

function renderProject() {
  return `<section class="page project-page">${projectHeader()}<nav class="project-tabs" aria-label="${t('项目页面', 'Project sections')}">${[['overview','项目概览','Overview'],['files','项目文件','Files'],['results','研究成果','Results']].map(([key, zh, en]) => `<button class="${state.projectTab === key ? 'active' : ''}" data-project-tab="${key}" aria-current="${state.projectTab === key ? 'page' : 'false'}">${t(zh,en)}</button>`).join('')}</nav>${state.projectTab === 'files' ? renderFiles() : state.projectTab === 'results' ? renderResults() : renderOverview()}</section>`;
}

function renderOverview() {
  if (!project().files) return `<section class="section-block"><div class="empty-state">${icon('folder')}<h2>${t('项目已建立，开始整理研究数据吧', 'Your project is ready for research data')}</h2><p>${t('添加第一份 Excel 文件，即可开始配置字段与分析。', 'Add your first Excel file to begin configuring fields and analyzing data.')}</p><button class="button primary" data-action="sample-upload">${icon('upload')}${t('添加 Excel 文件', 'Add an Excel file')}</button></div></section>`;
  return `<div class="project-summary-strip"><div><span>${t('项目文件', 'Project files')}</span><strong>${project().files}<small>${t('份文件', 'files')}</small></strong></div><div><span>${t('分析任务', 'Analysis tasks')}</span><strong>${t('进行中', 'In progress')}<small>${t('字段配置已完成', 'Fields configured')}</small></strong></div><div><span>${t('最近成果', 'Latest result')}</span><strong>${t('描述统计', 'Statistics')}<small>${t('可查看与继续分析', 'Ready to explore')}</small></strong></div></div>
    <div class="overview-layout"><div><section class="section-block"><div class="section-toolbar"><h2>${t('当前分析', 'Current analysis')}</h2><span class="status-pill amber">${t('进行中', 'In progress')}</span></div><div class="analysis-current"><span class="small-icon violet">${icon('chart')}</span><div><h3>${t('描述统计与箱线图', 'Descriptive statistics & boxplot')}</h3><p>${esc(state.selectedFile)}</p><div class="inline-meta"><span>${t('工作表：研究数据', 'Worksheet: Research data')}</span><span>${t('数值字段：C反应蛋白', 'Measure: C-reactive protein')}</span></div></div></div><div class="mini-flow"><span class="done">${icon('check')}${t('数据已就绪', 'Data ready')}</span><span class="done">${icon('check')}${t('字段已配置', 'Fields configured')}</span><span>${icon('chart')}${t('查看统计结果', 'Explore statistics')}</span></div><div class="section-bottom"><span class="muted">${t('保留来源与分析过程，随时继续。', 'Your source data and progress stay together.')}</span><button class="button primary" data-action="continue-analysis">${t('进入数据分析', 'Open analysis')}${icon('arrow')}</button></div></section>
    <section class="section-block"><div class="section-toolbar"><h2>${t('最近任务', 'Recent tasks')}</h2><button class="text-button" data-action="tasks">${t('查看全部', 'View all')}${icon('arrow')}</button></div><ul class="activity-list"><li><span class="activity-icon green">${icon('check')}</span><div><strong>${t('描述统计已完成', 'Statistics completed')}</strong><p>${t('总体与分组结果已保存，可继续查看数据分布。', 'Overall and group summaries are ready to explore.')}</p></div><time>${dateLabel('2026-10-06')}</time></li><li><span class="activity-icon violet">${icon('file')}</span><div><strong>${t('研究数据已上传', 'Research data uploaded')}</strong><p>${esc(state.selectedFile)}</p></div><time>${dateLabel('2026-10-06')}</time></li></ul></section></div>
    <aside class="overview-aside"><h3>${t('项目资料', 'Project resources')}</h3><button class="resource-link" data-project-tab="files">${icon('file')}<span>${t('查看全部项目文件', 'View all project files')}<small>${t('原始数据、补充资料', 'Source data and supporting files')}</small></span>${icon('arrow')}</button><button class="resource-link" data-project-tab="results">${icon('folder')}<span>${t('查看研究成果', 'View research results')}<small>${t('统计结果、图表与报告', 'Statistics, figures and reports')}</small></span>${icon('arrow')}</button><div class="quiet-note">${icon('shield')}<p>${t('研究内容按项目独立整理。生成的图表与解释，请结合专业判断核对。', 'Keep research organized by project. Review figures and explanations with your own expertise.')}</p></div></aside></div>`;
}

function renderFiles() {
  if (!project().files) return `<section class="section-block"><div class="empty-state">${icon('file')}<h2>${t('还没有项目文件', 'No project files yet')}</h2><p>${t('先添加一份研究数据。', 'Start by adding research data.')}</p><button class="button primary" data-action="sample-upload">${icon('upload')}${t('添加 Excel 文件', 'Add an Excel file')}</button></div></section>`;
  const files = [[state.selectedFile, '28 KB', '2026-10-06'], ['研究对象基线资料.xlsx', '19 KB', '2026-10-05'], ['随访记录.xlsx', '16 KB', '2026-10-03']];
  return `<section class="section-block files-section"><div class="section-toolbar"><div><h2>${t('项目文件', 'Project files')}</h2><p class="section-subtitle">${t('原始数据集中保存，分析时可随时选择。', 'Keep source files together and select them for analysis.')}</p></div><button class="button primary" data-action="sample-upload">${icon('upload')}${t('添加 Excel 文件', 'Add an Excel file')}</button></div><div class="table-scroll"><table><thead><tr><th>${t('文件名称', 'Filename')}</th><th>${t('大小', 'Size')}</th><th>${t('状态', 'Status')}</th><th>${t('上传时间', 'Uploaded')}</th><th>${t('操作', 'Actions')}</th></tr></thead><tbody>${files.slice(0, Math.max(1, project().files)).map(([name,size,date]) => `<tr><td><span class="file-cell">${icon('file')}<strong>${esc(name)}</strong></span></td><td class="muted">${size}</td><td><span class="status-pill green">${t('解析完成', 'Ready')}</span></td><td class="muted">${dateLabel(date)}</td><td><div class="table-actions"><button class="text-button" data-action="preview-data">${t('预览', 'Preview')}</button><button class="icon-button" data-action="download" aria-label="${t('下载', 'Download')} ${esc(name)}">${icon('download')}</button></div></td></tr>`).join('')}</tbody></table></div></section>`;
}

function renderResults() {
  if (!project().files) return `<section class="section-block"><div class="empty-state">${icon('chart')}<h2>${t('这里将汇集你的研究成果', 'Your research results will appear here')}</h2><p>${t('完成数据分析后，可在这里查看统计、图表与报告。', 'After analysis, find your statistics, figures and reports here.')}</p><button class="button secondary" data-project-tab="files">${t('查看项目文件', 'View project files')}${icon('arrow')}</button></div></section>`;
  return `<section class="section-block"><div class="section-toolbar"><div><h2>${t('研究成果', 'Research results')}</h2><p class="section-subtitle">${t('与本项目相关的分析结果、图表和报告。', 'Analysis, figures and reports connected to this project.')}</p></div><button class="button secondary" data-action="continue-analysis">${t('继续分析', 'Continue analysis')}${icon('arrow')}</button></div><div class="result-list">${[['chart','描述统计结果','Descriptive statistics','总体与治疗分组的统计摘要','Overall and treatment-group summaries','statistics'],['chart','C反应蛋白分布箱线图','C-reactive protein boxplot','PNG 图表 · 示例','PNG figure · sample','figure'],['file','炎症指标分析报告','Inflammatory marker report','Word 报告 · 示例','Word report · sample','report']].map(([glyph,zh,en,subZh,subEn,step]) => `<article class="result-row"><span class="small-icon ${step === 'report' ? 'blue' : 'violet'}">${icon(glyph)}</span><div><h3>${t(zh,en)}</h3><p>${t(subZh,subEn)}</p><small>${t('来源：炎症指标研究数据.xlsx · 研究数据', 'Source: 炎症指标研究数据.xlsx · 研究数据')}</small></div><button class="text-button" data-result-step="${step}">${t('查看成果', 'View result')}${icon('arrow')}</button></article>`).join('')}</div></section>`;
}

function renderAnalysis() {
  const current = steps.findIndex(step => step[0] === state.step);
  return `<section class="page analysis-page"><button class="back-link" data-action="project-overview">${icon('back')}${t('返回项目概览', 'Back to project overview')}</button><header class="page-header"><div><div class="eyebrow">${esc(project().name)}</div><h1>${t('数据分析', 'Data analysis')}</h1><p>${t('从原始数据到可解释的结果，每一步都清晰可见。', 'A clear path from your source data to results you can explain.')}</p></div><span class="subtle-badge">${t('描述统计与箱线图', 'Descriptive statistics & boxplot')}</span></header><nav class="workflow-steps" aria-label="${t('分析流程', 'Analysis workflow')}">${steps.map(([key,zh,en],i) => `<button class="workflow-step ${key === state.step ? 'active' : ''} ${i < current ? 'complete' : ''}" data-step="${key}" aria-current="${key === state.step ? 'step' : 'false'}"><span class="step-dot">${icon(i < current ? 'check' : key === 'excel' || key === 'report' ? 'file' : key === 'explanation' ? 'spark' : 'chart')}</span><span><strong>${t(zh,en)}</strong><small>${key === state.step ? t('当前步骤', 'Current step') : i < current ? t('已查看', 'Viewed') : t('查看示例', 'Explore sample')}</small></span></button>`).join('')}</nav><div class="analysis-source"><span>${icon('file')}${esc(state.selectedFile)}</span><span>${t('工作表', 'Worksheet')}<strong>${esc(state.sheet)}</strong></span><button class="text-button" data-step="excel">${t('查看数据', 'View data')}</button></div>${({excel:renderExcel,fields:renderFields,statistics:renderStatistics,figure:renderFigure,explanation:renderExplanation,report:renderReport})[state.step]()}</section>`;
}

function dataTable(compact = false) {
  const rows = [['对照组','8.2','46','女'],['对照组','7.6','52','男'],['治疗组','4.1','48','女'],['治疗组','5.3','55','男']];
  return `<div class="table-scroll"><table class="data-table"><caption>${t('示例数据预览', 'Sample data preview')}${compact ? '' : t(' · 展示部分记录', ' · Selected rows')}</caption><thead><tr>${['治疗分组','C反应蛋白','年龄','性别'].map(x => `<th>${x}${x === 'C反应蛋白' ? '<span class="unit-label">mg/L</span>' : ''}</th>`).join('')}</tr></thead><tbody>${rows.map(row => '<tr>'+row.map(value=>`<td>${value}</td>`).join('')+'</tr>').join('')}</tbody></table></div>`;
}

function renderExcel() {
  return `<section class="section-block"><div class="section-toolbar"><div><h2>${t('选择研究数据', 'Select your research data')}</h2><p class="section-subtitle">${t('选择项目中已保存的文件，确认工作表内容。', 'Choose a saved file and review its worksheet.')}</p></div><button class="button secondary" data-action="sample-upload">${icon('upload')}${t('添加 Excel', 'Add Excel')}</button></div><div class="form-grid source-fields"><label>${t('分析文件', 'Analysis file')}<select id="analysis-file"><option>${esc(state.selectedFile)}</option><option>研究对象基线资料.xlsx</option></select></label><label>${t('工作表', 'Worksheet')}<select id="analysis-sheet"><option>研究数据</option><option>基线资料</option></select></label></div>${dataTable()}<div class="section-bottom"><span class="inline-note">${icon('check')}${t('示例文件已解析，可继续配置字段。', 'The sample file is ready for field configuration.')}</span><button class="button primary" data-step="fields">${t('配置分析字段', 'Configure fields')}${icon('arrow')}</button></div></section>`;
}

function renderFields() {
  return `<div class="analysis-layout"><section class="section-block field-panel"><div class="section-toolbar"><div><h2>${t('配置分析字段', 'Configure analysis fields')}</h2><p class="section-subtitle">${t('选择需要分析的数值，以及用于比较的分组。', 'Choose a measure and an optional comparison group.')}</p></div><span class="subtle-badge">${t('当前草稿', 'Current draft')}</span></div><div class="form-grid"><label>${t('数值字段', 'Numeric measure')}<select id="metric"><option ${state.metric==='C反应蛋白'?'selected':''}>C反应蛋白</option><option ${state.metric==='年龄'?'selected':''}>年龄</option></select><small>${t('选择包含连续数值的列。', 'Choose a column with continuous numeric data.')}</small></label><label>${t('分组字段', 'Group by')}<span class="optional">${t('可选', 'Optional')}</span><select id="group"><option ${state.group==='治疗分组'?'selected':''}>治疗分组</option><option ${state.group==='性别'?'selected':''}>性别</option><option value="" ${state.group===''?'selected':''}>${t('不分组', 'No grouping')}</option></select><small>${t('按组查看分布，更容易发现差异。', 'Compare the distribution across groups.')}</small></label><label>${t('数值单位', 'Unit')}<span class="optional">${t('可选', 'Optional')}</span><input id="unit" value="${esc(state.unit)}" placeholder="${t('例如 mg/L', 'e.g. mg/L')}" maxlength="30"><small>${t('用于图表标注与分析报告。', 'Shown in figures and the report.')}</small></label><label>${t('缺失值处理', 'Missing values')}<select id="missing-policy"><option>${t('排除所选字段缺失的记录', 'Exclude records missing selected fields')}</option></select><small>${t('原始文件始终保持不变。', 'Your original file stays unchanged.')}</small></label></div><div class="preview-divider"><h3>${t('确认数据内容', 'Check your data')}</h3><span>${t('合成数据示例', 'Synthetic sample data')}</span></div>${dataTable(true)}<div class="section-bottom"><span class="save-state" id="save-state">${icon('check')}${state.fieldSaved?t('配置已就绪','Configuration ready'):t('有未保存的修改','Unsaved changes')}</span><button class="button primary" data-action="save-fields">${t('保存并查看统计', 'Save & view statistics')}${icon('arrow')}</button></div></section><aside class="analysis-aside"><div class="check-heading"><span class="activity-icon green">${icon('check')}</span><div><h3>${t('数据准备就绪', 'Your data is ready')}</h3><p>${t('可以继续描述统计', 'Ready for descriptive statistics')}</p></div></div><dl class="data-check"><div><dt>${t('总记录', 'Total records')}</dt><dd>48</dd></div><div><dt>${t('有效记录', 'Valid records')}</dt><dd>46</dd></div><div><dt>${t('缺失记录', 'Missing records')}</dt><dd>2</dd></div><div><dt>${t('有效分组', 'Valid groups')}</dt><dd>${state.group?2:1}</dd></div></dl><div class="quiet-note">${icon('help')}<p>${t('这里的数值用于演示界面。正式分析中，将以所选字段的数据检查结果为准。', 'These values illustrate the design. Actual analysis uses checks on your selected fields.')}</p></div><div class="analysis-tip"><h4>${t('选择字段的小提示', 'Choosing your fields')}</h4><p>${t('数值字段通常是检测指标、测量结果或评分。分组字段通常是治疗方案、样本类别等。', 'Measures are usually lab results, measurements or scores. Groups are often treatment types or sample categories.')}</p></div></aside></div>`;
}

function renderStatistics() {
  const rows = [['总体','46','6.84','2.10','6.50','3.80','11.20'],['对照组','23','8.12','1.74','7.90','5.20','11.20'],['治疗组','23','5.56','1.61','5.30','3.80','9.10']];
  return `<section class="section-block"><div class="section-toolbar"><div><h2>${t('描述统计结果', 'Descriptive statistics')}</h2><p class="section-subtitle">${esc(state.metric)}${state.unit?' · '+esc(state.unit):''} · ${t('示例结果', 'Sample results')}</p></div><span class="status-pill green">${t('示例已就绪', 'Sample ready')}</span></div><div class="statistics-highlights"><div><span>${t('有效样本', 'Valid samples')}</span><strong>46<small>${t('份', 'records')}</small></strong></div><div><span>${t('均值', 'Mean')}</span><strong>6.84<small>${esc(state.unit)}</small></strong></div><div><span>${t('中位数', 'Median')}</span><strong>6.50<small>${esc(state.unit)}</small></strong></div></div><div class="table-scroll"><table class="statistics-table"><caption class="sr-only">${t('合成描述统计示例', 'Synthetic statistics example')}</caption><thead><tr>${['分组','样本量','均值','标准差','中位数','最小值','最大值'].map((s,i)=>`<th>${t(s,['Group','Count','Mean','Std. dev.','Median','Minimum','Maximum'][i])}</th>`).join('')}</tr></thead><tbody>${rows.slice(0,state.group?3:1).map(row=>`<tr>${row.map((cell,i)=>i?`<td>${cell}</td>`:`<th scope="row">${cell}</th>`).join('')}</tr>`).join('')}</tbody></table></div><div class="notice-line">${icon('help')}<p>${t('统计与图表为合成示例。', 'Statistics and figures are synthetic examples.')}</p></div><div class="section-bottom"><button class="button secondary" data-step="fields">${icon('back')}${t('调整字段', 'Adjust fields')}</button><button class="button primary" data-step="figure">${t('查看箱线图示例', 'View sample boxplot')}${icon('arrow')}</button></div></section>`;
}

function boxplot() {
  return `<svg class="boxplot" viewBox="0 0 740 340" role="img" aria-label="${t('合成箱线图示例：对照组与治疗组的分布', 'Synthetic boxplot showing control and treatment group distributions')}"><g class="chart-grid" stroke="#e9e6ee" stroke-width="1"><path d="M88 58h580M88 110h580M88 162h580M88 214h580M88 266h580"/></g><g class="chart-axis" fill="#80798d" font-size="12" font-family="sans-serif"><text x="60" y="62">12</text><text x="60" y="114">9</text><text x="60" y="166">6</text><text x="60" y="218">3</text><text x="60" y="270">0</text><text x="250" y="299" text-anchor="middle">${state.group==='性别'?'女':'对照组'}</text><text x="502" y="299" text-anchor="middle">${state.group==='性别'?'男':'治疗组'}</text><text x="378" y="329" text-anchor="middle">${esc(state.group||t('总体','Overall'))}</text><text transform="translate(23 168) rotate(-90)" text-anchor="middle">${esc(state.metric)} ${esc(state.unit)}</text></g><g stroke="#7661b6" stroke-width="2"><path d="M250 73v100M226 73h48M226 173h48"/><rect x="203" y="112" width="94" height="45" rx="3" fill="#e6defa"/><path d="M203 130h94" stroke="#5b3cc4" stroke-width="3"/></g><g stroke="#66958e" stroke-width="2"><path d="M502 126v74M478 126h48M478 200h48"/><rect x="455" y="155" width="94" height="30" rx="3" fill="#dcedea"/><path d="M455 174h94" stroke="#487d73" stroke-width="3"/></g><circle cx="504" cy="107" r="4" fill="#fff" stroke="#66958e" stroke-width="1.5"/></svg>`;
}

function renderFigure() {
  return `<section class="section-block figure-panel"><div class="section-toolbar"><div><h2>${t('不同治疗分组的指标分布', 'Distribution by treatment group')}</h2><p class="section-subtitle">${t('箱线图 · 合成数据示例', 'Boxplot · synthetic sample data')}</p></div><button class="button secondary" data-action="download">${icon('download')}${t('下载图表', 'Download figure')}</button></div><figure>${boxplot()}<figcaption>${t('图示用于展示中位数、四分位区间与分布范围。这里的分组和数值仅作设计演示。', 'The figure illustrates medians, quartiles and distribution ranges. Groups and values are for design demonstration only.')}</figcaption></figure><div class="section-bottom"><button class="button secondary" data-step="statistics">${icon('back')}${t('返回统计结果', 'Back to statistics')}</button><button class="button primary" data-step="explanation">${t('查看分析解释', 'Read explanation')}${icon('arrow')}</button></div></section>`;
}

function renderExplanation() {
  return `<section class="section-block explanation-panel"><div class="section-toolbar"><div><h2>${t('读懂分析结果', 'Understand the results')}</h2><p class="section-subtitle">${t('分析解释 · 内容示例', 'Analysis explanation · sample content')}</p></div><span class="subtle-badge">${t('请结合专业判断', 'Review with your expertise')}</span></div><article class="reading-content"><h3>${t('本次分析关注什么', 'What this analysis explores')}</h3><p>${t('通过描述统计与箱线图，观察不同治疗组中 C 反应蛋白的分布特征，帮助形成对数据的初步认识。', 'Descriptive statistics and a boxplot show the distribution of C-reactive protein across treatment groups, helping build an initial understanding of the data.')}</p><h3>${t('如何阅读结果', 'How to read the results')}</h3><p>${t('阅读箱线图时，可结合中位数、箱体范围及离群点观察分布。分组之间的位置差异只描述本次示例数据，并不代表统计显著性或治疗效果。', 'Consider medians, box ranges and outliers together. Differences between groups describe this sample only; they do not establish statistical significance or treatment effects.')}</p><blockquote>${t('先理解数据分布，再根据研究设计选择后续分析方法。', 'Understand the distribution before selecting the next analysis method for your study.')}</blockquote><h3>${t('需要注意的范围', 'What to keep in mind')}</h3><p>${t('本页面为合成内容示例，不是对真实研究数据的分析。正式报告需要结合研究设计、样本来源和专业知识进行核对。', 'This page contains synthetic sample content, not an analysis of actual research data. Review a real report against the study design, sample source and subject expertise.')}</p></article><div class="section-bottom"><button class="button secondary" data-step="figure">${icon('back')}${t('查看图表', 'View figure')}</button><button class="button primary" data-step="report">${t('查看 Word 报告', 'View Word report')}${icon('arrow')}</button></div></section>`;
}

function renderReport() {
  return `<section class="section-block report-panel"><div class="report-illustration" aria-hidden="true"><span class="report-paper">${icon('file')}<i></i><i></i><i></i></span><span class="file-format">DOCX</span></div><div class="report-copy"><span class="status-pill green">${t('报告示例', 'Sample report')}</span><h2>${t('让分析成果清晰呈现', 'Bring your analysis together')}</h2><p>${t('数据说明、统计结果、图表和解释，整理成一份可编辑的 Word 文档。', 'Data context, statistics, figures and explanations in one editable Word document.')}</p><ul class="report-includes">${['来源文件与字段说明','总体和分组描述统计','箱线图与图注','分析解释与阅读提示'].map((s,i)=>`<li>${icon('check')}${t(s,['Source files and selected fields','Overall and grouped statistics','Boxplot and figure caption','Explanation and reading notes'][i])}</li>`).join('')}</ul><div class="report-actions"><button class="button primary" data-action="download">${icon('download')}${t('下载 Word 报告', 'Download Word report')}</button><button class="text-button" data-project-tab="results">${t('返回研究成果', 'Back to results')}${icon('arrow')}</button></div><small class="muted">${t('设计稿仅展示报告出口，不会生成或下载真实文件。', 'This prototype shows the report action without generating or downloading a file.')}</small></div></section>`;
}

function renderLogin() {
  return `<section class="login-page"><aside class="login-story"><div class="brand"><span class="brand-mark"><i></i><i></i><i></i></span><span>PaperAssist</span></div><div class="login-story-copy"><span class="eyebrow">${t('专注研究的每一步', 'FOCUS ON EVERY STEP OF RESEARCH')}</span><h1>${t('让数据与思考，<br>有序地走向成果。', 'From data and ideas<br>to clearer results.')}</h1><p>${t('在一个清晰的工作空间，管理项目、分析数据，整理属于你的研究成果。', 'A thoughtful workspace to manage projects, analyze data and bring your research together.')}</p><div class="login-art" aria-hidden="true"><div class="art-sheet sheet-back"><i></i><i></i><i></i></div><div class="art-sheet sheet-front"><span class="art-label">RESEARCH OVERVIEW</span><div class="art-chart"><b></b><b></b><b></b><b></b><b></b></div><i></i><i></i></div><span class="art-check">${icon('check')}</span></div></div><div class="login-story-footer">${t('清晰的过程，可信的依据。', 'Clear process. Traceable evidence.')}</div></aside><div class="login-form-area"><button class="language-button login-language" data-action="language">${icon('globe')}${state.locale === 'zh' ? '简体中文' : 'English'}${icon('down')}</button><div class="login-form-wrap"><span class="welcome-label">${t('欢迎回来', 'WELCOME BACK')}</span><h2>${t('登录你的工作空间', 'Sign in to your workspace')}</h2><p>${t('继续推进你的研究。', 'Continue where your research left off.')}</p><form id="login-form"><label for="login-email">${t('邮箱', 'Email')}</label><input id="login-email" name="email" type="email" autocomplete="off" placeholder="researcher@example.com" required><div class="password-label"><label for="login-password">${t('密码', 'Password')}</label><button type="button" class="text-button" data-action="forgot-password">${t('忘记密码？', 'Forgot password?')}</button></div><input id="login-password" name="password" type="password" autocomplete="off" placeholder="${t('请输入密码', 'Enter your password')}" required><button type="submit" class="button primary login-submit">${t('登录', 'Sign in')}${icon('arrow')}</button></form><div class="login-demo-note">${t('这是界面设计稿，请勿输入真实密码。', 'This is a design prototype. Do not enter a real password.')}</div><button class="demo-entry text-button" data-action="demo-login">${t('直接体验示例工作台', 'Explore the sample workspace')}${icon('arrow')}</button><p class="login-contact">${t('需要开通账号？请联系项目管理员。', 'Need an account? Contact your project administrator.')}</p></div><span class="login-copyright">PaperAssist · ${t('科研论文辅助系统', 'Research workspace')}</span></div></section>`;
}

function openProjectDialog(edit = false) {
  const item = edit ? project() : {name:'',theme:'',type:''};
  dialog.innerHTML = `<form id="project-form" data-edit="${edit}"><div class="dialog-header"><div><span class="eyebrow">${t('为研究建立一个起点', 'A HOME FOR YOUR RESEARCH')}</span><h2 id="dialog-title">${edit?t('编辑项目','Edit project'):t('新建研究项目','Create a research project')}</h2></div><button type="button" class="icon-button" data-action="close-dialog" aria-label="${t('关闭','Close')}">${icon('close')}</button></div><label for="project-name">${t('项目名称','Project name')}</label><input id="project-name" name="projectName" required maxlength="80" value="${esc(item.name)}" placeholder="${t('给这项研究起一个清晰的名字','Give your research a clear name')}"><label for="project-type">${t('项目类型','Project type')}</label><select id="project-type" name="projectType" required ${edit?'disabled':''}><option value="" disabled ${!item.type ? 'selected' : ''}>${t('选择项目类型', 'Choose a project type')}</option><option value="sci" ${item.type==='sci'?'selected':''}>${t('SCI 科研论文','SCI research paper')}</option><option value="thesis" ${item.type==='thesis'?'selected':''}>${t('毕业论文','Thesis')}</option></select><label for="project-theme">${t('研究主题','Research topic')}</label><textarea id="project-theme" name="projectTheme" required rows="3" maxlength="240" placeholder="${t('简要描述研究目标或关注的问题','Briefly describe your research question')}">${esc(item.theme)}</textarea><p class="dialog-note">${t('本设计稿仅在当前页面保留示例项目，刷新后恢复。','Sample projects stay on this page only and reset on refresh.')}</p><div class="dialog-actions"><button type="button" class="button secondary" data-action="close-dialog">${t('取消','Cancel')}</button><button type="submit" class="button primary">${edit?t('保存修改','Save changes'):t('创建项目','Create project')}${icon('arrow')}</button></div></form>`;
  dialog.showModal();
  dialog.querySelector('input').focus();
}

let toastTimer;
function notify(message) {
  const toast = document.querySelector('#toast');
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 4500);
}

function navigate(scene, options = {}) {
  if (state.scene === 'login') document.querySelector('#login-form')?.reset();
  Object.assign(state, {scene}, options);
  render();
  content.focus({preventScroll:true});
  window.scrollTo({top:0,behavior:'instant'});
}

document.addEventListener('click', event => {
  const button = event.target.closest('button, [data-action="close-menu"]');
  if (!button) return;
  if (button.dataset.scene) return navigate(button.dataset.scene, button.dataset.scene === 'project' ? {projectTab:'overview'} : {});
  if (button.dataset.openProject !== undefined) return navigate('project', {projectIndex:Number(button.dataset.openProject),projectTab:'overview'});
  if (button.dataset.projectTab) return button.dataset.projectTab === 'analysis' ? navigate('analysis') : navigate('project', {projectTab:button.dataset.projectTab});
  if (button.dataset.step) return navigate('analysis', {step:button.dataset.step});
  if (button.dataset.resultStep) return navigate('analysis', {step:button.dataset.resultStep});
  const action = button.dataset.action;
  if (action === 'workspace') navigate('workspace');
  else if (action === 'projects' || action === 'project-overview') navigate('project',{projectTab:'overview'});
  else if (action === 'new-project') openProjectDialog();
  else if (action === 'edit-project') openProjectDialog(true);
  else if (action === 'close-dialog') dialog.close();
  else if (action === 'continue-analysis') navigate('analysis',{step:'fields'});
  else if (action === 'guide') navigate('analysis',{step:'excel'});
  else if (action === 'preview-data') navigate('analysis',{step:'excel'});
  else if (action === 'language') {state.locale = state.locale === 'zh'?'en':'zh';render();}
  else if (action === 'save-fields') {state.fieldSaved=true;navigate('analysis',{step:'statistics'});notify(t('示例配置已保存，可查看统计布局。','Sample configuration saved. Explore the statistics layout.'));}
  else if (action === 'download') notify(t('这是 UI 设计稿，下载操作仅作演示，不生成真实文件。','This UI prototype demonstrates the download action without creating a file.'));
  else if (action === 'sample-upload') notify(t('这里将打开 Excel 上传。设计稿使用合成文件，可点击“预览”查看。','Excel upload will open here. This prototype uses sample files; select Preview to explore.'));
  else if (action === 'help') notify(t('从新建项目开始，添加 Excel 后即可配置字段、查看统计与报告。','Create a project, add Excel data, then explore fields, statistics and reports.'));
  else if (action === 'tasks') notify(t('本示例展示最近的两项任务。','This example shows the two most recent tasks.'));
  else if (action === 'account') navigate('login');
  else if (action === 'demo-login') navigate('workspace');
  else if (action === 'forgot-password') notify(t('正式界面可输入管理员签发的恢复码，重新设置密码。','The full interface lets you reset your password with a recovery code from an administrator.'));
  else if (action === 'menu') document.body.classList.add('menu-open');
  else if (action === 'close-menu') document.body.classList.remove('menu-open');
  else if (action === 'clear-search') {state.search='';render();document.querySelector('#project-search')?.focus();}
});

document.addEventListener('input', event => {
  if (event.target.id === 'project-search') {state.search=event.target.value;document.querySelector('#project-list').innerHTML=renderProjectList();}
  if (event.target.id === 'unit') {state.unit=event.target.value;markDraft();}
});
document.addEventListener('change', event => {
  if (['metric','group'].includes(event.target.id)) {state[event.target.id]=event.target.value;markDraft();}
  if (event.target.id === 'analysis-file') {state.selectedFile=event.target.value;notify(t('已选择示例文件，当前预览为合成数据。','Sample file selected. The preview uses synthetic data.'));}
  if (event.target.id === 'analysis-sheet') {state.sheet=event.target.value;notify(t('已切换示例工作表。','Sample worksheet changed.'));}
});
function markDraft(){state.fieldSaved=false;const label=document.querySelector('#save-state');if(label)label.innerHTML=icon('edit')+t('有未保存的修改','Unsaved changes');}

document.addEventListener('submit', event => {
  event.preventDefault();
  if (event.target.id === 'login-form') {event.target.reset();navigate('workspace');notify(t('已进入示例工作台；未发送或保存登录信息。','Sample workspace opened. No sign-in details were sent or saved.'));}
  if (event.target.id === 'project-form') {
    const form = event.target;
    const name = form.elements.projectName.value.trim();
    if (!name) {form.elements.projectName.setCustomValidity(t('请输入项目名称','Enter a project name'));form.elements.projectName.reportValidity();form.elements.projectName.addEventListener('input',()=>form.elements.projectName.setCustomValidity(''),{once:true});return;}
    const theme=form.elements.projectTheme.value.trim();
    if (!theme) {form.elements.projectTheme.setCustomValidity(t('请输入研究主题','Enter a research topic'));form.elements.projectTheme.reportValidity();form.elements.projectTheme.addEventListener('input',()=>form.elements.projectTheme.setCustomValidity(''),{once:true});return;}
    if (form.dataset.edit === 'true') Object.assign(project(),{name,theme});
    else {state.projects.unshift({name,theme,type:form.elements.projectType.value,date:'2026-10-07',status:'ready',files:0});state.projectIndex=0;}
    dialog.close();navigate('project',{projectTab:'overview'});notify(t('示例项目已保存，仅保留在当前页面。','Sample project saved for this page only.'));
  }
});
dialog.addEventListener('click', event => {if(event.target===dialog){const bounds=dialog.getBoundingClientRect();if(event.clientX<bounds.left||event.clientX>bounds.right||event.clientY<bounds.top||event.clientY>bounds.bottom)dialog.close();}});
document.addEventListener('keydown', event => {if(event.key==='Escape')document.body.classList.remove('menu-open');});
render();
