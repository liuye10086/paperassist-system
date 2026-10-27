export const state = {
  lang: 'zh', page: 'home', view: '', selected: 'metabolism', collapsed: false, mobile: false,
  projectFilter: 'all', search: '', taskFilter: 'all', role: 'researcher',
  projects: [
    {id:'metabolism',name:'代谢表型与干预响应研究',topic:'不同干预条件下的代谢表型变化与研究结果整理',type:'sci',files:3,date:'2026-10-25',mark:'M',color:'sage',next:'manuscripts'},
    {id:'neural',name:'神经炎症相关指标分析',topic:'实验分组、炎症标志物与统计分析方案',type:'sci',files:3,date:'2026-10-24',mark:'N',color:'blue',next:'analysis'},
    {id:'thesis',name:'生物医学数据分析与方法研究',topic:'毕业论文写作与学校模板适配',type:'thesis',files:3,date:'2026-10-23',mark:'B',color:'sand',next:'manuscripts'},
  ],
  tasks:[
    {id:'sample-1',title:'统计分析方案确认',detail:'分析方案已准备，请核对变量与分组。',status:'waiting_confirmation',page:'analysis',time:'10:42'},
    {id:'sample-2',title:'稿件内容整理',detail:'当前示例稿件已保存，可继续编辑。',status:'succeeded',page:'manuscripts',time:'10:18'},
    {id:'sample-3',title:'文献资料读取',detail:'示例失败状态，可演示重新读取。',status:'failed',page:'literature',time:'昨天'},
    {id:'sample-4',title:'图表解释请求',detail:'提交结果尚未核实，不能重新发送。',status:'unknown',page:'tasks',time:'昨天'},
  ],
  research: {}, writing: {},
};
export const project = () => state.projects.find(p=>p.id===state.selected) || state.projects[0];
export const t = (zh,en) => state.lang==='en' ? (en||zh) : zh;
export const e = value => String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths={
grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
folder:'<path d="M3 7V5h7l2 2h9v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
file:'<path d="M14 3H5v18h14V8Zm0 0v6h5M8 13h8M8 17h5"/>',
chart:'<path d="M4 3v17h17M9 16V9m5 7V5m5 11v-4"/>',
book:'<path d="M12 5v16M3 3c4-1 6 0 9 2 3-2 5-3 9-2v16c-4-1-6 0-9 2-3-2-5-3-9-2Z"/>',
pen:'<path d="m14 5 5 5M4 20l4-1L21 6l-4-4L4 15Zm0 0h16"/>',
message:'<path d="M4 4h16v12H9l-5 4ZM8 8h8m-8 4h5"/>',
layers:'<path d="m3 7 9-5 9 5-9 5Zm0 5 9 5 9-5M3 17l9 5 9-5"/>',
check:'<path d="m5 12 4 4L19 6"/>',clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
arrow:'<path d="M5 12h14m-6-6 6 6-6 6"/>',chevron:'<path d="m9 5 7 7-7 7"/>',plus:'<path d="M12 5v14M5 12h14"/>',
search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
upload:'<path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5"/>',download:'<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>',
menu:'<path d="M4 6h16M4 12h16M4 18h16"/>',close:'<path d="m6 6 12 12M6 18 18 6"/>',
settings:'<circle cx="12" cy="12" r="3"/><path d="m9 3 1 2h4l1-2 3 2-1 2 2 3h2v4h-2l-2 3 1 2-3 2-1-2h-4l-1 2-3-2 1-2-2-3H3v-4h2l2-3-1-2Z"/>',
globe:'<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
user:'<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
leaf:'<path d="M20 3C7 2 2 9 6 16s15 4 14-13ZM4 21 16 8"/>',
alert:'<path d="m12 3 10 18H2Zm0 6v5m0 3v.1"/>',info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/>',
more:'<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
lock:'<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 4v3"/>',
logout:'<path d="M9 4H4v16h5m-1-8h13m-5-5 5 5-5 5"/>',link:'<path d="m9 15 6-6m-8 3-2 2a4 4 0 0 0 5 5l2-2m0-10 2-2a4 4 0 0 1 5 5l-2 2"/>',
eye:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
save:'<path d="M19 21H5a2 2 0 0 1-2-2V3h14l4 4v12a2 2 0 0 1-2 2ZM7 3v6h10V3M7 21v-8h10v8"/>',
refresh:'<path d="M20 7v5h-5M4 17v-5h5M5 8a8 8 0 0 1 13-3l2 3M4 16l2 3a8 8 0 0 0 13-3"/>',
filter:'<path d="M3 4h18l-7 8v7l-4 2v-9Z"/>',external:'<path d="M14 3h7v7m0-7L10 14m0-10H4v16h16v-6"/>',
collapse:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16m7-12-4 4 4 4"/>'};
export const icon=(name,size=18)=>`<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]||paths.file}</svg>`;
export const button=(label,act,variant='secondary',iconName='',attrs='')=>`<button type="button" class="button ${variant}" data-act="${e(act)}" ${attrs}>${iconName?icon(iconName):''}<span>${e(label)}</span></button>`;
export const badge=(label,tone='neutral')=>`<span class="badge ${tone}"><span class="status-dot"></span>${e(label)}</span>`;
export const head=(kicker,title,description,actions='')=>`<header class="page-heading"><div><p class="eyebrow">${e(kicker)}</p><h1 id="page-title" tabindex="-1">${e(title)}</h1>${description?`<p class="page-description">${e(description)}</p>`:''}</div><div class="heading-actions">${actions}</div></header>`;
export const card=(title,content,extra='',className='')=>`<section class="card ${className}"><div class="panel-head"><h2>${e(title)}</h2>${extra}</div><div class="panel-body">${content}</div></section>`;
