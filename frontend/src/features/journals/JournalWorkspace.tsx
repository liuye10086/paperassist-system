import {useCallback,useEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError,useI18n} from '../../shared/i18n'
import {taskRequest,TaskRequestError} from '../tasks/taskApi'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import JournalFormatPanel from './JournalFormatPanel'
import JournalAdaptationPanel from './JournalAdaptationPanel'
import JournalSubmissionPanel from './JournalSubmissionPanel'
import {isAdaptation,isAdaptationPreview,isSubmissionEvent,isSubmissionHistory,type Adaptation,type AdaptationPreview,type AdaptationRequest,type AdoptRequest,type SubmissionEvent,type SubmissionHistory,type SubmissionRequest} from './adaptationContracts'
import {isGuide,isTarget,isFormatCheck,type Guide,type GuideRequest,type Target,type TargetRequest,type FormatCheck} from './formatContracts'
import JournalSourceForm from './JournalSourceForm'
import JournalResearchForm from './JournalResearchForm'
import JournalResults,{JournalProfile} from './JournalResults'
import {isProfile,isRecommendation,record,syntheticLabel,type MaterialCandidate,type ManuscriptChoice,type Profile,type ProfileRequest,type Recommendation,type Research} from './contracts'
import './journals.css'
type Props={projectId:string;active:boolean;onOpenTask?:(id:string)=>void}
const formatFailure='指南、目标或检查历史读取失败，请刷新后重试。'
const failure='期刊资料或建议读取失败，请刷新后重试。'
const mutationFailure='期刊请求未确认，请核对资料后重试。'
export default function JournalWorkspace(props:Props){return <JournalPanel key={props.projectId} {...props}/>}
function JournalPanel({projectId,active,onOpenTask}:Props){
 const {t,locale}=useI18n();const visible=useDocumentVisible();const [profiles,setProfiles]=useState<Profile[]>([]);const [history,setHistory]=useState<Recommendation[]>([]);const [selected,setSelected]=useState('');const [materials,setMaterials]=useState<MaterialCandidate[]>([]);const [manuscripts,setManuscripts]=useState<ManuscriptChoice[]>([]);const [error,setError]=useState('');const [materialError,setMaterialError]=useState('');const [busy,setBusy]=useState(false);const [ready,setReady]=useState(false);const [blocked,setBlocked]=useState(false);const [attempt,setAttempt]=useState(0)
 const [guides,setGuides]=useState<Guide[]>([]);const [targets,setTargets]=useState<Target[]>([]);const [checks,setChecks]=useState<FormatCheck[]>([]);const [formatReady,setFormatReady]=useState(false);const [formatError,setFormatError]=useState('')
 const [adaptations,setAdaptations]=useState<Adaptation[]>([]),[submissions,setSubmissions]=useState<SubmissionHistory>({items:[],current_by_target:{}}),[adaptationReady,setAdaptationReady]=useState(false),[adaptationError,setAdaptationError]=useState('')
 const alive=useRef(true);const controllers=useRef(new Set<AbortController>());const writing=useRef(false);const replay=useRef(new Map<string,{body:string;key:string}>());const base=`/api/v1/projects/${encodeURIComponent(projectId)}`
 const stop=useCallback(()=>{alive.current=false;controllers.current.forEach(c=>c.abort());controllers.current.clear();replay.current.clear();setBlocked(true);setAdaptations([]);setSubmissions({items:[],current_by_target:{}});setAdaptationReady(false);setAdaptationError('');setGuides([]);setTargets([]);setChecks([]);setFormatReady(false);setFormatError('');setProfiles([]);setHistory([]);setMaterials([]);setManuscripts([]);setSelected('');setError('');setMaterialError('');setBusy(false);setReady(false)},[])
 useEffect(()=>{const pending=controllers.current;alive.current=true;const session=onApiSessionChanged(stop);return()=>{alive.current=false;pending.forEach(c=>c.abort());session()}},[stop])
 async function request<T>(path:string,valid:(v:unknown)=>v is T,controller:AbortController,init?:RequestInit){try{return await taskRequest(`${base}/${path}`,controller,valid,init?mutationFailure:/^journals\/(guides|targets|checks)/.test(path)?formatFailure:failure,init)}catch(cause){if(cause instanceof TaskRequestError&&[401,403].includes(cause.status))stop();throw cause}}
 useEffect(()=>{
  if(!active||!visible||blocked)return;let current=true;let timer=0;const controller=new AbortController();const pending=controllers.current;pending.add(controller)
  async function load(){try{
   const [config,list,batches]=await Promise.all([
    request('journals/config',(v):v is Record<string,unknown>=>record(v)&&v.workflow_version==='journal_recommendation_v1'&&v.real_model_calls===false&&v.real_network_calls===false&&v.metrics_enabled===false,controller),
    request('journals/profiles',(v):v is {items:Profile[]}=>record(v)&&Array.isArray(v.items)&&v.items.every(p=>isProfile(p,projectId)),controller),
    request('journals/recommendations',(v):v is {items:Recommendation[]}=>record(v)&&Array.isArray(v.items)&&v.items.every(p=>isRecommendation(p,projectId)),controller)])
   if(!current||!alive.current||controller.signal.aborted)return
   void config;setProfiles(list.items);setHistory(batches.items);setSelected(old=>old||batches.items[0]?.id||'');setReady(true);setError('')
   if(batches.items.some(v=>['queued','running'].includes(v.task.status)))timer=window.setTimeout(()=>void load(),3000)
  }catch(cause){if(current&&alive.current)setError(safeError(cause,failure))}}
  void load();return()=>{current=false;controller.abort();pending.delete(controller);window.clearTimeout(timer)}
  // Requests retain the controller and project identity of this effect.
  // eslint-disable-next-line react-hooks/exhaustive-deps
 },[base,active,visible,blocked,attempt])
 useEffect(()=>{
  if(!active||blocked)return;let current=true;const controller=new AbortController();const pending=controllers.current;pending.add(controller)
  async function load(){const results=await Promise.allSettled([
   request('manuscripts/candidates',(v):v is {items:MaterialCandidate[]}=>record(v)&&Array.isArray(v.items)&&v.items.every(m=>record(m)&&typeof m.kind==='string'&&typeof m.id==='string'&&typeof m.file_id==='string'&&typeof m.label==='string'),controller),
   request('manuscripts',(v):v is {items:ManuscriptChoice[]}=>record(v)&&Array.isArray(v.items)&&v.items.every(m=>record(m)&&typeof m.id==='string'&&typeof m.title==='string'&&Array.isArray(m.versions)&&m.versions.every(v=>record(v)&&typeof v.id==='string'&&Number.isSafeInteger(v.revision)&&Number(v.revision)>0&&typeof v.status==='string')),controller)])
   if(!current||!alive.current)return
   const [sources,drafts]=results
   if(sources.status==='fulfilled')setMaterials(sources.value.items.filter(m=>['original','document_version','ocr_review_version','external_evidence_version'].includes(m.kind)))
   if(drafts.status==='fulfilled')setManuscripts(drafts.value.items)
   setMaterialError(results.some(r=>r.status==='rejected')?'公共资料或稿件暂不可用；仍可填写研究信息，刷新后重新选择。':'')
  }
  void load();return()=>{current=false;controller.abort();pending.delete(controller)}
  // eslint-disable-next-line react-hooks/exhaustive-deps
 },[base,active,blocked,attempt])
 useEffect(()=>{
  if(!active||!visible||blocked)return;let current=true;let timer=0;const controller=new AbortController();const pending=controllers.current;pending.add(controller)
  async function load(){try{const [g,t,c]=await Promise.all([
   request('journals/guides',(v):v is {items:Guide[]}=>record(v)&&Array.isArray(v.items)&&v.items.every(x=>isGuide(x,projectId)),controller),
   request('journals/targets',(v):v is {items:Target[]}=>record(v)&&Array.isArray(v.items)&&v.items.every(x=>isTarget(x,projectId)),controller),
   request('journals/checks',(v):v is {items:FormatCheck[]}=>record(v)&&Array.isArray(v.items)&&v.items.every(x=>isFormatCheck(x,projectId)),controller)])
   if(!current||!alive.current||controller.signal.aborted)return;setGuides(g.items);setTargets(t.items);setChecks(c.items);setFormatReady(true);setFormatError('')
   if(c.items.some(c=>['queued','running'].includes(c.task.status)))timer=window.setTimeout(()=>void load(),3000)
  }catch(cause){if(current&&alive.current){setFormatError(safeError(cause,'指南、目标或检查历史读取失败，请刷新后重试。'));setFormatReady(false)}}}
  void load();return()=>{current=false;controller.abort();pending.delete(controller);window.clearTimeout(timer)}
  // eslint-disable-next-line react-hooks/exhaustive-deps
 },[base,active,visible,blocked,attempt])
 useEffect(()=>{
  if(!active||!visible||blocked)return;let current=true,timer=0;const controller=new AbortController(),pending=controllers.current;pending.add(controller)
  async function load(){try{const [a,e]=await Promise.all([
   request('journals/adaptations',(v):v is {items:Adaptation[]}=>record(v)&&Array.isArray(v.items)&&v.items.every(x=>isAdaptation(x,projectId)),controller),
   request('journals/submission-events',(v):v is SubmissionHistory=>isSubmissionHistory(v,projectId),controller)])
   if(!current||!alive.current||controller.signal.aborted)return;setAdaptations(a.items);setSubmissions(e);setAdaptationReady(true);setAdaptationError('')
   if(a.items.some(a=>['queued','running'].includes(a.task.status)))timer=window.setTimeout(()=>void load(),3000)
  }catch(cause){if(current&&alive.current){setAdaptationReady(false);setAdaptationError(safeError(cause,'适配或投稿记录读取失败，请刷新重试。'))}}}
  void load();return()=>{current=false;controller.abort();pending.delete(controller);window.clearTimeout(timer)}
  // Requests inherit the parent project scope; no child registers a scope owner.
  // eslint-disable-next-line react-hooks/exhaustive-deps
 },[base,active,visible,blocked,attempt])
 async function mutate<T>(path:string,body:unknown,valid:(v:unknown)=>v is T):Promise<T|null>{
  if(writing.current||blocked||!ready)return null;writing.current=true;setBusy(true);setError('');const controller=new AbortController();controllers.current.add(controller);const serialized=JSON.stringify(body);let operation=replay.current.get(path);if(operation?.body!==serialized){operation={body:serialized,key:crypto.randomUUID()};replay.current.set(path,operation)}
  try{const value=await request(path,valid,controller,{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':operation.key},body:serialized});if(!alive.current||controller.signal.aborted)return null;replay.current.delete(path);return value}catch(cause){if(alive.current)setError(cause instanceof TaskRequestError&&cause.status===409?'资料、预览或稿件 revision 已变化，请刷新核对；固定父稿保持原版本。':safeError(cause,mutationFailure));return null}finally{writing.current=false;controllers.current.delete(controller);if(alive.current)setBusy(false)}
 }
 async function save(p:ProfileRequest){const result=await mutate('journals/profiles',p,(v):v is Profile=>isProfile(v,projectId));if(!result)return false;setProfiles(old=>[result,...old.filter(p=>p.id!==result.id)]);setAttempt(v=>v+1);return true}
 async function create(r:Research){const result=await mutate('journals/recommendations',r,(v):v is Recommendation=>isRecommendation(v,projectId));if(!result)return false;setHistory(old=>[result,...old.filter(v=>v.id!==result.id)]);setSelected(result.id);setAttempt(v=>v+1);return true}
 async function saveGuide(g:GuideRequest){const value=await mutate('journals/guides',g,(v):v is Guide=>isGuide(v,projectId));if(!value)return false;setGuides(old=>[value,...old.filter(g=>g.id!==value.id)]);return true}
 async function confirmTarget(t:TargetRequest){const value=await mutate('journals/targets',t,(v):v is Target=>isTarget(v,projectId));if(value)setTargets(old=>[value,...old.filter(t=>t.id!==value.id)]);return value}
 async function checkManuscript(target_id:string,manuscript:{id:string;revision:number}){const value=await mutate('journals/checks',{target_id,manuscript,check_version:1},(v):v is FormatCheck=>isFormatCheck(v,projectId));if(value){setChecks(old=>[value,...old.filter(c=>c.id!==value.id)]);setAttempt(v=>v+1)}return value}
 async function retryCheck(check:FormatCheck){if(check.task.status!=='failed'||(check.task.retry_count??0)>=3)return;const value=await mutate(`journals/checks/${encodeURIComponent(check.id)}/retry`,{},(v):v is FormatCheck=>isFormatCheck(v,projectId)&&v.id===check.id);if(value){setChecks(old=>old.map(c=>c.id===value.id?value:c));setAttempt(v=>v+1)}}
 async function previewAdaptation(value:AdaptationRequest){return mutate('journals/adaptations/preview',value,(v):v is AdaptationPreview=>isAdaptationPreview(v,value))}
 async function adopt(value:AdoptRequest){const saved=await mutate('journals/adaptations',value,(v):v is Adaptation=>isAdaptation(v,projectId)&&v.input_snapshot.target_id===value.target_id&&v.input_snapshot.check_id===value.check_id&&v.input_snapshot.manuscript.version_id===value.manuscript.version_id);if(saved){setAdaptations(old=>[saved,...old.filter(v=>v.id!==saved.id)]);setAttempt(a=>a+1)}return saved}
 async function retryAdaptation(value:Adaptation){if(value.task.status!=='failed'||(value.task.retry_count??0)>=3)return;const saved=await mutate(`journals/adaptations/${encodeURIComponent(value.id)}/retry`,{},(v):v is Adaptation=>isAdaptation(v,projectId)&&v.id===value.id&&JSON.stringify(v.input_snapshot)===JSON.stringify(value.input_snapshot));if(saved){setAdaptations(old=>old.map(v=>v.id===saved.id?saved:v));setAttempt(a=>a+1)}}
 async function saveSubmission(value:SubmissionRequest){const saved=await mutate('journals/submission-events',value,(v):v is SubmissionEvent=>isSubmissionEvent(v,projectId)&&v.target_id===value.target_id&&v.corrects_event_id===(value.corrects_event_id??null));if(saved){setSubmissions(old=>({...old,items:[saved,...old.items.filter(e=>e.id!==saved.id)]}));setAttempt(a=>a+1)}return saved}
 const item=history.find(v=>v.id===selected)
 async function retry(){if(!item||item.task.status!=='failed'||(item.task.retry_count??0)>=3)return;const result=await mutate(`journals/recommendations/${encodeURIComponent(item.id)}/retry`,{},(v):v is Recommendation=>isRecommendation(v,projectId)&&v.id===item.id);if(result){setHistory(old=>old.map(v=>v.id===result.id?result:v));setAttempt(v=>v+1)}}
 if(!active)return null
 return <section className="journal-workspace" aria-label={t('期刊建议')}><div className="workspace-page-heading"><div><span className="workspace-eyebrow">SCI</span><h2>{t('期刊建议')}</h2><p>{t('依据明确研究信息与本地材料进行可解释的离线规则建议。')}</p></div><button type="button" disabled={busy||blocked} onClick={()=>setAttempt(v=>v+1)}>{t('刷新期刊资料')}</button></div>
 <div className="warning-panel"><p>{t(profiles.some(p=>p.synthetic)?syntheticLabel:'若使用合成资料，仅能验证离线工程。')}</p><p>{t('真实模型调用 0；真实网络调用 0。真实材料不足时，结果不代表真实推荐质量或用户验收。')}</p><p>{t('SCI/SCIE、JIF/JCR、分区未接入；PubMed 不能证明 SCI。无录用概率或发表时间承诺。')}</p></div>
 {error&&<p role="alert" className="error-panel">{t(error)}</p>}{blocked?<p role="alert">{t('会话或项目访问已变化，请重新打开项目。')}</p>:<>{!ready&&!error&&<p role="status">{t('正在读取期刊资料……')}</p>}{materialError&&<p role="alert">{t(materialError)}</p>}
 {formatError&&<p role="alert">{t(formatError)}</p>}
 <JournalFormatPanel projectId={projectId} recommendations={history} profiles={profiles} guides={guides} targets={targets} checks={checks} manuscripts={manuscripts} materials={materials} busy={busy||!ready||!formatReady} onSaveGuide={saveGuide} onConfirm={confirmTarget} onCheck={checkManuscript} onRetry={c=>void retryCheck(c)} onOpenTask={onOpenTask} onUnavailable={stop}/>
 {adaptationError&&<p role="alert">{t(adaptationError)}</p>}
 <JournalAdaptationPanel projectId={projectId} active={active} checks={checks} targets={targets} manuscripts={manuscripts} items={adaptations} busy={busy||!ready||!formatReady||!adaptationReady} onPreview={previewAdaptation} onAdopt={adopt} onRetry={a=>void retryAdaptation(a)} onOpenTask={onOpenTask} onUnavailable={stop}/>
 <JournalSubmissionPanel targets={targets} manuscripts={manuscripts} history={submissions} busy={busy||!ready||!formatReady||!adaptationReady} onSave={saveSubmission}/>
 <JournalResearchForm manuscripts={manuscripts} materials={materials} profiles={profiles} busy={busy||!ready} onCreate={create}/>
 <details className="journal-panel"><summary>{t('登记期刊资料与版本')}</summary><JournalSourceForm projectId={projectId} onUnavailable={stop} profiles={profiles} materials={materials} busy={busy||!ready} onSave={save}/>{!profiles.length&&<p>{t('暂无期刊材料；请先登记来源或创建空候选批次查看待补信息。')}</p>}{profiles.map(p=><JournalProfile key={p.id} profile={p}/>)}</details>
 <section className="journal-panel" aria-label={t('建议批次历史')}><h3>{t('建议批次历史')}</h3><p>{t('历史批次保留创建时的输入、来源和字段证据；新版本不会覆盖旧建议。')}</p>{history.map(v=><button type="button" key={v.id} aria-pressed={selected===v.id} onClick={()=>setSelected(v.id)}>{v.input_snapshot.research.title} · {v.id} · {new Date(v.created_at).toLocaleString(locale)}</button>)}{!history.length&&<p>{t('尚无建议批次。')}</p>}</section>
 {item&&<JournalResults item={item} busy={busy} projectId={projectId} onOpenTask={onOpenTask} onRetry={()=>void retry()}/>}</>}
 </section>
}
