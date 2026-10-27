import {state,project,t,e,icon,button,badge,head,card} from './shared.js';

const chapters = [['abstract','摘要','Abstract'],['intro','引言','Introduction'],['methods','材料与方法','Methods'],['results','研究结果','Results'],['discussion','讨论','Discussion']];
const initial = {
  abstract:'本研究围绕不同干预条件下的代谢表型变化，整理实验分组、观察指标与分析路径。本文为合成内容预览，尚未使用真实研究数据。',
  intro:'代谢表型能够为理解干预响应提供研究线索。本研究关注实验条件、样本特征与指标变化之间的关系，并保留证据来源与不确定性。',
  methods:'根据预先定义的实验分组整理样本信息。正式统计分析前，需要核对缺失值、测量单位、样本独立性和分析假设。此处不提供真实检验结果。',
  results:'合成样例展示结果的组织方式：先描述样本与数据质量，再依次报告主要指标和探索性结果。效应量、置信区间和具体数值等待真实分析后补充。',
  discussion:'研究解释应结合设计局限、样本代表性与潜在混杂因素。当前段落用于演示编辑体验，不构成经过核验的科研结论。',
};
const reviews = [
  {id:'R1-01',title:'补充样本纳入与排除标准',original:'样本按实验分组纳入分析。',after:'样本按预先定义的分组整理；纳入与排除标准、排除数量和原因待研究者根据原始记录补充。',plan:'核对原始实验记录，补充纳入与排除标准；不从现有摘要推断缺失信息。'},
  {id:'R1-02',title:'讨论观察结果的适用边界',original:'该干预能够改善代谢表型。',after:'当前观察结果的解释受到研究设计和样本范围限制；在完成真实分析与核验前，不作确定的干预效果判断。',plan:'收窄因果措辞，结合研究设计补充局限，并关联真实分析依据。'},
];
const manuscriptViews = [['text','正文','Text'],['sources','依据','Sources'],['checks','检查','Checks'],['versions','版本','Versions']];
const reviewViews = [['comment','意见','Comment'],['plan','处理计划','Plan'],['compare','修改对照','Compare'],['response','回复','Response']];
const guidelineViews = [['detail','概况','Overview'],['rules','规则详情','Rules'],['requirements','待确认事项','To confirm']];

function manuscriptDirty(doc) { return Object.keys(doc.draft).some(key => doc.draft[key] !== doc.saved[key]); }
function planDirty(w) { return w.planDraft[w.review] !== w.planSaved[w.review]; }
function computeDirty() {
  const root = state.writing;
  root.dirty = Object.values(root.docs ?? {}).some(manuscriptDirty)
    || Object.values(root.projects ?? {}).some(bucket => Object.keys(bucket.planDraft ?? {}).some(key => bucket.planDraft[key] !== bucket.planSaved[key]));
  return root.dirty;
}
function ws() {
  const root = state.writing;
  root.docs ??= {};
  root.projects ??= {};
  const id = project().id;
  root.docs[id] ??= {saved:{...initial},draft:{...initial}};
  if (!root.projects[id]) {
    const plans = Object.fromEntries(reviews.map((review,index) => [index,review.plan]));
    root.projects[id] = {chapter:'abstract',editing:false,review:0,compareSide:'proposed',accepted:{},journal:0,school:0,links:{},planSaved:{...plans},planDraft:{...plans}};
  }
  root.activeProject = id;
  computeDirty();
  return root.projects[id];
}
export function discardWritingChanges() {
  const root = state.writing;
  for (const doc of Object.values(root.docs ?? {})) doc.draft = {...doc.saved};
  for (const bucket of Object.values(root.projects ?? {})) {
    bucket.planDraft = {...bucket.planSaved};
    bucket.editing = false;
  }
  computeDirty();
}
function currentView(options,fallback) { return options.some(([value]) => value === state.view) ? state.view : fallback; }
function switcher(options,current,label,action='w-view') {
  return `<nav class="view-switcher" aria-label="${e(label)}">${options.map(([value,zh,en]) => `<button type="button" class="view-button ${value === current ? 'active' : ''}" data-act="${action}" data-value="${value}" aria-pressed="${value === current}">${e(t(zh,en))}</button>`).join('')}</nav>`;
}
function viewButton(label,view,variant='secondary',iconName='arrow') { return button(label,'w-view',variant,iconName,`data-value="${view}"`); }
function saveStatus(doc) { return manuscriptDirty(doc) ? t('未保存修改','Unsaved changes') : t('已保存至预览内存','Saved in preview memory'); }
function planStatus(w) { return planDirty(w) ? t('计划有未保存修改','Unsaved plan changes') : t('计划已保存至预览内存','Plan saved in preview memory'); }
function chapterPicker(w) {
  return `<div class="w-context-bar"><label class="w-picker" for="w-chapter">${e(t('当前章节','Section'))}<select id="w-chapter" data-change="w-chapter">${chapters.map(([value,zh,en]) => `<option value="${value}" ${value === w.chapter ? 'selected' : ''}>${e(t(zh,en))}</option>`).join('')}</select></label><span class="w-caption">${e(t('研究稿件 · 中文正文','Research draft · Chinese text'))}</span></div>`;
}
function manuscriptText(w,doc) {
  const chapter = chapters.find(([value]) => value === w.chapter);
  return `<article class="w-paper focus-panel" data-writing-panel="text">
    <div class="w-paper-meta"><span>${e(t('当前工作稿 · 内容预览','Current draft · Content preview'))}</span><span id="w-save-status" aria-live="polite">${e(saveStatus(doc))}</span></div>
    <div class="w-section-heading"><div><p class="eyebrow">${e(t('合成研究稿件','SYNTHETIC MANUSCRIPT'))}</p><h2>${e(t(chapter[1],chapter[2]))}</h2></div>${button(w.editing ? t('完成编辑','Finish editing') : t('编辑段落','Edit paragraph'),'w-edit','secondary','pen')}</div>
    ${w.editing ? `<label class="w-edit-label" for="w-paragraph">${e(t('当前章节正文','Current section text'))}</label><textarea id="w-paragraph" class="w-textarea" data-input="w-draft" aria-describedby="w-save-status">${e(doc.draft[w.chapter])}</textarea>` : `<p class="w-prose">${e(doc.draft[w.chapter])}</p>`}
    <div class="w-content-footer"><span>${e(t('待科研核验；最终 Word 排版需另行核对。','Research review pending; final Word layout needs a separate check.'))}</span>${viewButton(t('查看本节依据','View section sources'),'sources','ghost','link')}</div>
  </article>`;
}
function manuscriptSources() {
  return card(t('本节关联材料','Sources for this section'),`<div class="w-source">${icon('file',24)}<div><strong>实验分组说明.docx</strong><small>${e(t('合成材料 · 未核验','Synthetic material · Unverified'))}</small></div></div><p class="w-detail-copy">${e(t('用于演示章节与来源关联。未提供 DOI、真实文献或引用核验结果。','Illustrates section-source links. No DOI, actual reference or reference-verification result is supplied.'))}</p><div class="w-panel-actions">${viewButton(t('返回正文','Back to text'),'text')}</div>`,badge(t('待核对','To review'),'warning'),'w-focus-card focus-panel');
}
function manuscriptChecks() {
  const checks = [['统计方法与研究设计是否一致','Are statistical methods consistent with the study design?'],['引用是否能由原始来源支持','Are claims supported by original sources?'],['结论是否超出数据范围','Do conclusions exceed the data?']];
  return card(t('本节检查项','Section checklist'),`<ul class="w-check-list">${checks.map(([zh,en]) => `<li><span>${e(t(zh,en))}</span>${badge(t('待核对','To review'),'warning')}</li>`).join('')}</ul><p class="w-caption">${e(t('检查项示例；尚未执行真实内容检查。','Illustrative checklist; no actual content check has run.'))}</p><div class="w-panel-actions">${viewButton(t('返回正文','Back to text'),'text')}</div>`,'','w-focus-card focus-panel');
}
function manuscriptVersions(doc) {
  return card(t('当前稿件','Current manuscript'),`<div class="w-version-row">${icon('file',24)}<div><strong>${e(t('当前工作稿','Current working draft'))}</strong><p>${e(saveStatus(doc))}</p></div>${badge(t('预览内存','Preview memory'))}</div><p class="w-detail-copy">${e(t('本预览未连接版本服务，没有可恢复的历史版本。保存仅更新本次预览内存。','This preview is not connected to the version service and has no historical versions to restore. Saving updates this preview memory only.'))}</p><div class="w-panel-actions">${viewButton(t('继续编辑正文','Continue editing'),'text')}</div>`,'','w-focus-card focus-panel');
}
function manuscripts() {
  const w = ws(), doc = state.writing.docs[project().id], view = currentView(manuscriptViews,'text');
  const body = view === 'text' ? manuscriptText(w,doc) : view === 'sources' ? manuscriptSources() : view === 'checks' ? manuscriptChecks() : manuscriptVersions(doc);
  return head(t('写作工作区','Writing workspace'),t('稿件','Manuscript'),project().name,view === 'text' ? button(t('保存修改','Save changes'),'w-save','primary','save') : '')
    + chapterPicker(w) + switcher(manuscriptViews,view,t('稿件视图','Manuscript views')) + body;
}

function reviewPicker(w) {
  return `<div class="w-context-bar"><label class="w-picker w-review-picker" for="w-review">${e(t('本轮意见','Comment'))}<select id="w-review" data-change="w-review">${reviews.map((review,index) => `<option value="${index}" ${index === w.review ? 'selected' : ''}>${e(`${review.id} · ${review.title} · ${w.accepted[index] ? t('已采用','Adopted') : t('待处理','Pending')}`)}</option>`).join('')}</select></label><span class="w-caption">${e(t('第 1 轮 · 评审人 1','Round 1 · Reviewer 1'))}</span></div>`;
}
function reviewComment(r) {
  return `<div class="w-review-content" data-writing-panel="comment"><p class="w-caption">${e(t('原始意见 · 中文 · 合成示例','Original comment · Chinese · Synthetic sample'))}</p><blockquote class="w-comment">${e(r.title)}</blockquote><p class="w-detail-copy">${e(t('先记录处理计划，再核对修改对照；采用修改由你单独决定。','Record a plan, then review the proposed change. Adoption is a separate decision.'))}</p><div class="w-panel-actions">${viewButton(t('编写处理计划','Edit revision plan'),'plan','primary','pen')}</div></div>`;
}
function reviewPlan(w) {
  return `<div class="w-review-content" data-writing-panel="plan"><label class="field" for="w-plan">${e(t('处理计划 · 中文','Revision plan · Chinese'))}<textarea id="w-plan" class="w-plan" data-input="w-plan" aria-describedby="w-plan-status">${e(w.planDraft[w.review])}</textarea></label><p id="w-plan-status" class="w-caption" aria-live="polite">${e(planStatus(w))}</p><div class="w-panel-actions">${button(t('保存计划','Save plan'),'w-save-plan','primary','save')}${viewButton(t('查看修改对照','Review proposed change'),'compare')}</div></div>`;
}
function reviewCompare(w,r) {
  const proposed = w.compareSide !== 'original';
  return `<div class="w-review-content" data-writing-panel="compare">${switcher([['original','原文','Original'],['proposed','建议修改后','Proposed']],proposed ? 'proposed' : 'original',t('对照内容','Comparison text'),'w-compare-side')}<div class="w-comparison ${proposed ? 'w-proposed' : ''}"><p class="eyebrow">${e(proposed ? t('建议修改后 · 合成示例','PROPOSED · SYNTHETIC SAMPLE') : t('原文 · 中文','ORIGINAL · CHINESE'))}</p><p>${e(proposed ? r.after : r.original)}</p></div><p class="w-caption">${e(planDirty(w) ? t('处理计划尚未保存，请保存后再采用。','The revision plan has unsaved changes. Save it before adoption.') : t('采用仅更新本地演示状态；正式稿件未变更。','Adoption only updates the local demo state; the actual manuscript is unchanged.'))}</p><div class="w-panel-actions">${button(w.accepted[w.review] ? t('已采用演示修改','Demo change adopted') : t('采用演示修改','Adopt demo change'),'w-adopt','primary','check',w.accepted[w.review] ? 'disabled' : '')}${viewButton(planDirty(w) ? t('返回计划并保存','Return to plan and save') : t('查看处理计划','View revision plan'),'plan')}${viewButton(t('查看回复草稿','View response draft'),'response','ghost','message')}</div></div>`;
}
function reviewResponse() {
  return `<div class="w-review-content" data-writing-panel="response"><p class="w-caption">${e(t('回复草稿 · 中文 · 合成示例','Response draft · Chinese · Synthetic sample'))}</p><p class="w-prose w-response">感谢此项建议。拟根据原始记录补充说明，并在核对后更新对应段落。</p><p class="w-caption">${e(t('回复草稿尚未核验或导出，请与修改稿分别核对。','The response draft has not been verified or exported. Review it separately from the revised manuscript.'))}</p><div class="w-panel-actions">${viewButton(t('返回修改对照','Back to comparison'),'compare')}</div></div>`;
}
function reviewPage() {
  const w = ws(), r = reviews[w.review], view = currentView(reviewViews,'comment');
  const body = view === 'comment' ? reviewComment(r) : view === 'plan' ? reviewPlan(w) : view === 'compare' ? reviewCompare(w,r) : reviewResponse();
  return head(t('修改与回复','Revision & response'),t('意见修改','Review revisions'),project().name) + reviewPicker(w) + switcher(reviewViews,view,t('意见处理视图','Review views'))
    + `<section class="card w-focus-card focus-panel"><div class="panel-head"><div><p class="eyebrow">${r.id}</p><h2>${e(r.title)}</h2></div>${badge(w.accepted[w.review] ? t('已采用 · 预览','Adopted · Preview') : t('待用户决定','Decision pending'),w.accepted[w.review] ? 'success' : 'warning')}</div><div class="panel-body">${body}</div></section>`;
}

const journals = [
  {name:['Metabolic Research Example','Metabolic Research Example'],kind:['代谢研究方向 · 虚构期刊样例','Metabolic research · Fictional journal'],scope:['摘要结构、关键词与图表说明','Abstract structure, keywords and figure captions']},
  {name:['Biomedical Methods Example','Biomedical Methods Example'],kind:['方法研究方向 · 虚构期刊样例','Research methods · Fictional journal'],scope:['方法可重复性与研究局限','Method reproducibility and study limitations']},
];
const schools = [
  {name:['示例大学 · 学术硕士','Example University · Academic master’s'],kind:['学术硕士 · 合成模板','Academic master’s · Synthetic template'],scope:['标题层级、正文段落、参考文献格式','Heading levels, body paragraphs and reference style']},
  {name:['示例医学院 · 博士学位','Example Medical School · Doctoral degree'],kind:['博士学位 · 合成模板','Doctoral degree · Synthetic template'],scope:['封面字段、摘要结构、图表目录','Cover fields, abstract structure and lists of figures']},
];
function guidelineList(items,key,w,school) {
  return `<section class="card w-guideline-list focus-panel"><div class="panel-head"><h2>${e(school ? t('选择模板样例','Choose a template sample') : t('选择离线候选样例','Choose an offline candidate'))}</h2><span class="w-caption">${e(t('查看后再关联稿件','Review before linking'))}</span></div>${items.map((item,index) => `<button type="button" class="w-rule-choice" data-act="w-${key}" data-value="${index}">${icon(school ? 'layers' : 'book',22)}<span><strong>${e(t(...item.name))}</strong><small>${e(t(...item.kind))}</small></span>${w.links?.[key] === index ? badge(t('已关联','Linked'),'success') : ''}${icon('chevron')}</button>`).join('')}</section>`;
}
function ruleDetails(school) {
  const rules = school ? [
    ['封面与学位信息','Cover and degree details','核对学校名称、学位类型和模板官方版本。','Confirm the school, degree type and official template version.'],
    ['标题、图表与目录','Headings, figures and contents','层级、编号与目录范围需依据官方文件确认。','Verify hierarchy, numbering and contents against the official document.'],
    ['正文与参考文献','Body text and references','段落、页边距与引用格式分别核对。','Review paragraphs, margins and reference style separately.'],
  ] : [
    ['摘要与关键词','Abstract and keywords','背景、方法、结果、结论结构及关键词要求待确认。','Confirm abstract structure and keyword requirements.'],
    ['标题与图表','Headings and figures','层级、编号与图表说明需依据官方指南核对。','Verify hierarchy, numbering and captions against the official guidelines.'],
    ['参考文献','References','引用格式与来源真实性分别核对。','Review reference style and source authenticity separately.'],
  ];
  return `<dl class="w-rule-details">${rules.map(([zh,en,descZh,descEn]) => `<div><dt>${e(t(zh,en))}</dt><dd>${e(t(descZh,descEn))}</dd></div>`).join('')}</dl>`;
}
function guidelineBody(view,school,item) {
  if (view === 'rules') return `<p class="w-caption">${e(t('离线合成规则 · 尚未人工确认','Offline synthetic rules · Not yet confirmed'))}</p>${ruleDetails(school)}`;
  if (view === 'requirements') return `<ul class="w-requirements">${(school ? [
    ['确认适用学位与学校官方模板版本。','Confirm the degree and official school template version.'],
    ['核对页边距、标题、引用与目录规则。','Verify margins, headings, references and contents.'],
    ['Word、PDF 与办公软件分页分别核验。','Verify Word, PDF and office-app pagination separately.'],
  ] : [
    ['取得并核对期刊官方作者指南及版本。','Obtain and review the official author guidelines and version.'],
    ['SCI / SCIE、JIF / JCR：未接入 / 无可用来源。','SCI / SCIE, JIF / JCR: not connected / no available source.'],
    ['不推断收录、分区或录用概率。','No inference about indexing, quartiles or acceptance probability.'],
  ]).map(([zh,en]) => `<li>${e(t(zh,en))}</li>`).join('')}</ul><p class="w-caption">${e(school ? t('解析规则不等于格式合规。','Parsed rules do not establish compliance.') : t('这些候选用于展示组织方式，不是真实期刊推荐。','These candidates illustrate organization, not actual journal recommendations.'))}</p>`;
  return `<p class="w-detail-copy">${e(school ? t('来源：本地合成模板；尚未上传或解析真实学校文件。','Source: local synthetic template; no actual school document has been uploaded or parsed.') : t('来源：本地合成指南；未进行联网检索。','Source: local synthetic guidelines; no live lookup has run.'))}</p><dl class="w-rule-details"><div><dt>${e(t('可展示的规则范围','Illustrated rule scope'))}</dt><dd>${e(t(...item.scope))}</dd></div></dl><div class="w-panel-actions">${viewButton(t('查看规则详情','View rule details'),'rules','secondary','eye')}</div>`;
}
function rulesPage(school) {
  const w = ws(), items = school ? schools : journals, key = school ? 'school' : 'journal';
  const view = currentView([['list'],...guidelineViews],'list'), item = items[w[key]];
  const title = school ? t('学校模板','School templates') : t('期刊建议','Journal suggestions');
  if (view === 'list') return head(t('写作规范','Writing guidelines'),title,t('先选择一项，再查看来源与具体规则。','Choose one item to review its source and rules.')) + guidelineList(items,key,w,school);
  const linked = w.links?.[key] === w[key];
  return head(t('写作规范','Writing guidelines'),title,t(...item.name),viewButton(t('返回列表','Back to list'),'list','secondary','arrow')) + switcher(guidelineViews,view,t('规范详情视图','Guideline views'))
    + `<section class="card w-focus-card focus-panel"><div class="panel-head"><h2>${e(t(...item.name))}</h2>${badge(t('待人工确认','Pending review'),'warning')}</div><div class="panel-body">${guidelineBody(view,school,item)}<div class="w-guideline-footer"><p class="w-caption">${e(linked ? t('已关联当前预览稿件；正式适配仍待核对。','Linked to this preview manuscript; actual adaptation remains unverified.') : t('可关联当前预览稿件，后续仍需人工核对。','You can link this preview manuscript; manual review is still required.'))}</p>${button(linked ? t('已关联当前稿件','Current manuscript linked') : t('关联当前稿件','Link current manuscript'),'w-link',linked ? 'secondary' : 'primary','link',linked ? 'disabled' : '')}</div></div></section>`;
}

export function renderWriting(page) {
  if (!['manuscripts','reviews','journals','school-templates'].includes(page)) return null;
  return `<div class="w-workspace">${page === 'manuscripts' ? manuscripts() : page === 'reviews' ? reviewPage() : rulesPage(page === 'school-templates')}</div>`;
}
export function writingRouteItem(page,item) {
  const selection = {
    manuscripts:['chapter',chapters.map(([id]) => id)],
    reviews:['review',reviews.map(review => review.id)],
    journals:['journal',journals.map((_,index) => String(index))],
    'school-templates':['school',schools.map((_,index) => String(index))],
  }[page];
  if (!selection) return '';
  const w = ws(), [key,values] = selection, index = values.indexOf(item);
  if (index >= 0) w[key] = key === 'chapter' ? item : index;
  return key === 'chapter' ? w[key] : values[w[key]];
}
export function handleWriting(action,el,api) {
  if (!action.startsWith('w-')) return false;
  const w = ws(), doc = state.writing.docs[project().id];
  switch (action) {
    case 'w-view': api.view(el.dataset.value); break;
    case 'w-draft': {
      doc.draft[w.chapter] = el.value;
      computeDirty();
      const status = document.getElementById('w-save-status');
      if (status) status.textContent = saveStatus(doc);
      break;
    }
    case 'w-chapter': w.chapter = el.value || el.dataset.value; w.editing = false; api.view('text'); break;
    case 'w-edit':
      w.editing = !w.editing;
      api.render();
      if (w.editing) document.getElementById('w-paragraph')?.focus();
      break;
    case 'w-save':
      doc.saved = {...doc.draft};
      computeDirty();
      api.render();
      api.toast(t('已保存至本次预览内存，刷新页面会重置。','Saved in preview memory; refreshing resets the demo.'));
      break;
    case 'w-versions': api.view('versions'); break;
    case 'w-sources': api.view('sources'); break;
    case 'w-check': api.view('checks'); break;
    case 'w-review': w.review = Number(el.value || el.dataset.value); api.view('comment'); break;
    case 'w-plan': {
      w.planDraft[w.review] = el.value;
      computeDirty();
      const status = document.getElementById('w-plan-status');
      if (status) status.textContent = planStatus(w);
      break;
    }
    case 'w-save-plan':
      w.planSaved[w.review] = w.planDraft[w.review];
      computeDirty();
      api.render();
      api.toast(t('处理计划已保存至预览内存。','Revision plan saved in preview memory.'));
      break;
    case 'w-compare-side': w.compareSide = el.dataset.value; api.render(); break;
    case 'w-adopt':
      if (planDirty(w)) {
        api.toast(t('请先保存当前处理计划，再采用演示修改。','Save the current revision plan before adopting the demo change.'));
        break;
      }
      w.accepted[w.review] = true;
      api.render();
      api.toast(t('已采用演示修改；正式稿件未变更。','Demo change adopted; actual manuscript unchanged.'));
      break;
    case 'w-response': api.view('response'); break;
    case 'w-journal': w.journal = Number(el.dataset.value); api.view('detail'); break;
    case 'w-school': w.school = Number(el.dataset.value); api.view('detail'); break;
    case 'w-rules': api.view('rules'); break;
    case 'w-link': {
      const key = state.page === 'school-templates' ? 'school' : 'journal';
      w.links ??= {};
      w.links[key] = w[key];
      api.render();
      api.toast(t('已更新本地演示关联。','Local demo link updated.'));
      break;
    }
    case 'w-close': api.closeModal(); break;
    default: return false;
  }
  return true;
}
