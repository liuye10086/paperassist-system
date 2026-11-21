import LiteratureChecks from './LiteratureChecks'
import EvidenceWorkspace from './EvidenceWorkspace'
import CitationWorkspace from './CitationWorkspace'
import SavedSearchContext from './SavedSearchContext'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { apiError, safeError, translateForLocale, useI18n } from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { isTask, isWorkspace, taskDisplayName, type TaskView, type TaskWorkspace } from '../tasks/taskTypes'
import { TaskRequestError } from '../tasks/taskApi'
import TaskPendingAction from '../tasks/TaskPendingAction'
import { basePath, literatureRequest, publicationTypes, validConfig, validDetail, validPage, validReference, validSearch, validSearchInput, type Configuration, type Page, type Reference, type ReferenceDetail, type Search, type SearchInput, type Selection, type Source } from './literatureApi'
import type { LiteratureNavigation, LiteratureView } from '../projects/literatureViews'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import {LiteratureActivity} from './LiteratureActivity'
import {useLiteratureActive,useLiteratureLeaveGuard} from './literatureActivityContext'
import { suggestManualPubMedQuery, suggestPubMedQuery } from './pubmedKeywords'
import { citationBase, citationPage, validCandidate, type Candidate } from './citationApi'
import './literature.css'
type Props={customerSci?:boolean;projectKeywords?:readonly string[];/** A paragraph waits for a reference (B03 task 7): called once one is shortlisted with a usable bibliography. */onReferenceReady?:(referenceId:string)=>void;projectId:string;researchTopic:string;outputLanguage?:string;active:boolean;initialSearchId?:string;onOpenTask?:(id:string)=>void;onSearchChange?:(id:string)=>void;literatureNavigation?:LiteratureNavigation;onLiteratureNavigate?:(next:LiteratureNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}
export default function ProjectLiterature(props:Props){return <Scope key={props.projectId} {...props}/>}
function Scope(props:Props){const {t}=useI18n();const [valid,setValid]=useState(true);const [visited,setVisited]=useState(props.active);if(props.active&&!visited)setVisited(true);useEffect(()=>onApiSessionChanged(()=>setValid(false)),[]);return valid?visited?<div hidden={!props.active}><LiteratureActivity active={props.active} register={props.registerLeaveGuard}><Literature {...props}/></LiteratureActivity></div>:null:<p hidden={!props.active} role="alert">{t('会话已失效，请重新登录。')}</p>}
function useResource<T>(url:string|null,valid:(v:unknown)=>v is T,revision:number,onDenied:()=>void,onLoaded?:(data:T)=>void){
 const enabled=useLiteratureActive();const loaded=useRef<string|null>(null)
 const key=url===null?null:JSON.stringify([url,revision])
 const [state,setState]=useState<{key:string|null;data:T|null;error:string;loading:boolean}>({key:null,data:null,error:'',loading:false})
 const callbacks=useRef({valid,onDenied,onLoaded});useEffect(()=>{callbacks.current={valid,onDenied,onLoaded}})
 useEffect(()=>{if(!url){loaded.current=null;return}if(!enabled||loaded.current===key)return;loaded.current=null;let active=true;const controller=new AbortController()
 void literatureRequest(url,controller,v=>callbacks.current.valid(v)).then(data=>{if(active&&!controller.signal.aborted){loaded.current=key;setState({key,data,error:'',loading:false});callbacks.current.onLoaded?.(data)}}).catch(cause=>{if(!active)return;if(cause instanceof TaskRequestError&&cause.status===403)callbacks.current.onDenied();setState({key,data:null,error:safeError(cause,'文献资料读取失败，请重试。'),loading:false})})
 return()=>{active=false;controller.abort()}
 },[url,revision,key,enabled])
 return state.key===key?state:{key,data:null,error:'',loading:!!url}
}
function Pagination({page,total,label,onPage,disabled=false}:{page:number;total:number;label:string;onPage:(p:number)=>void;disabled?:boolean}){const {t}=useI18n();const pages=Math.max(1,Math.ceil(total/10));return <nav className="literature-pagination" aria-label={t(label)}><span>{t('共 {total} 项 · 第 {page} / {pages} 页',{total,page,pages})}</span><button type="button" disabled={disabled||page<=1} onClick={()=>onPage(page-1)}>{t('上一页')}</button><button type="button" disabled={disabled||page>=pages} onClick={()=>onPage(page+1)}>{t('下一页')}</button></nav>}
function Literature({projectId,researchTopic,outputLanguage,onOpenTask,initialSearchId,onSearchChange,literatureNavigation,onLiteratureNavigate,customerSci=false,projectKeywords=[],onReferenceReady}:Props){
 const {t,locale}=useI18n();const base=basePath(projectId)
 // A shortlisted reference whose bibliography still needs checking; the citation list reports when it becomes usable.
 const [waitingReference,setWaitingReference]=useState('');const readyReported=useRef(false)
 const ready=(c:Candidate|undefined)=>!!c&&c.selection.status==='shortlisted'&&c.metadata?.usable===true
 function reportReady(id:string){if(readyReported.current||!onReferenceReady)return;readyReported.current=true;setWaitingReference('');onReferenceReady(id)}
 async function checkReady(id:string){
  const controller=new AbortController()
  try{for(let page=1;page<=10;page++){const result=await literatureRequest(`${citationBase(projectId)}/candidates?page=${page}`,controller,citationPage(projectId,page,validCandidate));const found=result.items.find(c=>c.id===id);if(found){if(ready(found)){reportReady(id);return}break}if(page*result.page_size>=result.total)break}}catch{/* an unreadable list keeps the customer here with the notice */}
  if(mounted.current)setWaitingReference(id)
 }
 function selectionSaved(id:string,status:Selection['status']){if(onReferenceReady&&status==='shortlisted')void checkReady(id)}
 function candidatesLoaded(items:Candidate[]){if(waitingReference&&ready(items.find(c=>c.id===waitingReference)))reportReady(waitingReference)}
 const queryHint=useId()
 const keywordSuggestion=suggestPubMedQuery(projectKeywords)
 const [localNavigation,setLocalNavigation]=useState<LiteratureNavigation>({view:'list',referenceId:''});const navigation=literatureNavigation??localNavigation;const view=navigation.view;
 const [visited,setVisited]=useState<Set<LiteratureView>>(()=>new Set([view]));
 const [details,setDetails]=useState<{referenceId:string;searchId:string}[]>([]);
 function navigate(next:LiteratureNavigation){setLocalNavigation(next);onLiteratureNavigate?.(next)}
 if(!visited.has(view))setVisited(new Set([...visited,view]));
 const [denied,setDenied]=useState(false);const deny=()=>setDenied(true)
 const [revision,setRevision]=useState(0);const [historyPage,setHistoryPage]=useState(1);const [candidatePage,setCandidatePage]=useState(1)
 const [localSearchId,setSearchId]=useState(initialSearchId??'');const searchId=initialSearchId===undefined?localSearchId:initialSearchId;const [selection,setSelection]=useState('');const detailId=navigation.referenceId;
 const [previousSearch,setPreviousSearch]=useState(initialSearchId);if(previousSearch!==initialSearchId){setPreviousSearch(initialSearchId);setSearchId(initialSearchId??'');setCandidatePage(1)}
 if(view==='detail'&&detailId&&!details.some(d=>d.referenceId===detailId&&d.searchId===searchId))setDetails([...details,{referenceId:detailId,searchId}])
 const [input,setInput]=useState<SearchInput>({research_topic:researchTopic,source_context:{kind:'project_topic',label:'',text:researchTopic},query:keywordSuggestion.query,year_from:null,year_to:null,publication_types:[],sort:'relevance',limit:20,output_language:outputLanguage==='en'?'en':'zh-CN'})
 const manualSuggestion=suggestManualPubMedQuery(input.query)
 const queryTranslation=manualSuggestion&&!manualSuggestion.omitted.length?manualSuggestion.query:''
 const [inputBaseline,setInputBaseline]=useState(JSON.stringify(input));const [uncertain,setUncertain]=useState(false);
 const [busy,setBusy]=useState(false);useLiteratureLeaveGuard(JSON.stringify(input)!==inputBaseline||uncertain,busy);const [error,setError]=useState('');const [saved,setSaved]=useState<TaskView|null>(null)
 const replay=useRef<{signature:string;key:string}|null>(null);const request=useRef<AbortController|null>(null);const mounted=useRef(true)
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;request.current?.abort()}},[])
 const config=useResource<Configuration>(denied?null:`${base}/config`,validConfig,revision,deny)
 const history=useResource<Page<Search>>(denied?null:`${base}/searches?page=${historyPage}`,v=>validPage(v,projectId,historyPage,x=>validSearch(x,projectId)),revision,deny,data=>{const last=Math.max(1,Math.ceil(data.total/10));if(historyPage>last)setHistoryPage(last)})
 const search=useResource<Search>(!denied&&searchId?`${base}/searches/${encodeURIComponent(searchId)}`:null,(v):v is Search=>validSearch(v,projectId)&&v.id===searchId,revision,deny)
 const selectedSearch=search.data
 const recoveryId=view==='list'&&selectedSearch&&['failed','waiting_confirmation'].includes(selectedSearch.task.status) ? selectedSearch.id : null
 const recovery=useResource<TaskWorkspace>(recoveryId?'/api/v1/tasks/'+encodeURIComponent(recoveryId)+'/workspace':null,
  (v):v is TaskWorkspace=>!!recoveryId&&isWorkspace(v,projectId,recoveryId),revision,deny)
 const params=new URLSearchParams({page:String(candidatePage)});if(searchId)params.set('search_id',searchId);if(selection)params.set('selection',selection)
 const candidates=useResource<Page<Reference>>(denied?null:`${base}/references?${params}`,v=>validPage(v,projectId,candidatePage,x=>validReference(x,projectId)),revision,deny,data=>{const last=Math.max(1,Math.ceil(data.total/10));if(candidatePage>last)setCandidatePage(last)})
 function refresh(){setRevision(r=>r+1)}
 function chooseSearch(id:string){setSearchId(id);onSearchChange?.(id);setCandidatePage(1);navigate({view:'list',referenceId:''})}
 function edit<K extends keyof SearchInput>(key:K,value:SearchInput[K]){setInput(old=>({...old,[key]:value}));setSaved(null);setError('')}
 function editSavedSearch(search:Search){
  setInput(structuredClone(search.input));setSaved(null);setError('')
  navigate({view:'search',referenceId:''})
 }
 async function create(event:FormEvent){event.preventDefault();if(request.current||denied)return
 const body={...input,research_topic:input.research_topic.trim(),query:queryTranslation||input.query.trim()}
 if(!validSearchInput(body)){setError('请检查研究主题、检索式和年份范围。');return}
 const signature=JSON.stringify(body);if(replay.current?.signature!==signature)replay.current={signature,key:crypto.randomUUID()}
 const controller=new AbortController();request.current=controller;setBusy(true);setError('');setSaved(null)
 try{const task=await literatureRequest(`${base}/searches`,controller,(v):v is TaskView=>isTask(v,projectId)&&v.task_type==='literature_search',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':replay.current.key},body:signature});if(mounted.current&&!controller.signal.aborted){replay.current=null;setSaved(task);setInput(body);setInputBaseline(signature);setUncertain(false);refresh()}}
 catch(cause){if(mounted.current){
  const rejected=cause instanceof TaskRequestError&&cause.status>=400&&cause.status<500
  if(cause instanceof TaskRequestError&&cause.status===403)deny()
  if(rejected)replay.current=null
  setUncertain(!rejected)
  setError(rejected?safeError(cause,'检索保存失败，请核对后重试。'):'检索提交结果未确认，请先刷新历史；相同输入重试沿用请求标识。')
 }}
 finally{if(request.current===controller)request.current=null;if(mounted.current)setBusy(false)}
 }
 if(denied)return <p className="error-panel" role="alert">{t('项目不存在或无权访问。')}</p>
 return <section className="literature-workspace" aria-label={t('项目文献')}>
 <div className="workspace-page-heading"><div><span className="workspace-eyebrow">PubMed</span><h2>{t('文献')}</h2></div><button type="button" onClick={refresh}>{t('刷新文献记录')}</button></div>
 <nav className="literature-view-switcher" aria-label={t('文献任务视图')}>{([['list','候选列表'],['search','新建文献检索'],['history','检索历史'],['evidence','论述与证据核验'],['citations','引用工作台']] as const).map(([target,label])=><button key={target} type="button" aria-pressed={view===target} onClick={()=>navigate({view:target,referenceId:''})}>{t(label)}</button>)}</nav>
 {waitingReference&&onReferenceReady&&<p role="status" className="warning-panel">{t('还需核对这篇文献的书目信息，完成后会自动回到本段。')}</p>}
 {(visited.has('evidence')||view==='evidence')&&<div hidden={view!=='evidence'}><LiteratureActivity active={view==='evidence'}><EvidenceWorkspace projectId={projectId} researchTopic={researchTopic} outputLanguage={outputLanguage} customerSci={customerSci} onOpenTask={onOpenTask} onDenied={deny}/></LiteratureActivity></div>}
 {(visited.has('citations')||view==='citations')&&<div hidden={view!=='citations'}><LiteratureActivity active={view==='citations'}><CitationWorkspace projectId={projectId} outputLanguage={outputLanguage} customerSci={customerSci} onCandidates={onReferenceReady?candidatesLoaded:undefined} onVerify={()=>navigate({view:'evidence',referenceId:''})} onDenied={deny}/></LiteratureActivity></div>}
 <div hidden={view!=='search'} className="literature-task-view">
 {config.loading&&<p role="status">{t('正在读取文献配置……')}</p>}{config.error&&<p role="alert">{t(config.error)}</p>}
 {config.data&&<p className="warning-panel">{t(config.data.available?'本机 NCBI 配置已启用；检索结果以实际任务回执为准。':'NCBI 当前关闭；已保存结果仍可查看。新检索任务将持久等待配置。')}</p>}
 <form className="project-form literature-form" aria-label={t('文献检索条件')} onSubmit={event=>void create(event)}>
 <fieldset disabled={busy}><legend>{t('研究主题与来源')}</legend>
 <label>{t('研究主题')}<textarea required maxLength={2000} value={input.research_topic} onChange={e=>edit('research_topic',e.target.value)} /></label>
 <div className="project-fields"><label>{t('来源类型')}<select value={input.source_context.kind} onChange={e=>edit('source_context',{...input.source_context,kind:e.target.value as SearchInput['source_context']['kind']})}><option value="project_topic">{t('项目研究主题')}</option><option value="section">{t('论文章节')}</option>{!customerSci&&<option value="feedback">{t('导师或审稿反馈')}</option>}</select></label><label>{t('来源标签')}<input maxLength={200} value={input.source_context.label} onChange={e=>edit('source_context',{...input.source_context,label:e.target.value})}/></label></div>
 <label>{t('来源文本快照')}<textarea maxLength={6000} value={input.source_context.text} onChange={e=>edit('source_context',{...input.source_context,text:e.target.value})}/></label>
 <p className="muted">{t('检索依据按本次填写保存，后续修改不会改写历史。')}</p>
 <div className="literature-search-query">
   <label>{t('PubMed 检索式')}<textarea required maxLength={4000} value={input.query} onChange={e=>edit('query',e.target.value)}
     aria-describedby={queryHint} placeholder="single cell RNA sequencing AND (batch effects OR batch correction)"/></label>
   <div id={queryHint} className="muted literature-search-query">
     {keywordSuggestion.hasSecondaryTerms && <small>{t('项目关键词建议式匹配第一个可用概念和任一其他可用概念。')}</small>}
     {keywordSuggestion.omitted.length>0 && <small>{t('建议式暂缺这些关键词的英文写法（{keywords}）。请补充到检索式中。', {keywords:keywordSuggestion.omitted.join(' · ')})}</small>}
     {keywordSuggestion.tooLong && <small>{t('关键词建议式超过 4000 字符，请选取主要概念填写检索式。')}</small>}
     {queryTranslation&&<small>{t('检索将使用以下英文词组')} <span>{queryTranslation}</span></small>}
     {!!manualSuggestion?.omitted.length&&<small>{t('请为这些手填关键词补充英文写法（{keywords}）。',{keywords:manualSuggestion.omitted.join(' · ')})}</small>}
     <small>{t('可直接填写英文检索词、PubMed 字段标签或 PMID。')}</small>
   </div>
   {keywordSuggestion.query && input.query!==keywordSuggestion.query && <button type="button" onClick={()=>edit('query',keywordSuggestion.query)}>
     {t('填入项目关键词建议式')}
   </button>}
 </div>
 <div className="literature-condition-grid"><label>{t('起始年份')}<input type="number" min={1800} max={3000} step={1} placeholder={t('不限')} value={input.year_from??''} onChange={e=>edit('year_from',e.target.value===''?null:Number(e.target.value))}/></label><label>{t('结束年份')}<input type="number" min={1800} max={3000} step={1} placeholder={t('不限')} value={input.year_to??''} onChange={e=>edit('year_to',e.target.value===''?null:Number(e.target.value))}/></label>
 <label>{t('排序方式')}<select value={input.sort} onChange={e=>edit('sort',e.target.value as SearchInput['sort'])}><option value="relevance">{t('相关性')}</option><option value="pub_date">{t('发表日期')}</option></select></label>
 <label>{t('候选数量上限')}<select value={input.limit} onChange={e=>edit('limit',Number(e.target.value) as SearchInput['limit'])}>{[20,50,100].map(n=><option key={n} value={n}>{n}</option>)}</select></label>
 <label>{t('检索输出语言')}<select value={input.output_language} onChange={e=>edit('output_language',e.target.value as SearchInput['output_language'])}><option value="zh-CN">{t('简体中文')}</option><option value="en">English</option></select></label></div>
 <fieldset className="literature-types"><legend>{t('文献类型（默认不限）')}</legend>{publicationTypes.map(type=><label key={type}><input type="checkbox" checked={input.publication_types.includes(type)} onChange={e=>edit('publication_types',e.target.checked?[...input.publication_types,type]:input.publication_types.filter(v=>v!==type))}/>{t(publicationTypeLabel(type))}</label>)}</fieldset>
 <p className="muted"><a href="https://www.ncbi.nlm.nih.gov/About/disclaimer.html" target="_blank" rel="noopener noreferrer">{t('NCBI 使用与版权说明')}</a></p>
 <p className="muted">{t('PubMed 主要覆盖生物医学，全文可得性以实际取得为准。')}</p>
 <button type="submit" className="button-primary">{t(busy?'正在保存检索……':'保存检索并创建任务')}</button>
 </fieldset></form>
 {error&&<p role="alert" className="error-panel">{t(error)}</p>}{saved&&<div><p role="status">{t('检索任务已保存。')}</p>
   <div className="literature-actions"><button type="button" onClick={()=>chooseSearch(saved.id)}>{t('查看本次检索')}</button>
     <TaskEntry customerSci={customerSci} projectId={projectId} taskId={saved.id} onOpenTask={onOpenTask}/></div>
 </div>}
 </div>
 <div hidden={view!=='history'} className="literature-task-view">
 <section className="literature-panel" aria-label={t('检索历史')}>{history.loading&&<p role="status">{t('正在读取检索历史……')}</p>}{history.error&&<p role="alert">{t(history.error)}</p>}
 {history.data&&<>{!history.data.items.length&&<p>{t('尚无检索记录。')}</p>}<ol className="literature-history">{history.data.items.map(item=><li key={item.id}><strong>{item.input.research_topic}</strong><p className="literature-original">{item.input.query}</p><span>{translateForLocale(taskDisplayName(item.task),item.input.output_language)} · {new Date(item.created_at).toLocaleString(locale)} · {translateForLocale('已获取 {count} 篇',item.input.output_language,{count:item.retrieved_count})}</span><div className="literature-actions"><button type="button" onClick={()=>chooseSearch(item.id)}>{t('查看本次检索')}</button><button type="button" disabled={busy} onClick={()=>editSavedSearch(item)}>{t('编辑后重新检索')}</button><TaskEntry customerSci={customerSci} projectId={projectId} taskId={item.task.id} onOpenTask={onOpenTask}/></div></li>)}</ol><Pagination page={historyPage} total={history.data.total} label="检索历史分页" onPage={setHistoryPage} disabled={history.loading}/></>}
 </section>
 </div>
 <div hidden={view!=='list'} className="literature-task-view">
 {searchId&&<section className="literature-panel" aria-label={t('已保存的检索条件')}>
   <h3>{t('已保存的检索条件')}</h3>
   {search.loading&&<p role="status">{t('正在读取检索历史……')}</p>}
   {search.error&&<p role="alert">{t(search.error)}</p>}
   {selectedSearch&&<>
     <strong>{selectedSearch.input.research_topic}</strong>
     <p>{selectedSearch.input.source_context.label}</p>
     <p className="literature-original">{selectedSearch.input.source_context.text}</p>
     <FrozenConditions input={selectedSearch.input}/>
     <dl>
       <dt>{t('原始检索式')}</dt><dd className="literature-original">{selectedSearch.input.query}</dd>
       <dt>{t('有效检索式')}</dt><dd className="literature-original">{selectedSearch.effective_query}</dd>
       <dt>{t('PubMed 转换检索式')}</dt><dd className="literature-original">{selectedSearch.query_translation??t('尚未返回')}</dd>
       <dt>{t('匹配与获取')}</dt>
       <dd>{translateForLocale('匹配 {matched} 篇 · 已获取 {retrieved} 篇',selectedSearch.input.output_language,{
         matched:selectedSearch.matched_count??translateForLocale('尚未返回',selectedSearch.input.output_language),
         retrieved:selectedSearch.retrieved_count,
       })}</dd>
     </dl>
     {selectedSearch.task.status==='failed'&&<p className="error-panel" role="alert">
       {t(apiError({code:selectedSearch.task.error_code},'检索未完成，请核对条件后重试。'))}
     </p>}
     {recovery.error&&<p role="alert">{t(recovery.error)}</p>}
     {recovery.data&&<TaskPendingAction workspace={recovery.data} blocked={busy} onChanged={refresh}/>}
     {selectedSearch.matched_count===0&&<p className="warning-panel">{t('当前检索条件匹配 0 篇。可保留主要概念、替换同义词或放宽年份和文献类型，再保存为新的检索。')}</p>}
     {selectedSearch.missing_pmids.length>0&&<p className="warning-panel">{translateForLocale('部分条目未返回：{pmids}',selectedSearch.input.output_language,{pmids:selectedSearch.missing_pmids.join(', ')})}</p>}
     {selectedSearch.warnings.length>0&&<p className="warning-panel">{translateForLocale('PubMed 返回 {count} 条检索提示，请核对官方检索结果与原始来源。',selectedSearch.input.output_language,{count:selectedSearch.warnings.length})}</p>}
     <div className="literature-actions">
       {(selectedSearch.matched_count===0||selectedSearch.task.status==='failed')&&<button type="button" disabled={busy} onClick={()=>editSavedSearch(selectedSearch)}>{t('编辑后重新检索')}</button>}
       <a href={`https://pubmed.ncbi.nlm.nih.gov/?term=${encodeURIComponent(selectedSearch.effective_query)}`} target="_blank" rel="noopener noreferrer">{t('打开 PubMed 检索')}</a>
       <TaskEntry customerSci={customerSci} projectId={projectId} taskId={selectedSearch.task.id} onOpenTask={onOpenTask}/>
     </div>
   </>}
 </section>}
 <section className="literature-panel" aria-label={t('项目候选文献')}><div className="literature-actions"><h3>{t('项目候选文献')}</h3><label>{t('筛选候选状态')}<select value={selection} onChange={e=>{setSelection(e.target.value);setCandidatePage(1)}}><option value="">{t('全部状态')}</option>{(['candidate','shortlisted','excluded'] as const).map(s=><option key={s} value={s}>{t(selectionName(s))}</option>)}</select></label>{searchId&&<button type="button" onClick={()=>chooseSearch('')}>{t('查看所有检索候选')}</button>}</div>
 <p className="muted">{t('入选不代表支持论述；全文入口不代表取得全文，DOI 入口不代表解析成功。')}</p>
 {candidates.loading&&<p role="status">{t('正在读取候选文献……')}</p>}{candidates.error&&<p role="alert">{t(candidates.error)}</p>}
 {candidates.data&&<>{!candidates.data.items.length&&<p>{t('当前条件下暂无候选文献。')}</p>}<ol className="literature-candidates">{candidates.data.items.map(item=><li key={item.id}><h4 className="literature-original">{item.record.title||t('题名未提供')}</h4><p>{item.record.authors.length?item.record.authors.join('; '):t('作者未提供')} · {item.record.year??t('年份未提供')} · {item.record.journal||t('期刊未提供')}</p><span className="task-status">{t(selectionName(item.selection.status))}</span><button type="button" onClick={()=>navigate({view:'detail',referenceId:item.id})}>{t('查看候选详情')}</button></li>)}</ol><Pagination page={candidatePage} total={candidates.data.total} label="候选文献分页" onPage={setCandidatePage} disabled={candidates.loading}/></>}
 </section>
 </div>
 {[...details,...(view==='detail'&&detailId&&!details.some(d=>d.referenceId===detailId&&d.searchId===searchId)?[{referenceId:detailId,searchId}]:[])].map(d=><div key={`${d.referenceId}:${d.searchId}`} hidden={view!=='detail'||detailId!==d.referenceId||searchId!==d.searchId}><LiteratureActivity active={view==='detail'&&detailId===d.referenceId&&searchId===d.searchId}><CandidateDetail projectId={projectId} customerSci={customerSci} referenceId={d.referenceId} searchId={d.searchId} onClose={()=>navigate({view:'list',referenceId:''})} onChanged={refresh} onSaved={status=>selectionSaved(d.referenceId,status)} onDenied={deny} onVerify={()=>navigate({view:'evidence',referenceId:''})}/></LiteratureActivity></div>)}
 </section>
}
function publicationTypeLabel(type:string){return ({'Clinical Trial':'临床试验','Randomized Controlled Trial':'随机对照试验','Review':'综述','Systematic Review':'系统综述','Meta-Analysis':'荟萃分析','Observational Study':'观察性研究','Case Reports':'病例报告'} as Record<string,string>)[type]??type}
function FrozenConditions({input}:{input:SearchInput}){const t=(key:string,params:Record<string,string|number>={})=>translateForLocale(key,input.output_language,params);return <p lang={input.output_language}>{t('年份：{from}–{to}；类型：{types}；排序：{sort}；最多 {limit} 篇；输出：{language}。',{from:input.year_from??t('不限'),to:input.year_to??t('不限'),types:input.publication_types.length?input.publication_types.map(type=>t(publicationTypeLabel(type))).join('; '):t('不限'),sort:t(input.sort==='pub_date'?'发表日期':'相关性'),limit:input.limit,language:input.output_language==='en'?'English':t('简体中文')})}</p>}
function selectionName(status:Selection['status']){return {candidate:'候选',shortlisted:'人工入选',excluded:'人工排除'}[status]}
function TaskEntry({projectId,taskId,onOpenTask,customerSci}:{customerSci:boolean;projectId:string;taskId:string;onOpenTask?:Props['onOpenTask']}){const {t}=useI18n();return customerSci?null:onOpenTask?<button type="button" onClick={()=>onOpenTask(taskId)}>{t('查看检索任务')}</button>:<a href={`#project=${encodeURIComponent(projectId)}&section=tasks&task=${encodeURIComponent(taskId)}`}>{t('查看检索任务')}</a>}
function SourceView({source,customer}:{source:Source;customer:boolean}) {
 const {t,locale}=useI18n()
 const sourceName=source.source_kind==='synthetic_fixture'?t('合成测试资料'):customer?'PubMed':'NCBI E-utilities'
 return <div className="literature-source">
  <p>{sourceName} · {new Date(source.retrieved_at).toLocaleString(locale)} · {t(source.cached?'复用已保存的来源回执':'已保存的来源记录')}</p>
  <SavedSearchContext context={source.source_context}/>
  <p>{t('原始检索式')}：<span className="literature-original">{source.query}</span></p>
  <p>{t('有效检索式')}：<span className="literature-original">{source.effective_query}</span></p>
  {!customer&&<ProjectDownloadLink href={source.source_download_url} filename="pubmed-source.xml">{t('下载原始 JSON/XML')}</ProjectDownloadLink>}
 </div>
}
function CandidateDetail({projectId,referenceId,searchId,onClose,onChanged,onSaved,onDenied,onVerify,customerSci=false}:{customerSci?:boolean;projectId:string;referenceId:string;searchId:string;onClose:()=>void;onChanged:()=>void;onSaved?:(status:Selection['status'])=>void;onDenied:()=>void;onVerify:()=>void}){
 const {t}=useI18n();const [checksOpen,setChecksOpen]=useState(false);const [detailView,setDetailView]=useState('overview');const [page,setPage]=useState(1);const [revision,setRevision]=useState(0);const [status,setStatus]=useState<Selection['status']>('candidate');const [note,setNote]=useState('');const [error,setError]=useState('');const [busy,setBusy]=useState(false)
 const [dirty,setDirty]=useState(false);const dirtyRef=useRef(false);const [editorRevision,setEditorRevision]=useState<number|null>(null);const [uncertain,setUncertain]=useState(false);useLiteratureLeaveGuard(dirty||uncertain,busy);
 const request=useRef<AbortController|null>(null);const mounted=useRef(true);useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;request.current?.abort()}},[])
 const base=`${basePath(projectId)}/references/${encodeURIComponent(referenceId)}`
 const params=new URLSearchParams({page:String(page)});if(searchId)params.set('search_id',searchId)
 const detail=useResource<ReferenceDetail>(`${base}?${params}`,(v):v is ReferenceDetail=>validDetail(v,projectId,referenceId,page)&&(!searchId||v.source.search_id===searchId),revision,onDenied,data=>{if(!dirtyRef.current){setStatus(data.selection.status);setNote(data.selection.note);setEditorRevision(data.selection.revision)}const last=Math.max(1,Math.ceil(data.sources.total/10));if(page>last)setPage(last)})
 async function save(){if(!detail.data||request.current||detail.loading)return;const controller=new AbortController();request.current=controller;setBusy(true);setError('')
 try{await literatureRequest(base,controller,(v):v is Reference=>validReference(v,projectId)&&v.id===referenceId,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_revision:editorRevision??detail.data.selection.revision,status,note})});if(mounted.current&&!controller.signal.aborted){dirtyRef.current=false;setDirty(false);setUncertain(false);setRevision(r=>r+1);onChanged();onSaved?.(status)}}
 catch(cause){if(mounted.current){if(cause instanceof TaskRequestError&&cause.status===403)onDenied();setUncertain(!(cause instanceof TaskRequestError&&cause.status===409));setError(cause instanceof TaskRequestError&&cause.status===409?'候选状态已变化，已重新读取；请核对后再保存。':'筛选保存未确认，请重新读取后核对。');setRevision(r=>r+1);onChanged()}}
 finally{if(request.current===controller)request.current=null;if(mounted.current)setBusy(false)}
 }
 const item=detail.data,r=item?.record
 return <section className="literature-panel literature-detail" aria-label={t('候选文献详情')}><div className="literature-actions"><h3>{t('候选文献详情')}</h3><button type="button" onClick={onClose}>{t('关闭详情')}</button><button type="button" disabled={busy} onClick={()=>setRevision(v=>v+1)}>{t('重新读取候选详情')}</button></div>
 {detail.loading&&<p role="status">{t('正在读取候选文献……')}</p>}{detail.error&&<p role="alert">{t(detail.error)}</p>}{error&&<p role="alert" className="warning-panel">{t(error)}</p>}{dirty&&<p className="muted">{t('候选筛选有未保存修改，切换视图会保留。')}</p>}{(dirty||uncertain)&&<button type="button" disabled={busy} onClick={()=>{dirtyRef.current=false;setDirty(false);setUncertain(false);setRevision(r=>r+1)}}>{t('载入服务器筛选（替换本地编辑）')}</button>}
 {item&&r&&<><h4 className="literature-original">{r.title||t('题名未提供')}</h4><p>{r.authors.length?r.authors.join('; '):t('作者未提供')} · {r.year??t('年份未提供')} · {r.journal||t('期刊未提供')}</p>
 <nav className="literature-view-switcher" aria-label={t('候选详情视图')}>{([['overview','摘要概览'],['selection','人工筛选'],['sources','来源记录'],['checks','三项核验']] as const).map(([value,label])=><button key={value} type="button" aria-pressed={detailView===value} onClick={()=>{setDetailView(value);if(value==='checks')setChecksOpen(true)}}>{t(label)}</button>)}</nav>
 <div hidden={detailView!=='overview'}>
 <p className="muted">{t('本次检索未取得全文；项目上传材料见论述与证据。')}</p><div className="literature-statuses">{['全文未取得'].map(s=><span key={s}>{t(s)}</span>)}</div><h4>{t('原文摘要')}</h4>{r.abstract_status==='available'?r.abstract.map((a,i)=><p className="literature-original" key={i}>{a.label&&<strong>{a.label}: </strong>}{a.text}</p>):<p>{t(r.abstract_status==='not_returned'?'摘要未返回':'摘要为空')}</p>}
 <p>{t('关键词')}：{r.keywords.length?r.keywords.join('; '):t('未提供')}</p><p>MeSH：{r.mesh_terms.length?r.mesh_terms.join('; '):t('未提供')}</p>
 <div className="literature-actions"><a href={`https://pubmed.ncbi.nlm.nih.gov/${item.pmid}/`} target="_blank" rel="noopener noreferrer">{t('PubMed 原始条目')}</a>{r.doi?<a href={`https://doi.org/${encodeURIComponent(r.doi)}`} target="_blank" rel="noopener noreferrer">{t('DOI 未核验入口')}</a>:<span>{t('DOI 未提供')}</span>}{r.full_text_links.filter(l=>/^https:\/\/pmc\.ncbi\.nlm\.nih\.gov\/articles\/PMC[1-9][0-9]*\/$/.test(l.url)).map(l=><a key={l.url} href={l.url} target="_blank" rel="noopener noreferrer">{t('PMC 全文入口')}</a>)}</div>
 <button type="button" aria-pressed={detailView==='checks'} onClick={()=>{setChecksOpen(true);setDetailView('checks')}}>{t('查看三项核验与历史')}</button></div><div hidden={detailView!=='checks'}>{checksOpen&&<LiteratureActivity active={detailView==='checks'}><LiteratureChecks projectId={projectId} referenceId={referenceId} initialSearchId={searchId} customerSci={customerSci} onDenied={onDenied} onVerify={onVerify} onClose={()=>setDetailView('overview')}/></LiteratureActivity>}</div>
 <div hidden={detailView!=='sources'}>
 <h4>{t('当前条目快照来源')}</h4><SourceView source={item.source} customer={customerSci}/>
 <h4>{t('全部检索来源')}</h4>{item.sources.items.map((source,i)=><SourceView key={i} source={source} customer={customerSci}/>)}<Pagination page={page} total={item.sources.total} label="候选来源分页" onPage={setPage} disabled={busy||detail.loading}/>
 </div>
 <div hidden={detailView!=='selection'}>
 <fieldset disabled={busy||detail.loading}><legend>{t('人工筛选')}</legend><label>{t('人工筛选状态')}<select value={status} onChange={e=>{dirtyRef.current=true;setDirty(true);setStatus(e.target.value as Selection['status'])}}>{(['candidate','shortlisted','excluded'] as const).map(s=><option key={s} value={s}>{t(selectionName(s))}</option>)}</select></label><label>{t('筛选备注')}<textarea maxLength={2000} value={note} onChange={e=>{dirtyRef.current=true;setDirty(true);setNote(e.target.value)}}/></label><button type="button" className="button-primary" onClick={()=>void save()}>{t(busy?'正在保存筛选……':'保存人工筛选')}</button></fieldset>
 </div></>}
 </section>
}
