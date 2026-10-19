import LiteratureChecks from './LiteratureChecks'
import EvidenceWorkspace from './EvidenceWorkspace'
import CitationWorkspace from './CitationWorkspace'
import SavedSearchContext from './SavedSearchContext'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { safeError, translateForLocale, useI18n } from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { isTask, taskDisplayName, type TaskView } from '../tasks/taskTypes'
import { TaskRequestError } from '../tasks/taskApi'
import { basePath, literatureRequest, publicationTypes, validConfig, validDetail, validPage, validReference, validSearch, validSearchInput, type Configuration, type Page, type Reference, type ReferenceDetail, type Search, type SearchInput, type Selection, type Source } from './literatureApi'
import './literature.css'
type Props={projectId:string;researchTopic:string;outputLanguage?:string;active:boolean;initialSearchId?:string;onOpenTask?:(id:string)=>void;onSearchChange?:(id:string)=>void}
export default function ProjectLiterature(props:Props){return props.active?<Scope key={props.projectId} {...props}/>:null}
function Scope(props:Props){const {t}=useI18n();const [valid,setValid]=useState(true);useEffect(()=>onApiSessionChanged(()=>setValid(false)),[]);return valid?<Literature {...props}/>:<p role="alert">{t('会话已失效，请重新登录。')}</p>}
function useResource<T>(url:string|null,valid:(v:unknown)=>v is T,revision:number,onDenied:()=>void,onLoaded?:(data:T)=>void){
 const key=url===null?null:JSON.stringify([url,revision])
 const [state,setState]=useState<{key:string|null;data:T|null;error:string;loading:boolean}>({key:null,data:null,error:'',loading:false})
 const callbacks=useRef({valid,onDenied,onLoaded});useEffect(()=>{callbacks.current={valid,onDenied,onLoaded}})
 useEffect(()=>{if(!url)return;let active=true;const controller=new AbortController()
 void literatureRequest(url,controller,v=>callbacks.current.valid(v)).then(data=>{if(active&&!controller.signal.aborted){setState({key,data,error:'',loading:false});callbacks.current.onLoaded?.(data)}}).catch(cause=>{if(!active)return;if(cause instanceof TaskRequestError&&cause.status===403)callbacks.current.onDenied();setState({key,data:null,error:safeError(cause,'文献资料读取失败，请重试。'),loading:false})})
 return()=>{active=false;controller.abort()}
 },[url,revision,key])
 return state.key===key?state:{key,data:null,error:'',loading:!!url}
}
function Pagination({page,total,label,onPage,disabled=false}:{page:number;total:number;label:string;onPage:(p:number)=>void;disabled?:boolean}){const {t}=useI18n();const pages=Math.max(1,Math.ceil(total/10));return <nav className="literature-pagination" aria-label={t(label)}><span>{t('共 {total} 项 · 第 {page} / {pages} 页',{total,page,pages})}</span><button type="button" disabled={disabled||page<=1} onClick={()=>onPage(page-1)}>{t('上一页')}</button><button type="button" disabled={disabled||page>=pages} onClick={()=>onPage(page+1)}>{t('下一页')}</button></nav>}
function Literature({projectId,researchTopic,outputLanguage,onOpenTask,initialSearchId,onSearchChange}:Props){
 const {t,locale}=useI18n();const base=basePath(projectId)
 const [evidenceOpen,setEvidenceOpen]=useState(false);const [citationOpen,setCitationOpen]=useState(false);const [denied,setDenied]=useState(false);const deny=()=>setDenied(true)
 const [revision,setRevision]=useState(0);const [historyPage,setHistoryPage]=useState(1);const [candidatePage,setCandidatePage]=useState(1)
 const [searchId,setSearchId]=useState(initialSearchId??'');const [selection,setSelection]=useState('');const [detailId,setDetailId]=useState('')
 const [input,setInput]=useState<SearchInput>({research_topic:researchTopic,source_context:{kind:'project_topic',label:'',text:researchTopic},query:'',year_from:null,year_to:null,publication_types:[],sort:'relevance',limit:20,output_language:outputLanguage==='en'?'en':'zh-CN'})
 const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [saved,setSaved]=useState<TaskView|null>(null)
 const replay=useRef<{signature:string;key:string}|null>(null);const request=useRef<AbortController|null>(null);const mounted=useRef(true)
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;request.current?.abort()}},[])
 const config=useResource<Configuration>(denied?null:`${base}/config`,validConfig,revision,deny)
 const history=useResource<Page<Search>>(denied?null:`${base}/searches?page=${historyPage}`,v=>validPage(v,projectId,historyPage,x=>validSearch(x,projectId)),revision,deny,data=>{const last=Math.max(1,Math.ceil(data.total/10));if(historyPage>last)setHistoryPage(last)})
 const search=useResource<Search>(!denied&&searchId?`${base}/searches/${encodeURIComponent(searchId)}`:null,(v):v is Search=>validSearch(v,projectId)&&v.id===searchId,revision,deny)
 const params=new URLSearchParams({page:String(candidatePage)});if(searchId)params.set('search_id',searchId);if(selection)params.set('selection',selection)
 const candidates=useResource<Page<Reference>>(denied?null:`${base}/references?${params}`,v=>validPage(v,projectId,candidatePage,x=>validReference(x,projectId)),revision,deny,data=>{const last=Math.max(1,Math.ceil(data.total/10));if(candidatePage>last)setCandidatePage(last)})
 function refresh(){setRevision(r=>r+1)}
 function chooseSearch(id:string){setSearchId(id);onSearchChange?.(id);setCandidatePage(1);setDetailId('')}
 function edit<K extends keyof SearchInput>(key:K,value:SearchInput[K]){setInput(old=>({...old,[key]:value}));setSaved(null);setError('')}
 async function create(event:FormEvent){event.preventDefault();if(request.current||denied)return
 const body={...input,research_topic:input.research_topic.trim(),query:input.query.trim()}
 if(!validSearchInput(body)){setError('请检查研究主题、检索式和年份范围。');return}
 const signature=JSON.stringify(body);if(replay.current?.signature!==signature)replay.current={signature,key:crypto.randomUUID()}
 const controller=new AbortController();request.current=controller;setBusy(true);setError('');setSaved(null)
 try{const task=await literatureRequest(`${base}/searches`,controller,(v):v is TaskView=>isTask(v,projectId)&&v.task_type==='literature_search',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':replay.current.key},body:signature});if(mounted.current&&!controller.signal.aborted){setSaved(task);refresh()}}
 catch(cause){if(mounted.current){if(cause instanceof TaskRequestError&&cause.status===403)deny();setError('检索提交结果未确认，请先刷新历史；相同输入重试沿用请求标识。')}}
 finally{if(request.current===controller)request.current=null;if(mounted.current)setBusy(false)}
 }
 if(denied)return <p className="error-panel" role="alert">{t('项目不存在或无权访问。')}</p>
 return <section className="literature-workspace" aria-label={t('项目文献')}>
 <div className="workspace-page-heading"><div><span className="workspace-eyebrow">PubMed</span><h2>{t('文献')}</h2><p>{t('保存检索过程，查看原始来源，人工筛选项目候选。')}</p></div><button type="button" onClick={refresh}>{t('刷新文献记录')}</button></div>
 <div className="literature-actions"><button type="button" aria-expanded={evidenceOpen} onClick={()=>{setEvidenceOpen(v=>!v);setCitationOpen(false)}}>{t(evidenceOpen?'关闭论述核验工作区':'论述与证据核验')}</button><button type="button" aria-expanded={citationOpen} onClick={()=>{setCitationOpen(v=>!v);setEvidenceOpen(false)}}>{t(citationOpen?'关闭引用工作台':'引用工作台')}</button></div>
 {evidenceOpen&&<EvidenceWorkspace projectId={projectId} researchTopic={researchTopic} outputLanguage={outputLanguage} onOpenTask={onOpenTask} onDenied={deny}/>}
 {citationOpen&&<CitationWorkspace projectId={projectId} outputLanguage={outputLanguage} onVerify={()=>{setCitationOpen(false);setEvidenceOpen(true)}} onDenied={deny}/>}
 {!evidenceOpen&&!citationOpen&&<>
 {config.loading&&<p role="status">{t('正在读取文献配置……')}</p>}{config.error&&<p role="alert">{t(config.error)}</p>}
 {config.data&&<p className="warning-panel">{t(config.data.available?'本机 NCBI 配置已启用；检索结果以实际任务回执为准。':'NCBI 当前关闭；已保存结果仍可查看。新检索任务将持久等待配置。')}</p>}
 <form className="project-form literature-form" aria-label={t('文献检索条件')} onSubmit={event=>void create(event)}>
 <fieldset disabled={busy}><legend>{t('研究主题与来源')}</legend>
 <label>{t('研究主题')}<textarea required maxLength={2000} value={input.research_topic} onChange={e=>edit('research_topic',e.target.value)} /></label>
 <div className="project-fields"><label>{t('来源类型')}<select value={input.source_context.kind} onChange={e=>edit('source_context',{...input.source_context,kind:e.target.value as SearchInput['source_context']['kind']})}><option value="project_topic">{t('项目研究主题')}</option><option value="section">{t('论文章节')}</option><option value="feedback">{t('导师或审稿反馈')}</option></select></label><label>{t('来源标签')}<input maxLength={200} value={input.source_context.label} onChange={e=>edit('source_context',{...input.source_context,label:e.target.value})}/></label></div>
 <label>{t('来源文本快照')}<textarea maxLength={6000} value={input.source_context.text} onChange={e=>edit('source_context',{...input.source_context,text:e.target.value})}/></label>
 <p className="muted">{t('检索依据按本次填写保存，后续修改不会改写历史。')}</p>
 <label>{t('PubMed 检索式')}<textarea required maxLength={4000} value={input.query} onChange={e=>edit('query',e.target.value)} placeholder="(topic[Title/Abstract]) AND (population[Title/Abstract])"/></label>
 <div className="literature-condition-grid"><label>{t('起始年份')}<input type="number" min={1800} max={3000} step={1} placeholder={t('不限')} value={input.year_from??''} onChange={e=>edit('year_from',e.target.value===''?null:Number(e.target.value))}/></label><label>{t('结束年份')}<input type="number" min={1800} max={3000} step={1} placeholder={t('不限')} value={input.year_to??''} onChange={e=>edit('year_to',e.target.value===''?null:Number(e.target.value))}/></label>
 <label>{t('排序方式')}<select value={input.sort} onChange={e=>edit('sort',e.target.value as SearchInput['sort'])}><option value="relevance">{t('相关性')}</option><option value="pub_date">{t('发表日期')}</option></select></label>
 <label>{t('候选数量上限')}<select value={input.limit} onChange={e=>edit('limit',Number(e.target.value) as SearchInput['limit'])}>{[20,50,100].map(n=><option key={n} value={n}>{n}</option>)}</select></label>
 <label>{t('检索输出语言')}<select value={input.output_language} onChange={e=>edit('output_language',e.target.value as SearchInput['output_language'])}><option value="zh-CN">{t('简体中文')}</option><option value="en">English</option></select></label></div>
 <fieldset className="literature-types"><legend>{t('文献类型（默认不限）')}</legend>{publicationTypes.map(type=><label key={type}><input type="checkbox" checked={input.publication_types.includes(type)} onChange={e=>edit('publication_types',e.target.checked?[...input.publication_types,type]:input.publication_types.filter(v=>v!==type))}/>{t(publicationTypeLabel(type))}</label>)}</fieldset>
 <p className="muted">{t('自动补搜：0。修改条件后创建新任务，历史输入保留。')} · <a href="https://www.ncbi.nlm.nih.gov/About/disclaimer.html" target="_blank" rel="noopener noreferrer">{t('NCBI 使用与版权说明')}</a></p>
 <p className="muted">{t('PubMed 主要覆盖生物医学，全文可得性以实际取得为准。')}</p>
 <button type="submit" className="button-primary">{t(busy?'正在保存检索……':'保存检索并创建任务')}</button>
 </fieldset></form>
 {error&&<p role="alert" className="error-panel">{t(error)}</p>}{saved&&<div role="status"><p>{t('检索任务已保存。')}</p><TaskEntry projectId={projectId} taskId={saved.id} onOpenTask={onOpenTask}/></div>}
 <section className="literature-panel" aria-label={t('检索历史')}><h3>{t('检索历史')}</h3>{history.loading&&<p role="status">{t('正在读取检索历史……')}</p>}{history.error&&<p role="alert">{t(history.error)}</p>}
 {history.data&&<>{!history.data.items.length&&<p>{t('尚无检索记录。')}</p>}<ol className="literature-history">{history.data.items.map(item=><li key={item.id}><strong>{item.input.research_topic}</strong><p className="literature-original">{item.input.query}</p><span>{translateForLocale(taskDisplayName(item.task),item.input.output_language)} · {new Date(item.created_at).toLocaleString(locale)} · {translateForLocale('已获取 {count} 篇',item.input.output_language,{count:item.retrieved_count})}</span><div className="literature-actions"><button type="button" onClick={()=>chooseSearch(item.id)}>{t('查看本次检索')}</button><button type="button" disabled={busy} onClick={()=>{setInput(structuredClone(item.input));setSaved(null);setError('')}}>{t('编辑后重新检索')}</button><TaskEntry projectId={projectId} taskId={item.task.id} onOpenTask={onOpenTask}/></div></li>)}</ol><Pagination page={historyPage} total={history.data.total} label="检索历史分页" onPage={setHistoryPage} disabled={history.loading}/></>}
 </section>
 {searchId&&<section className="literature-panel" aria-label={t('已保存的检索条件')}><h3>{t('已保存的检索条件')}</h3>{search.loading&&<p role="status">{t('正在读取检索历史……')}</p>}{search.error&&<p role="alert">{t(search.error)}</p>}{search.data&&<><strong>{search.data.input.research_topic}</strong><p>{search.data.input.source_context.label}</p><p className="literature-original">{search.data.input.source_context.text}</p><FrozenConditions input={search.data.input}/><dl><dt>{t('原始检索式')}</dt><dd className="literature-original">{search.data.input.query}</dd><dt>{t('有效检索式')}</dt><dd className="literature-original">{search.data.effective_query}</dd><dt>{t('PubMed 转换检索式')}</dt><dd className="literature-original">{search.data.query_translation??t('尚未返回')}</dd><dt>{t('匹配与获取')}</dt><dd>{translateForLocale('匹配 {matched} 篇 · 已获取 {retrieved} 篇',search.data.input.output_language,{matched:search.data.matched_count??translateForLocale('尚未返回',search.data.input.output_language),retrieved:search.data.retrieved_count})}</dd></dl>{search.data.missing_pmids.length>0&&<p className="warning-panel">{translateForLocale('部分条目未返回：{pmids}',search.data.input.output_language,{pmids:search.data.missing_pmids.join(', ')})}</p>}{search.data.warnings.length>0&&<p className="warning-panel">{translateForLocale('PubMed 返回 {count} 条检索提示，请核对官方检索结果与原始来源。',search.data.input.output_language,{count:search.data.warnings.length})}</p>}<a href={`https://pubmed.ncbi.nlm.nih.gov/?term=${encodeURIComponent(search.data.effective_query)}`} target="_blank" rel="noopener noreferrer">{t('打开 PubMed 检索')}</a><TaskEntry projectId={projectId} taskId={search.data.task.id} onOpenTask={onOpenTask}/></>}</section>}
 <section className="literature-panel" aria-label={t('项目候选文献')}><div className="literature-actions"><h3>{t('项目候选文献')}</h3><label>{t('筛选候选状态')}<select value={selection} onChange={e=>{setSelection(e.target.value);setCandidatePage(1);setDetailId('')}}><option value="">{t('全部状态')}</option>{(['candidate','shortlisted','excluded'] as const).map(s=><option key={s} value={s}>{t(selectionName(s))}</option>)}</select></label>{searchId&&<button type="button" onClick={()=>chooseSearch('')}>{t('查看所有检索候选')}</button>}</div>
 <p className="muted">{t('入选不代表支持论述；全文入口不代表取得全文，DOI 入口不代表解析成功。')}</p>
 {candidates.loading&&<p role="status">{t('正在读取候选文献……')}</p>}{candidates.error&&<p role="alert">{t(candidates.error)}</p>}
 {candidates.data&&<>{!candidates.data.items.length&&<p>{t('当前条件下暂无候选文献。')}</p>}<ol className="literature-candidates">{candidates.data.items.map(item=><li key={item.id}><h4 className="literature-original">{item.record.title||t('题名未提供')}</h4><p>{item.record.authors.length?item.record.authors.join('; '):t('作者未提供')} · {item.record.year??t('年份未提供')} · {item.record.journal||t('期刊未提供')}</p><span className="task-status">{t(selectionName(item.selection.status))}</span><button type="button" onClick={()=>setDetailId(item.id)}>{t('查看候选详情')}</button></li>)}</ol><Pagination page={candidatePage} total={candidates.data.total} label="候选文献分页" onPage={p=>{setCandidatePage(p);setDetailId('')}} disabled={candidates.loading}/></>}
 </section>
 {detailId&&<CandidateDetail key={detailId} projectId={projectId} referenceId={detailId} searchId={searchId} onClose={()=>setDetailId('')} onChanged={refresh} onDenied={deny} onVerify={()=>setEvidenceOpen(true)}/>}
 </>}
 </section>
}
function publicationTypeLabel(type:string){return ({'Clinical Trial':'临床试验','Randomized Controlled Trial':'随机对照试验','Review':'综述','Systematic Review':'系统综述','Meta-Analysis':'荟萃分析','Observational Study':'观察性研究','Case Reports':'病例报告'} as Record<string,string>)[type]??type}
function FrozenConditions({input}:{input:SearchInput}){const t=(key:string,params:Record<string,string|number>={})=>translateForLocale(key,input.output_language,params);return <p lang={input.output_language}>{t('年份：{from}–{to}；类型：{types}；排序：{sort}；最多 {limit} 篇；输出：{language}。',{from:input.year_from??t('不限'),to:input.year_to??t('不限'),types:input.publication_types.length?input.publication_types.map(type=>t(publicationTypeLabel(type))).join('; '):t('不限'),sort:t(input.sort==='pub_date'?'发表日期':'相关性'),limit:input.limit,language:input.output_language==='en'?'English':t('简体中文')})}</p>}
function selectionName(status:Selection['status']){return {candidate:'候选',shortlisted:'人工入选',excluded:'人工排除'}[status]}
function TaskEntry({projectId,taskId,onOpenTask}:{projectId:string;taskId:string;onOpenTask?:Props['onOpenTask']}){const {t}=useI18n();return onOpenTask?<button type="button" onClick={()=>onOpenTask(taskId)}>{t('查看检索任务')}</button>:<a href={`#project=${encodeURIComponent(projectId)}&section=tasks&task=${encodeURIComponent(taskId)}`}>{t('查看检索任务')}</a>}
function SourceView({source}:{source:Source}){const {t,locale}=useI18n();return <div className="literature-source"><p>{source.source_kind==='synthetic_fixture'?t('合成测试资料'):'NCBI E-utilities'} · {new Date(source.retrieved_at).toLocaleString(locale)} · {t(source.cached?'复用已保存的来源回执':'已保存的来源记录')}</p><SavedSearchContext context={source.source_context}/><p>{t('原始检索式')}：<span className="literature-original">{source.query}</span></p><p>{t('有效检索式')}：<span className="literature-original">{source.effective_query}</span></p><ProjectDownloadLink href={source.source_download_url} filename="pubmed-source.xml">{t('下载原始 JSON/XML')}</ProjectDownloadLink></div>}
function CandidateDetail({projectId,referenceId,searchId,onClose,onChanged,onDenied,onVerify}:{projectId:string;referenceId:string;searchId:string;onClose:()=>void;onChanged:()=>void;onDenied:()=>void;onVerify:()=>void}){
 const {t}=useI18n();const [checksOpen,setChecksOpen]=useState(false);const [page,setPage]=useState(1);const [revision,setRevision]=useState(0);const [status,setStatus]=useState<Selection['status']>('candidate');const [note,setNote]=useState('');const [error,setError]=useState('');const [busy,setBusy]=useState(false)
 const request=useRef<AbortController|null>(null);const mounted=useRef(true);useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;request.current?.abort()}},[])
 const base=`${basePath(projectId)}/references/${encodeURIComponent(referenceId)}`
 const params=new URLSearchParams({page:String(page)});if(searchId)params.set('search_id',searchId)
 const detail=useResource<ReferenceDetail>(`${base}?${params}`,(v):v is ReferenceDetail=>validDetail(v,projectId,referenceId,page)&&(!searchId||v.source.search_id===searchId),revision,onDenied,data=>{setStatus(data.selection.status);setNote(data.selection.note);const last=Math.max(1,Math.ceil(data.sources.total/10));if(page>last)setPage(last)})
 async function save(){if(!detail.data||request.current||detail.loading)return;const controller=new AbortController();request.current=controller;setBusy(true);setError('')
 try{await literatureRequest(base,controller,(v):v is Reference=>validReference(v,projectId)&&v.id===referenceId,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_revision:detail.data.selection.revision,status,note})});if(mounted.current&&!controller.signal.aborted){setRevision(r=>r+1);onChanged()}}
 catch(cause){if(mounted.current){if(cause instanceof TaskRequestError&&cause.status===403)onDenied();setError(cause instanceof TaskRequestError&&cause.status===409?'候选状态已变化，已重新读取；请核对后再保存。':'筛选保存未确认，请重新读取后核对。');setRevision(r=>r+1);onChanged()}}
 finally{if(request.current===controller)request.current=null;if(mounted.current)setBusy(false)}
 }
 const item=detail.data,r=item?.record
 return <section className="literature-panel literature-detail" aria-label={t('候选文献详情')}><div className="literature-actions"><h3>{t('候选文献详情')}</h3><button type="button" onClick={onClose}>{t('关闭详情')}</button><button type="button" disabled={busy} onClick={()=>setRevision(v=>v+1)}>{t('重新读取候选详情')}</button></div>
 {detail.loading&&<p role="status">{t('正在读取候选文献……')}</p>}{detail.error&&<p role="alert">{t(detail.error)}</p>}{error&&<p role="alert" className="warning-panel">{t(error)}</p>}
 {item&&r&&<><h4 className="literature-original">{r.title||t('题名未提供')}</h4><p>{r.authors.length?r.authors.join('; '):t('作者未提供')} · {r.year??t('年份未提供')} · {r.journal||t('期刊未提供')}</p>
 <p className="muted">{t('本次检索未取得全文；项目上传材料见论述与证据。')}</p><div className="literature-statuses">{['全文未取得'].map(s=><span key={s}>{t(s)}</span>)}</div><h4>{t('原文摘要')}</h4>{r.abstract_status==='available'?r.abstract.map((a,i)=><p className="literature-original" key={i}>{a.label&&<strong>{a.label}: </strong>}{a.text}</p>):<p>{t(r.abstract_status==='not_returned'?'摘要未返回':'摘要为空')}</p>}
 <p>{t('关键词')}：{r.keywords.length?r.keywords.join('; '):t('未提供')}</p><p>MeSH：{r.mesh_terms.length?r.mesh_terms.join('; '):t('未提供')}</p>
 <div className="literature-actions"><a href={`https://pubmed.ncbi.nlm.nih.gov/${item.pmid}/`} target="_blank" rel="noopener noreferrer">{t('PubMed 原始条目')}</a>{r.doi?<a href={`https://doi.org/${encodeURIComponent(r.doi)}`} target="_blank" rel="noopener noreferrer">{t('DOI 未核验入口')}</a>:<span>{t('DOI 未提供')}</span>}{r.full_text_links.filter(l=>/^https:\/\/pmc\.ncbi\.nlm\.nih\.gov\/articles\/PMC[1-9][0-9]*\/$/.test(l.url)).map(l=><a key={l.url} href={l.url} target="_blank" rel="noopener noreferrer">{t('PMC 全文入口')}</a>)}</div>
 <button type="button" aria-expanded={checksOpen} onClick={()=>setChecksOpen(v=>!v)}>{t('查看三项核验与历史')}</button>{checksOpen&&<LiteratureChecks projectId={projectId} referenceId={referenceId} initialSearchId={searchId} onDenied={onDenied} onVerify={onVerify} onClose={()=>setChecksOpen(false)}/>}
 <h4>{t('当前条目快照来源')}</h4><SourceView source={item.source}/>
 <h4>{t('全部检索来源')}</h4>{item.sources.items.map((source,i)=><SourceView key={i} source={source}/>)}<Pagination page={page} total={item.sources.total} label="候选来源分页" onPage={setPage} disabled={busy||detail.loading}/>
 <fieldset disabled={busy||detail.loading}><legend>{t('人工筛选')}</legend><label>{t('人工筛选状态')}<select value={status} onChange={e=>setStatus(e.target.value as Selection['status'])}>{(['candidate','shortlisted','excluded'] as const).map(s=><option key={s} value={s}>{t(selectionName(s))}</option>)}</select></label><label>{t('筛选备注')}<textarea maxLength={2000} value={note} onChange={e=>setNote(e.target.value)}/></label><button type="button" className="button-primary" onClick={()=>void save()}>{t(busy?'正在保存筛选……':'保存人工筛选')}</button></fieldset>
 </>}
 </section>
}
