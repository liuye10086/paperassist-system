import {state, project, t, e, icon, button, badge, head, card} from './shared.js';

const raw = {
  control: [8.2, 8.7, 9.1, 8.5, 9.4, 8.9],
  intervention: [6.2, 6.8, 7.1, 6.5, 7.3, 6.7]
};
const sourceName = '代谢指标_合成样例.csv';
const papers = [
  {
    id: 'p1', title: '代谢干预与表型变化：一项虚构的探索性研究',
    authors: '示例作者 A · 示例作者 B', year: '2025', type: 'study',
    abstract: '本条目用于演示文献详情与项目收藏。研究假设是不同干预条件可能伴随代谢指标变化；没有真实实验、期刊来源或全文。'
  },
  {
    id: 'p2', title: '小样本生物医学研究中的描述统计报告',
    authors: '示例作者 C', year: '2024', type: 'method',
    abstract: '虚构方法学条目。示例强调同时报告样本量、单位和离散程度，并在使用推断检验前核对研究设计。'
  },
  {
    id: 'p3', title: '从数据表到研究图表的可追溯工作流程',
    authors: '示例作者 D · 示例作者 E', year: '2023', type: 'method',
    abstract: '虚构流程示例，用于展示原始数据、分析设置和图表之间的关联；不应被当作论文引用。'
  }
];

function s() {
  return state.research[project().id] ||= {
    files: project().isNew ? [] : [
      {name: sourceName, type: 'CSV', size: '1.2 KB', status: 'ready'},
      {name: '研究方案_示例.txt', type: 'TXT', size: '2.4 KB', status: 'review'},
      {name: '样本分组_合成样例.csv', type: 'CSV', size: '0.8 KB', status: 'ready'}
    ],
    fileFilter: 'all', metric: 'glucose', method: 'mean', phase: 'idle',
    result: null, query: '', literatureFilter: 'all', joined: ['p2']
  };
}

function select(label, action, value, items, disabled = false) {
  return `<label class="field"><span>${e(label)}</span>
    <select data-change="${action}" ${disabled ? 'disabled' : ''}>
      ${items.map(([v, label]) => `<option value="${e(v)}" ${v === value ? 'selected' : ''}>${e(label)}</option>`).join('')}
    </select>
  </label>`;
}

function table(headers, rows, label = t('表格，可在此区域滚动','Table; scroll within this region')) {
  return `<div class="table-scroll r-table-scroll" role="region" aria-label="${e(label)}" tabindex="0">
    <table class="r-table"><thead><tr>${headers.map(x => `<th scope="col">${e(x)}</th>`).join('')}</tr></thead>
      <tbody>${rows.join('')}</tbody>
    </table>
  </div>`;
}

function previewData() {
  return `<p class="muted r-scroll-hint">${t('12 行合成记录 · 在表格内滚动查看全部数据。','12 synthetic records · Scroll within the table to view all rows.')}</p>` +
    table([t('样本','Sample'), t('组别','Group'), 'Glucose (mmol/L)'],
      Object.entries(raw).flatMap(([group, values]) => values.map((value, index) => `<tr>
        <td>${group === 'control' ? 'C' : 'I'}${String(index + 1).padStart(2, '0')}</td>
        <td>${group === 'control' ? t('对照组','Control') : t('干预组','Intervention')}</td>
        <td>${value.toFixed(1)}</td>
      </tr>`)), t('合成数据表，12 行，可局部滚动','Synthetic data table, 12 rows, scrollable'));
}

function summarize(values) {
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  return {
    n: values.length, mean,
    sd: Math.sqrt(values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (values.length - 1)),
    min: Math.min(...values), max: Math.max(...values)
  };
}

function chart(result) {
  const labels = [t('对照组','Control'), t('干预组','Intervention')];
  const points = result.groups.map((group, index) => ({x: 190 + index * 210, y: 270 - (group.mean - 5) * 45, group}));
  return `<svg class="r-chart" viewBox="0 0 600 350" role="img" aria-label="${e(t('合成样例：两组葡萄糖均值及标准差','Synthetic sample: glucose means and standard deviations'))}" xmlns="http://www.w3.org/2000/svg">
    <rect width="600" height="350" fill="white"/>
    <text x="70" y="25" fill="#20271F" font-size="15">${e(t('葡萄糖 · 合成样例','Glucose · synthetic sample'))}</text>
    ${[5, 6, 7, 8, 9, 10].map(value => {
      const y = 270 - (value - 5) * 45;
      return `<line x1="70" x2="550" y1="${y}" y2="${y}" stroke="#E5EAE2"/><text x="55" y="${y + 4}" text-anchor="end" fill="#626C60" font-size="12">${value}</text>`;
    }).join('')}
    <path d="M70 45V270H550" fill="none" stroke="#7F8B79"/>
    <text x="14" y="160" transform="rotate(-90 14 160)" text-anchor="middle" font-size="12" fill="#626C60">mmol/L</text>
    ${points.map(({x, y, group}, index) => {
      const color = index ? '#245A83' : '#35613C';
      const sd = group.sd * 45;
      return `<line x1="${x}" y1="${y - sd}" x2="${x}" y2="${y + sd}" stroke="${color}" stroke-width="2"/>
        <path d="M${x - 10} ${y - sd}h20M${x - 10} ${y + sd}h20" stroke="${color}"/>
        <circle cx="${x}" cy="${y}" r="7" fill="${color}"/>
        <text x="${x + 16}" y="${y + 4}" font-size="12" fill="${color}">${group.mean.toFixed(2)}</text>
        <text x="${x}" y="295" text-anchor="middle" font-size="13" fill="#20271F">${e(labels[index])}</text>`;
    }).join('')}
    <text x="300" y="330" text-anchor="middle" font-size="12" fill="#626C60">${e(t('点：均值；误差线：±1 SD；每组 n = 6','Point: mean; error bar: ±1 SD; n = 6 per group'))}</text>
  </svg>`;
}

function results(result) {
  const showRange = result.method === 'range';
  return table([
    t('组别','Group'), 'n', t('均值 (mmol/L)','Mean (mmol/L)'), t('标准差','SD'),
    ...(showRange ? [t('范围','Range')] : [])
  ], result.groups.map((group, index) => `<tr>
    <td>${index ? t('干预组','Intervention') : t('对照组','Control')}</td><td>${group.n}</td>
    <td>${group.mean.toFixed(2)}</td><td>${group.sd.toFixed(2)}</td>
    ${showRange ? `<td>${group.min.toFixed(1)}–${group.max.toFixed(1)}</td>` : ''}
  </tr>`));
}

function viewButton(label, view, variant = 'secondary', iconName = '') {
  return button(label, 'r-view', variant, iconName, `data-view="${e(view)}"`);
}

function viewSwitcher(items, current, label) {
  return `<div class="view-switcher r-view-switcher" role="group" aria-label="${e(label)}">
    ${items.map(([view, text]) => `<button type="button" class="view-button ${current === view ? 'active' : ''}"
      data-act="r-view" data-view="${e(view)}" aria-pressed="${current === view}">${e(text)}</button>`).join('')}
  </div>`;
}

function staleResult(a) {
  return a.result && a.result.method !== a.method
    ? `<p class="r-status-note">${icon('info', 16)}${t('基于先前设置生成。返回分析方案可更新结果。','Generated with previous settings. Return to the plan to update results.')}</p>`
    : '';
}

function generatedTime(result) {
  return result.generatedAt
    ? new Intl.DateTimeFormat(state.lang === 'en' ? 'en-GB' : 'zh-CN', {hour: '2-digit', minute: '2-digit', second: '2-digit'}).format(new Date(result.generatedAt))
    : t('本次预览','This preview');
}

function renderFiles(a) {
  const fileIndex = /^file-\d+$/.test(state.view || '') ? Number(state.view.slice(5)) : -1;
  const file = a.files[fileIndex];
  if (file) {
    return head(t('研究材料 / 文件预览','RESEARCH MATERIALS / PREVIEW'), file.name,
      t('内置示例文件 · 内容仅供界面预览。','Bundled example file · Content for interface review only.'),
      viewButton(t('返回文件列表','Back to files'), 'list')) +
      card(t('文件内容','File contents'), file.type === 'CSV'
        ? previewData()
        : `<div class="r-reading"><p>研究目的：探索干预条件下代谢表型的变化。</p><p>本研究方案完全虚构，仅用于界面交互预览；全部样本为合成数据。</p></div>`,
      button(t('进入数据分析','Open data analysis'), 'r-go-analysis', 'primary', 'arrow'));
  }
  const files = a.files.map((file, index) => ({...file, index})).filter(file => a.fileFilter === 'all' || file.type === a.fileFilter);
  return head(t('研究材料','RESEARCH MATERIALS'), t('项目文件','Project files'),
    t('按文件管理数据与研究材料，打开条目查看内容。','Manage research materials by file and open an item to view its contents.'),
    button(t('添加示例文件','Add sample file'), 'r-add-file', 'primary', 'plus')) +
    card(t('材料库','Material library'), `<div class="toolbar r-list-toolbar">
      ${select(t('文件类型','File type'), 'r-file-filter', a.fileFilter, [['all',t('全部文件','All files')], ['CSV','CSV'], ['TXT','TXT']])}
      <span class="muted">${files.length} ${t('份示例材料','sample files')}</span>
    </div>${files.length ? table([t('文件名称','Name'), t('类型 / 大小','Type / size'), t('添加日期','Added'), t('状态','Status'), t('操作','Action')],
      files.map(file => `<tr>
        <td><span class="r-file-name">${icon('file')}<strong>${e(file.name)}</strong></span></td>
        <td><span class="r-nowrap">${file.type} · ${file.size}</span></td><td class="r-nowrap">2026-10-25</td>
        <td>${badge(file.status === 'ready' ? t('合成数据就绪','Synthetic ready') : t('待人工核对','Review needed'), file.status === 'ready' ? 'success' : 'warning')}</td>
        <td>${viewButton(t('预览','Preview'), `file-${file.index}`, 'ghost', 'eye')}</td>
      </tr>`)) : `<div class="empty"><p>${t('这里还没有符合条件的示例文件。','No sample files match this view yet.')}</p></div>`}
      <p class="muted r-footnote">${t('添加内置样例不会读取本机文件；刷新后恢复初始状态。','Adding a bundled sample does not read local files. Reloading resets the preview.')}</p>`);
}

function renderAnalysis(a) {
  const views = [
    ['prepare', t('数据概况','Overview')], ['data', t('数据表','Data table')],
    ['plan', t('分析方案','Analysis plan')], ['results', t('统计结果','Statistics')],
    ['charts', t('图表','Charts')]
  ];
  const view = views.some(([key]) => key === state.view) ? state.view : 'prepare';
  let body;
  if (view === 'prepare') {
    body = card(t('数据概况','Data overview'), `<div class="r-overview-content">
      <div><p class="r-lead">${t('两组独立样本，准备进行描述统计。','Two independent groups, ready for descriptive statistics.')}</p>
        <dl class="r-meta">
          <dt>${t('来源','Source')}</dt><dd>${sourceName}</dd>
          <dt>${t('数据规模','Dataset')}</dt><dd>${t('12 行 · 2 组 · 每组 6 例','12 rows · 2 groups · 6 samples each')}</dd>
          <dt>${t('目标变量','Outcome')}</dt><dd>Glucose · mmol/L</dd>
          <dt>${t('分组','Groups')}</dt><dd>${t('对照组 / 干预组','Control / Intervention')}</dd>
          <dt>${t('缺失值','Missing values')}</dt><dd>${t('0 · 内置样例无缺失值','0 · None in the bundled sample')}</dd>
        </dl>
        <p class="muted r-footnote">${t('内置合成数据可用于体验分析；研究设计与真实样本尚未核验。','Bundled synthetic data is ready for this demo; study design and real samples have not been validated.')}</p>
      </div>
      <div class="r-overview-actions">${badge(t('合成样例就绪','Synthetic sample ready'),'success')}
        ${viewButton(t('配置分析方案','Configure analysis'), 'plan', 'primary', 'arrow')}
        ${viewButton(t('查看数据表','View data table'), 'data', 'secondary', 'file')}
      </div>
    </div>`);
  } else if (view === 'data') {
    body = card(t('数据表 · 合成样例','Data table · synthetic sample'), previewData(),
      viewButton(t('配置分析方案','Configure analysis'), 'plan', 'primary', 'arrow'));
  } else if (view === 'plan') {
    body = card(t('确认分析方案','Confirm analysis plan'), `<div class="r-plan-layout">
      <div class="r-plan-fields">
        ${select(t('目标变量','Outcome'), 'r-metric', a.metric, [['glucose','Glucose (mmol/L)']], a.phase === 'running')}
        ${select(t('报告方式','Report format'), 'r-method', a.method, [
          ['mean',t('均值与标准差','Mean and standard deviation')],
          ['range',t('均值、标准差与范围','Mean, SD and range')]
        ], a.phase === 'running')}
        <div class="r-plan-action">${button(a.phase === 'running' ? t('正在本地计算…','Computing locally…') : t('运行本地模拟分析','Run local simulation'),
          'r-run', 'primary', 'chart', a.phase === 'running' ? 'disabled' : '')}</div>
        ${a.phase === 'running' ? `<p class="r-run-status" role="status">${e(a.stage)}</p>` : a.result ? `<p class="muted">${t('已有结果。重新运行将更新当前预览成果。','Results available. Running again updates this preview output.')}</p>` : ''}
      </div>
      <div class="r-plan-context">
        <h3>${t('本次分析依据','Analysis basis')}</h3>
        <dl class="r-meta">
          <dt>${t('数据','Data')}</dt><dd>${sourceName} · ${t('12 行','12 rows')}</dd>
          <dt>${t('分组','Groups')}</dt><dd>${t('对照组 / 干预组，各 6 例','Control / Intervention, 6 samples each')}</dd>
          <dt>${t('方法','Method')}</dt><dd>${t('均值、样本标准差（n−1）','Mean, sample SD (n−1)')}${a.method === 'range' ? t('、最小值与最大值',', minimum and maximum') : ''}</dd>
          <dt>${t('缺失值','Missing')}</dt><dd>${t('样例无缺失值','None in this sample')}</dd>
        </dl>
        <p class="muted r-footnote">${t('仅描述两组分布，不计算显著性或形成真实科研结论。','Describes both groups only; no significance tests or real research conclusions.')}</p>
      </div>
    </div>`);
  } else if (a.result) {
    const isChart = view === 'charts';
    body = card(isChart ? t('分组葡萄糖水平','Glucose by group') : t('描述性统计','Descriptive statistics'),
      `${staleResult(a)}${isChart ? chart(a.result) : results(a.result)}
        <p class="muted r-footnote">${isChart
          ? t('来源：内置合成样例。点为均值，误差线为 ±1 SD，不代表置信区间。','Source: bundled synthetic sample. Points show means; error bars show ±1 SD, not confidence intervals.')
          : t('来源：内置 12 行合成记录。标准差使用 n−1；仅演示描述统计。','Source: 12 bundled synthetic records. SD uses n−1; descriptive demo only.')}</p>`,
      button(t('查看成果列表','View outputs'), 'r-go-artifacts', 'secondary', 'arrow'));
  } else {
    body = `<div class="empty">${icon('chart',32)}<h2>${t('尚无模拟结果','No simulated results yet')}</h2>
      <p>${a.phase === 'running' ? e(a.stage) : t('确认分析方案后，即可运行本地计算。','Confirm the plan to run a local calculation.')}</p>
      ${viewButton(t('前往分析方案','Open analysis plan'), 'plan', 'primary')}
    </div>`;
  }
  return head(t('研究工作流','RESEARCH WORKFLOW'), t('数据分析','Data analysis'),
    t('每次专注一个环节，随时切换数据、方案与结果。','Focus on one stage and switch between data, plan and results.')) +
    viewSwitcher(views, view, t('分析视图','Analysis views')) + body;
}

function renderArtifacts(a) {
  const view = ['figure','summary'].includes(state.view) ? state.view : 'list';
  const heading = head(t('研究成果','RESEARCH OUTPUTS'),
    view === 'figure' ? t('葡萄糖分组描述图','Glucose group summary') : view === 'summary' ? t('统计摘要','Statistical summary') : t('图表与报告','Charts & reports'),
    view === 'list' ? t('按成果浏览，打开后查看图表或统计摘要。','Browse outputs and open a chart or statistical summary.') : t('来源：代谢指标_合成样例.csv · 合成样例，未科研核验。','Source: 代谢指标_合成样例.csv · Synthetic, not research-validated.'),
    view === 'list' ? '' : viewButton(t('返回成果列表','Back to outputs'), 'list'));
  if (!a.result) {
    return heading + `<div class="empty">${icon('chart',36)}<h2>${t('运行分析后，成果会出现在这里','Run an analysis to create an output')}</h2>
      <p>${t('先确认数据与分析方案，再生成本地模拟结果。','Review the data and plan, then generate local simulation results.')}</p>
      ${button(t('前往分析方案','Open analysis plan'),'r-go-analysis','primary','arrow','data-view="plan"')}
    </div>`;
  }
  if (view === 'figure') {
    return heading + card(t('图表预览','Chart preview'), `${staleResult(a)}${chart(a.result)}
      <p class="muted r-footnote">${t('每组 n = 6。误差线为 ±1 SD，不代表置信区间；没有显著性检验。','n = 6 per group. Error bars show ±1 SD, not confidence intervals; no significance test.')}</p>`,
    button(t('下载示例 SVG','Download sample SVG'),'r-download-svg','primary','download') +
    viewButton(t('查看统计摘要','View summary'),'summary','secondary','file'));
  }
  if (view === 'summary') {
    return heading + card(t('分组葡萄糖描述性统计','Descriptive glucose statistics'), `${staleResult(a)}${results(a.result)}
      <div class="r-summary-method"><h3>${t('方法与范围','Method and scope')}</h3>
        <p>${t('在浏览器内计算 12 条内置记录的均值与样本标准差（分母 n−1）。这份摘要仅用于合成样例演示，不构成真实科研证据。','Means and sample standard deviations (denominator n−1) are computed in the browser from 12 bundled records. This synthetic summary is a demonstration, not research evidence.')}</p>
      </div>`, button(t('下载示例 TXT','Download sample TXT'),'r-download-txt','primary','download') +
      viewButton(t('查看图表','View chart'),'figure','secondary','chart'));
  }
  const outputs = [
    {view:'figure', title:t('葡萄糖分组描述图','Glucose group summary'), type:'SVG', icon:'chart', description:t('均值与标准差图','Mean and SD chart')},
    {view:'summary', title:t('分组葡萄糖统计摘要','Glucose statistical summary'), type:'TXT', icon:'file', description:t('方法与描述性统计','Method and descriptive statistics')}
  ];
  return heading + card(t('当前分析成果','Current analysis outputs'), `${staleResult(a)}
    <div class="r-output-list">${outputs.map(output => `<article class="r-output-row">
      <div class="r-item-symbol">${icon(output.icon,23)}</div>
      <div class="r-output-body"><h3><button type="button" class="r-title-button" data-act="r-view" data-view="${output.view}">${e(output.title)}</button></h3>
        <p class="muted">${output.type} · ${output.description} · ${t('本地生成','Generated locally')} ${e(generatedTime(a.result))}</p>
        <p class="muted r-source-line">${t('来源','Source')}：${sourceName} · ${t('合成样例，未科研核验','Synthetic, not research-validated')}</p>
      </div>${viewButton(t('查看详情','View details'),output.view,'secondary','eye')}
    </article>`).join('')}</div>`);
}

function paperCollectionAction(a, paper, variant = 'secondary') {
  return a.joined.includes(paper.id)
    ? badge(t('已加入当前项目','Added to project'),'success')
    : button(t('加入项目','Add to project'),'r-paper-add',variant,'plus',`data-id="${paper.id}"`);
}

function renderLiterature(a) {
  const paper = papers.find(item => state.view === `paper-${item.id}`);
  if (paper) {
    return head(t('证据与引用 / 文献详情','EVIDENCE & REFERENCES / DETAILS'), paper.title,
      `${paper.authors} · ${paper.year}`, viewButton(t('返回文献列表','Back to literature'),'list')) +
      card(t('文献详情','Reference details'), `<div class="r-paper-detail">
        <div class="r-detail-status">${badge(t('虚构样例，不可引用','Fictional example; do not cite'),'warning')}</div>
        <h3>${t('示例摘要','Sample abstract')}</h3><p class="r-abstract">${e(paper.abstract)}</p>
        <dl class="r-meta">
          <dt>${t('来源','Source')}</dt><dd>${t('内置虚构条目，无真实出版来源','Bundled fictional entry; no publication source')}</dd>
          <dt>DOI / PMID</dt><dd>${t('未提供','Not provided')}</dd>
          <dt>${t('全文','Full text')}</dt><dd>${t('无真实全文','No real full text')}</dd>
          <dt>${t('引用核验','Citation check')}</dt><dd>${t('未核验，收藏不代表引用可靠','Not verified; adding to a project does not validate a citation')}</dd>
        </dl>
      </div>`, paperCollectionAction(a,paper,'primary'));
  }
  const list = papers.filter(paper =>
    (a.literatureFilter !== 'project' || a.joined.includes(paper.id)) &&
    (a.literatureFilter !== 'method' || paper.type === 'method') &&
    `${paper.title} ${paper.authors} ${paper.year}`.toLowerCase().includes(a.query.toLowerCase()));
  return head(t('证据与引用','EVIDENCE & REFERENCES'),t('文献资料','Literature'),
    t('筛选条目并管理项目收藏，打开详情阅读摘要。','Filter entries, manage project references and open details to read abstracts.')) +
    card(t('示例文献库','Sample library'), `<div class="toolbar r-lit-toolbar">
      <label class="field r-search"><span>${t('标题、作者或年份','Title, author or year')}</span>
        <input type="search" value="${e(a.query)}" placeholder="${e(t('输入关键词','Enter a keyword'))}" data-input="r-query">
      </label>
      ${select(t('范围','Scope'),'r-lit-filter',a.literatureFilter,[
        ['all',t('全部样例','All examples')],['project',t('已加入当前项目','In current project')],['method',t('方法学样例','Methods examples')]
      ])}<span class="muted">${list.length} ${t('条','entries')}</span>
    </div><div class="r-literature-list">${list.length ? list.map(paper => `<article class="r-paper">
      <div class="r-item-symbol">${icon('book',23)}</div>
      <div class="r-paper-body"><h3><button type="button" class="r-title-button" data-act="r-paper-detail" data-id="${paper.id}">${e(paper.title)}</button></h3>
        <p class="muted">${e(paper.authors)} · ${e(paper.year)}</p>
        <p class="muted r-source-line">${t('虚构样例 · 无 DOI / PMID · 引用未核验','Fictional example · No DOI / PMID · Citation not verified')}</p>
      </div><div class="r-paper-actions">${paperCollectionAction(a,paper)}
        ${button(t('详情','Details'),'r-paper-detail','ghost','eye',`data-id="${paper.id}"`)}
      </div>
    </article>`).join('') : `<div class="empty"><h3>${t('没有符合条件的条目','No matching entries')}</h3>
      ${button(t('清除筛选','Clear filters'),'r-clear-literature','secondary')}</div>`}</div>`);
}

export function renderResearch(page) {
  const renderers = {files:renderFiles, analysis:renderAnalysis, artifacts:renderArtifacts, literature:renderLiterature};
  return renderers[page] ? `<div class="r-module">${renderers[page](s())}</div>` : null;
}

function download(content, name, type) {
  const url = URL.createObjectURL(new Blob([content], {type}));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url),1000);
}

function runAnalysis(a, api) {
  if (a.phase === 'running') return;
  const target = a;
  const projectId = project().id;
  const startedView = state.view;
  const method = a.method;
  target.phase = 'running';
  target.stage = t('正在读取内置样例…','Reading bundled sample…');
  api.render();
  setTimeout(() => {
    target.stage = t('正在计算两组描述统计…','Computing group summaries…');
    if (project().id === projectId && state.page === 'analysis' && state.view === startedView) api.render();
    setTimeout(() => {
      target.result = {groups:Object.values(raw).map(summarize), method, generatedAt:new Date().toISOString()};
      target.phase = 'done';
      api.addTask(t('合成样例描述统计（本地模拟）','Synthetic descriptive statistics (local demo)'), 'succeeded', projectId);
      if (project().id === projectId) {
        if (state.page === 'analysis' && startedView === 'plan' && state.view === startedView) api.view('results');
        else if (['artifacts','tasks','overview'].includes(state.page)) api.render();
        api.toast(t('本地计算完成；结果仅适用于合成样例。','Local calculation complete; synthetic sample only.'));
      }
    },650);
  },500);
}

export function handleResearch(action, element, api) {
  if (!action.startsWith('r-')) return false;
  const a = s();
  if (action.startsWith('r-tab-')) {
    api.view(action.slice(6));
    return true;
  }
  switch (action) {
    case 'r-view': api.view(element.dataset.view); break;
    case 'r-file-filter': a.fileFilter = element.value; api.render(); break;
    case 'r-add-file': {
      const name = `补充数据_合成样例_${a.files.length + 1}.csv`;
      a.files.push({name, type:'CSV', size:'1.2 KB', status:'ready'});
      project().files = a.files.length;
      api.render();
      api.toast(t('已添加内置合成样例；没有读取本机文件。','Bundled synthetic sample added; no local file was read.'));
      break;
    }
    case 'r-preview-file': {
      const index = a.files.findIndex(file => file.name === element.dataset.file);
      if (index >= 0) api.view(`file-${index}`);
      break;
    }
    case 'r-metric': a.metric = element.value; api.render(); break;
    case 'r-method': a.method = element.value; api.render(); break;
    case 'r-run': runAnalysis(a,api); break;
    case 'r-go-analysis': api.navigate('analysis', undefined, element.dataset.view || 'prepare'); break;
    case 'r-go-artifacts': api.navigate('artifacts', undefined, 'list'); break;
    case 'r-artifact-detail': if (a.result) api.view('figure'); break;
    case 'r-download-svg':
      if (a.result) {
        download(chart(a.result),'synthetic-glucose-chart.svg','image/svg+xml');
        api.toast(t('已下载标注合成样例的 SVG。','Synthetic sample SVG downloaded.'));
      }
      break;
    case 'r-download-txt':
      if (a.result) {
        const text = 'SYNTHETIC SAMPLE / 合成样例\nSource: bundled synthetic data, 12 records\nMethod: sample mean and SD (n-1); no inference\n' +
          a.result.groups.map((group,index) => `${index ? 'Intervention' : 'Control'}: n=${group.n}; mean=${group.mean.toFixed(2)} mmol/L; SD=${group.sd.toFixed(2)}${a.result.method === 'range' ? `; range=${group.min}-${group.max}` : ''}`).join('\n') +
          '\nNot research evidence. Not validated.';
        download(text,'synthetic-statistics.txt','text/plain;charset=utf-8');
        api.toast(t('已下载合成样例 TXT。','Synthetic sample TXT downloaded.'));
      }
      break;
    case 'r-query': {
      const start = element.selectionStart;
      const end = element.selectionEnd;
      a.query = element.value;
      api.render();
      const input = document.querySelector('[data-input="r-query"]');
      if (input) {
        input.focus();
        if (start !== null) input.setSelectionRange(start,end);
      }
      break;
    }
    case 'r-lit-filter': a.literatureFilter = element.value; api.render(); break;
    case 'r-clear-literature': a.query = ''; a.literatureFilter = 'all'; api.render(); break;
    case 'r-paper-add':
      if (papers.some(paper => paper.id === element.dataset.id) && !a.joined.includes(element.dataset.id)) a.joined.push(element.dataset.id);
      api.render();
      api.toast(t('已加入当前项目；引用内容仍未核验。','Added to this project; citation remains unverified.'));
      break;
    case 'r-paper-detail':
      if (papers.some(paper => paper.id === element.dataset.id)) api.view(`paper-${element.dataset.id}`);
      break;
    default: return false;
  }
  return true;
}
