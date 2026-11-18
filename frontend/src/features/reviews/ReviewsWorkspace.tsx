import {ReviewActivityContext,useReviewDraftGuard} from './reviewActivityContext'
import type {RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {reviewViews,type ReviewView} from '../projects/reviewViews'
import RevisionPanel from './RevisionPanel'
import ReturnContinuationPanel from './ReturnContinuationPanel'
import ReviewSciencePanel from './ReviewSciencePanel'
import ReviewProgressPanel from './ReviewProgressPanel'
import ReviewSupplementResume from './ReviewSupplementResume'
import type {NextRoundInput} from './continuationTypes'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import {useCallback,useContext,useEffect,useLayoutEffect,useRef,useState} from 'react'
import {apiFetch,onApiSessionChanged} from '../../shared/api/client'
import {apiError,safeError,useI18n} from '../../shared/i18n'
import BatchUpload from '../files/BatchUpload'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import {manuscriptVersionPath,validManuscriptVersion,sectionLabels,type SectionId,type Snapshot} from '../manuscripts/manuscriptTypes'
import {plannedSectionTitle} from '../manuscripts/paperPlan'
import {categories,roles,itemEdit,reviewItemLabel,validInputs,validPreview,validRound,validSegments,type Inputs,type Round,type Preview,type Source,type Segment,type ItemEdit,type Item,type Material,type Location,type Role} from './reviewTypes'
import {manuscriptHash} from './continuationTypes'
import './reviews.css'
export type ReviewRoundSelection = { created?: boolean; continuation?: NextRoundInput }
type Props = {
 view?: ReviewView
 selectedItemId?: string
 onViewChange?: (view: ReviewView) => void
 onSelectItem?: (id: string, view?: ReviewView) => void
 onSelectRun?: (id: string, automatic?: boolean) => void
 onSelectDocument?: (id: string, automatic?: boolean) => void
 registerLeaveGuard?: RegisterLeaveGuard
 projectId: string
 projectType: 'sci' | 'thesis'
 active: boolean
 roundId: string
 initialManuscript?: string
 initialRevision?: number
 initialPreviousRound?: string
 initialReturn?: string
 initialRun?: string
 initialDocument?: string
 onSelectRound: (id: string, selection?: ReviewRoundSelection) => void
 onOpenTask: (id: string) => void
 onOpenAnalysisDeliveries?: () => void
}
export default function ReviewsWorkspace(props:Props){return <ReviewWorkspace key={props.projectId} {...props}/>}
type ControllerEntry = {
 key: string
 roundId: string
 manuscript?: string
 revision?: number
 previousRound?: string
 userReturn?: string
 nextInput: NextRoundInput | null
}
function ReviewWorkspace(props:Props){
 const [nextInput,setNextInput]=useState<NextRoundInput|null>(null)
 const explicitManuscript=!!(props.initialManuscript&&props.initialRevision)
 const key=props.roundId?`round:${props.roundId}`:explicitManuscript
  ? `create:manuscript:${props.initialManuscript}:${props.initialRevision}:${props.initialPreviousRound??''}:${props.initialReturn??''}`
  : nextInput?`create:continuation:${nextInput.previous_round_id}:${nextInput.user_return_id??''}:${nextInput.manuscript.version_id}`:'create:manual'
 const entry:ControllerEntry={
  key,roundId:props.roundId,manuscript:props.initialManuscript,revision:props.initialRevision,
  previousRound:props.initialPreviousRound,userReturn:props.initialReturn,nextInput:explicitManuscript?null:nextInput,
 }
 const [visited,setVisited]=useState<ControllerEntry[]>(props.active?[entry]:[])
 if(props.active&&!visited.some(e=>e.key===key))setVisited(old=>[...old,entry])
 return <ReviewActivityContext.Provider value={props.registerLeaveGuard}>
  <div hidden={!props.active}>{visited.map(e=><div key={e.key} hidden={e.key!==key}>
   <Reviews {...props} active={props.active&&e.key===key} roundId={e.roundId}
    initialManuscript={e.manuscript} initialRevision={e.revision}
    initialPreviousRound={e.previousRound} initialReturn={e.userReturn}
    initialRun={e.key===key?props.initialRun:undefined} initialDocument={e.key===key?props.initialDocument:undefined}
    nextInput={e.nextInput} onSelectRound={(id,selection)=>{
     setNextInput(null)
     if(selection) props.onSelectRound(id,selection)
     else props.onSelectRound(id)
    }}
    onPrepareNext={input=>{
     if(props.onOpenAnalysisDeliveries) props.onSelectRound('',{continuation:input})
     else {
      setNextInput(input)
      props.onSelectRound('')
      props.onViewChange?.('create')
     }
    }}/>
  </div>)}</div>
 </ReviewActivityContext.Provider>
}
type ReviewProps=Props&{nextInput:NextRoundInput|null;onPrepareNext:(input:NextRoundInput)=>void}
function Reviews({projectId,projectType,active,roundId,initialManuscript,initialRevision,initialPreviousRound,initialReturn,initialRun,initialDocument,onSelectRound,onOpenTask,nextInput,onPrepareNext,view,selectedItemId,onViewChange,onSelectItem,onSelectRun,onSelectDocument,onOpenAnalysisDeliveries}:ReviewProps){
 const {t}=useI18n(),visible=useDocumentVisible(),base=`/api/v1/projects/${encodeURIComponent(projectId)}/reviews`
 const registerLeaveGuard = useContext(ReviewActivityContext)
 const customer = !!onOpenAnalysisDeliveries
 const pinnedParent = customer && !!initialManuscript && !!initialRevision
 const [inputs,setInputs]=useState<Inputs|null>(null),[rounds,setRounds]=useState<Round[]>([]),[round,setRound]=useState<Round|null>(null),[edits,setEdits]=useState<ItemEdit[]>([]),[materials,setMaterials]=useState<Material[]>([])
 const [title,setTitle]=useState(''),[versionId,setVersionId]=useState(nextInput?.manuscript.version_id??''),[previousRoundId,setPreviousRoundId]=useState(nextInput?.previous_round_id??initialPreviousRound??''),[userReturnId,setUserReturnId]=useState(nextInput?.user_return_id??initialReturn??''),[constraint,setConstraint]=useState(''),[sources,setSources]=useState<Source[]>([]),[upload,setUpload]=useState(false)
 const [source,setSource]=useState<Source>({role:projectType==='sci'?'reviewer':'advisor',label:'',format:'text',text:'',segments:[]}),[preview,setPreview]=useState<Preview|null>(null)
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[blocked,setBlocked]=useState(false),[refresh,setRefresh]=useState(0),[snapshot,setSnapshot]=useState<Snapshot|null>(null),[history,setHistory]=useState<number|null>(null),[decisionDraft,setDecisionDraft]=useState<Record<string,{action:string;reason:string}>>({})
 const [locationError,setLocationError]=useState('')
 const creationActive=useRef(active);useLayoutEffect(()=>{creationActive.current=active&&(!view||view==='create')},[active,view])
 const draftDirty=useRef(false),loadedRound=useRef<string|null>(null),loadedRevision=useRef<number|null>(null),entryApplied=useRef(false)
 const alive=useRef(true),lifetime=useRef(new AbortController()),lock=useRef(false),attempts=useRef(new Map<string,{body:string;key:string}>())
 const clear=useCallback(()=>{alive.current=false;lifetime.current.abort();setBlocked(true);setInputs(null);setRounds([]);setRound(null);setEdits([]);setMaterials([]);setDecisionDraft({});setSources([]);setSource({role:'reviewer',label:'',format:'text',text:'',segments:[]});setPreview(null);setSnapshot(null);setTitle('');setVersionId('');setConstraint('');setNotice('');setError('');setLocationError('');setUpload(false);attempts.current.clear()},[])
 useEffect(()=>{alive.current=true;if(lifetime.current.signal.aborted)lifetime.current=new AbortController();const old=lifetime.current,stop=onApiSessionChanged(clear);return()=>{alive.current=false;old.abort();stop()}},[clear])
 const request=useCallback(async<T,>(url:string,valid:(v:unknown)=>v is T,init?:RequestInit,signal?:AbortSignal):Promise<T>=>{const c=new AbortController(),parent=lifetime.current.signal,abort=()=>c.abort();parent.addEventListener('abort',abort,{once:true});signal?.addEventListener('abort',abort,{once:true});if(parent.aborted||signal?.aborted)c.abort();const timeout=window.setTimeout(abort,15000);try{const response=await apiFetch(url,{...init,signal:c.signal});const data=await response.json().catch(()=>null);if(!alive.current||parent.aborted||c.signal.aborted)throw new DOMException('Aborted','AbortError');if(response.status===401||response.status===403||(response.status===404&&data?.detail?.code==='project_not_found')){clear();throw new DOMException('Unavailable','AbortError')}if(!response.ok)throw new Error(apiError(data,'意见计划请求失败，请刷新后重试。'));if(!valid(data))throw new Error('意见计划响应格式不正确，请刷新。');return data}finally{window.clearTimeout(timeout);parent.removeEventListener('abort',abort);signal?.removeEventListener('abort',abort)}},[clear])
 const roundValid=useCallback((v:unknown):v is Round=>validRound(v,projectId),[projectId])
 const showRound=useCallback((r:Round,reset=true)=>{if(!reset&&loadedRound.current===r.id&&draftDirty.current){if(loadedRevision.current!==r.revision)setNotice('服务器记录已更新；未保存草稿已保留，请核对后保存。');return}setRound(r);loadedRound.current=r.id;loadedRevision.current=r.revision;draftDirty.current=false;setEdits(r.items.map(itemEdit));setMaterials(r.materials.map(m=>({kind:'document_version',file_id:m.file_id,id:m.id})));setHistory(null);setDecisionDraft(Object.fromEntries(r.items.map(i=>[i.id,{action:i.decision?.action??'accept',reason:i.decision?.reason??''}])))},[])
 useEffect(()=>{if(!active||!visible||blocked)return;const c=new AbortController();void Promise.all([request(base+'/inputs',validInputs,undefined,c.signal),request(base+'/rounds',(v):v is {items:Round[]}=>!!v&&typeof v==='object'&&'items'in v&&Array.isArray(v.items)&&v.items.every(roundValid),undefined,c.signal)]).then(([i,r])=>{if(c.signal.aborted)return;setInputs(i);setRounds(r.items);if(!entryApplied.current){entryApplied.current=true;if(!nextInput&&initialManuscript&&initialRevision){const m=i.manuscripts.find(m=>m.id===initialManuscript),v=m?.versions.find(v=>v.revision===initialRevision&&v.status==='published');if(v)setVersionId(v.id);else setError('所选固定稿件版本不可用，请重新选择。')}}}).catch(cause=>{if(!c.signal.aborted&&alive.current)setError(safeError(cause,'意见计划读取失败。'))});return()=>c.abort()},[active,visible,blocked,base,request,roundValid,refresh,initialManuscript,initialRevision,nextInput])
 useEffect(()=>{if(!active||!visible||blocked||!roundId)return;const c=new AbortController();let timer=0;async function load(){try{const r=await request(base+'/rounds/'+encodeURIComponent(roundId),roundValid,undefined,c.signal);if(c.signal.aborted)return;showRound(r,false);if(['queued','running'].includes(r.task.status))timer=window.setTimeout(()=>void load(),2000)}catch(cause){if(!c.signal.aborted&&alive.current)setError(safeError(cause,'本轮意见读取失败。'))}}void load();return()=>{c.abort();window.clearTimeout(timer)}},[roundId,base,active,visible,blocked,request,roundValid,showRound,refresh])
 const fixedVersionId=round?.manuscript.version_id||versionId
 const selectedRoot=inputs?.manuscripts.find(m=>m.versions.some(version=>version.id===fixedVersionId))
 const fixedManuscriptId=round?.manuscript.id??selectedRoot?.id
 const fixedRevision=round?.manuscript.revision??selectedRoot?.versions.find(version=>version.id===fixedVersionId)?.revision
 useEffect(()=>{
  if(!active||!visible||!fixedManuscriptId||!fixedRevision||blocked)return
  const c=new AbortController()
  void request(manuscriptVersionPath(projectId,fixedManuscriptId,fixedRevision),
   (value):value is import('../manuscripts/manuscriptTypes').ManuscriptVersion=>validManuscriptVersion(value,projectId,fixedManuscriptId),undefined,c.signal)
   .then(version=>{
    if(c.signal.aborted)return
    if(version.id!==fixedVersionId||version.revision!==fixedRevision||version.status!=='published'){
     setLocationError('固定稿件位置不可用，请刷新后核对。')
     return
    }
    setSnapshot(version.snapshot)
    setLocationError('')
    if(!roundId&&projectType==='thesis')setConstraint(version.snapshot.thesis_context?.confirmation_id??'')
   }).catch(cause=>{if(!c.signal.aborted&&alive.current)setLocationError(safeError(cause,'稿件位置读取失败。'))})
  return()=>c.abort()
 },[fixedVersionId,fixedManuscriptId,fixedRevision,roundId,blocked,projectId,projectType,request,active,visible,refresh])

 async function mutate<T>(path:string,body:unknown,valid:(v:unknown)=>v is T){const serialized=JSON.stringify(body),url=base+path;let attempt=attempts.current.get(url);if(attempt?.body!==serialized){attempt={body:serialized,key:crypto.randomUUID()};attempts.current.set(url,attempt)}return request(url,valid,{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':attempt!.key},body:serialized})}
 async function run(work:()=>Promise<void>){if(lock.current||blocked)return;lock.current=true;setBusy(true);setError('');setNotice('');try{await work()}catch(cause){if(alive.current)setError(safeError(cause,'意见计划请求失败，请刷新后重试。'))}finally{lock.current=false;if(alive.current)setBusy(false)}}
 function changeSource(p:Partial<Source>){setSource(s=>({...s,...p}));setPreview(null)}
 async function previewSource(){await run(async()=>{if(!source.label.trim())throw new Error('请填写来源身份。');const payload={...source,label:source.label.trim(),segments:undefined};const p=await mutate('/sources/preview',payload,validPreview);setPreview(p)})}
 function saveSource(){if(!preview?.supported||!validSegments(preview.original_text,preview.segments)){setError('分条必须按顺序完整覆盖原文，且不能重复。');return}setSources(old=>[...old,{...source,label:source.label.trim(),text:source.format==='text'?preview.original_text:undefined,segments:preview.segments.map(({start,end,original_number})=>({start,end,original_number}))}]);setSource({role:projectType==='sci'?'reviewer':'advisor',label:'',format:'text',text:'',segments:[]});setPreview(null)}
 async function create() {
  await run(async()=>{
   const manuscript = inputs?.manuscripts.find(m=>m.versions.some(v=>v.id===versionId&&v.status==='published'))
   const v = manuscript?.versions.find(v=>v.id===versionId)
   if(!title.trim()||!sources.length||!manuscript||!v)
    throw new Error('请填写轮次标题，选择已发布稿件版本，并保存至少一个来源。')
   const r = await mutate('/rounds',{
    title:title.trim(),project_type:projectType,synthetic:!customer,
    manuscript:{id:manuscript.id,revision:v.revision,version_id:v.id},sources,materials,
    ...(previousRoundId?{previous_round_id:previousRoundId,user_return_id:userReturnId||null}:{}),
    ...(projectType==='sci'?{journal_target_id:constraint||null}:{school_confirmation_id:constraint||null}),
   },roundValid)
   setRound(null)
   loadedRound.current=null
   loadedRevision.current=null
   draftDirty.current=false
   setEdits([])
   setDecisionDraft({})
   setMaterials([])
   if(!pinnedParent) {
    setSnapshot(null)
    setVersionId('')
    setPreviousRoundId('')
    setUserReturnId('')
    setConstraint('')
   } else if(projectType==='sci') {
    setConstraint('')
   }
   setRounds(old=>[r,...old.filter(x=>x.id!==r.id)])
   setSources([])
   setTitle('')
   setSource({role:projectType==='sci'?'reviewer':'advisor',label:'',format:'text',text:'',segments:[]})
   if(creationActive.current) {
    if(customer) onSelectRound(r.id,{created:true})
    else {
     onSelectRound(r.id)
     onViewChange?.('items')
    }
   }
  })
 }
 const currentMaterials = round?.materials.map(({file_id,id})=>({kind:'document_version',file_id,id}))
 const unsavedEdits = !!round&&(JSON.stringify(edits)!==JSON.stringify(round.items.map(itemEdit))||
  JSON.stringify(materials)!==JSON.stringify(currentMaterials))
 const importantEdits = edits.filter(i=>i.flags.length||i.proposed_action==='not_adopt')
 const displayedDecisions = customer ? importantEdits.filter(i=>i.id===selectedItemId) : importantEdits

 async function savePlan(){if(!round)return;await run(async()=>{const r=await mutate('/rounds/'+encodeURIComponent(round.id)+'/plans',{expected_revision:round.revision,items:edits,materials},roundValid);showRound(r);setNotice('意见计划已保存；意见仍待处理。')})}
 async function saveDecisions() {
  if(!round)return
  await run(async()=>{
   if(unsavedEdits)throw new Error('请先保存计划修改，再记录决定。')
   const decisions=displayedDecisions.map(i=>({
    item_id:i.id,action:decisionDraft[i.id]?.action??'accept',reason:decisionDraft[i.id]?.reason.trim()??'',
   }))
   if(!decisions.length)return
   if(decisions.some(d=>!d.reason))throw new Error('请填写决定理由。')
   const r=await mutate('/rounds/'+encodeURIComponent(round.id)+'/decisions',{expected_revision:round.revision,decisions},roundValid)
   // Saving one opinion's decision should preserve other opinions' unsaved decisions.
   const changed=r.items.filter(i=>i.id!==selectedItemId&&importantEdits.some(edit=>edit.id===i.id)&&
    (decisionDraft[i.id]?.action!==(i.decision?.action??'accept')||
    decisionDraft[i.id]?.reason!==(i.decision?.reason??'')))
   showRound(r)
   if(customer&&changed.length) {
    draftDirty.current=true
    const remaining=Object.fromEntries(changed.map(i=>[i.id,decisionDraft[i.id]]))
    setDecisionDraft(saved=>({...saved,...remaining}))
   }
   setNotice('决定已记录；可前往任务继续本地计划核查。')
  })
 }

 const unsavedPlan=unsavedEdits||!!round?.items.some(i=>(i.flags.length||i.proposed_action==='not_adopt')&&
  (decisionDraft[i.id]?.action!==(i.decision?.action??'accept')||decisionDraft[i.id]?.reason!==(i.decision?.reason??'')))
 const planDirty=busy||history!==null||unsavedPlan
 const createDirty=!!(title||!pinnedParent&&versionId||sources.length||source.label||source.text||
  source.received_on||source.document_version_id||materials.length||projectType==='sci'&&constraint||
  !pinnedParent&&previousRoundId)
 useReviewDraftGuard(roundId?unsavedPlan:createDirty,busy)
 const inView=(...views:ReviewView[])=>!view||views.includes(view)
 const selectedItem=round?.items.find(i=>i.id===selectedItemId)
 const available=inputs?.documents??[],locations=locationOptions(snapshot,t),readonly=history!==null,shown=readonly?round?.versions.find(v=>v.revision===history)?.items??[]:round?.items??[]
 const evidenceNames=new Map([
  ...(snapshot?.sources??[]).map(source=>[source.id,source.label] as const),
  ...available.map(document=>[document.document_version_id,document.filename] as const),
 ])
 if(customer&&active&&inView('create','supplements','continuation')&&!upload)setUpload(true)
 function changeMaterials(next:Material[]){draftDirty.current=true;setMaterials(next);const allowed=new Set([...next.map(m=>m.id),...(snapshot?.sources??[]).map(s=>s.id)]);setEdits(old=>old.map(i=>({...i,evidence_ids:i.evidence_ids.filter(id=>allowed.has(id))})))}
 function update(id:string,patch:Partial<ItemEdit>){draftDirty.current=true;setEdits(old=>old.map(i=>i.id===id?{...i,...patch}:i))}
 function openRound(id:string) {
  onSelectRound(id)
  if(!customer)onViewChange?.(id?'items':'create')
 }
 function openItem(id:string) {
  if(customer)onSelectItem?.(id,'plan')
  else {
   onSelectItem?.(id)
   onViewChange?.('plan')
  }
 }
 if(blocked)return <p role="status">{t('会话或项目不可用，请重新打开项目。')}</p>
 const sourceRecords=round?.sources.map(source=><article key={source.id}>
  <h4>{t(roles[source.role])} · {source.file_id
   ? <ProjectDownloadLink href={`/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(source.file_id)}/download`}
     filename={available.find(d=>d.file_id===source.file_id)?.filename??source.label}>{source.label}</ProjectDownloadLink>
   : source.label}</h4>
  <pre className="review-original">{source.original_text}</pre>
  {source.warnings?.map((warning,index)=><p className="warning-panel" key={index}>{t(warning)}</p>)}
 </article>)
 const tabs = reviewViews.filter(tab => roundId
  ? tab!=='create'&&(customer?projectType==='sci'||tab!=='response':tab!=='documents')
  : tab==='list'||tab==='progress'||!customer&&tab==='create')
 return <section className="reviews-workspace" aria-label={t('意见修改')}>
 {!customer&&<header><h2>{t('意见修改')}</h2><p>{t('固定稿件版本，保留逐条原文，整理修改计划与处理决定。')}</p></header>}
 {!customer&&<p className="warning-panel">{t('本批仅使用合成材料与本地具体改文；未调用模型或业务外网，不代表真实科学验收。')}</p>}
 {customer&&round?.synthetic&&<p className="warning-panel">{t('本轮使用合成材料。')}</p>}
 {(error||locationError)&&<p className="error-panel" role="alert">{t(error||locationError)}</p>}{notice&&<p role="status">{t(notice)}</p>}
 <button type="button" disabled={busy} onClick={()=>setRefresh(x=>x+1)}>{t('刷新意见记录')}</button>
 {view&&<nav className="review-view-tabs" aria-label={t('评审工作视图')}>{tabs.map(tab=>
  <button type="button" key={tab} aria-current={view===tab?'page':undefined} onClick={()=>onViewChange?.(tab)}>
   {t(customer&&tab==='science'?'分析材料补充':reviewViewLabels[tab])}
  </button>)}</nav>}
 <div hidden={!inView('list')}>
  <nav className="review-rounds" aria-label={t('意见轮次')}>
   <button type="button" onClick={()=>openRound('')}>{t('新建意见轮次')}</button>
   {rounds.map(r=><button type="button" key={r.id} aria-current={roundId===r.id?'page':undefined} onClick={()=>openRound(r.id)}>
    {t('第 {number} 轮',{number:r.round_number})} · {r.title}
   </button>)}
  </nav>
  {customer&&inputs&&!rounds.length&&<p className="muted">{t('尚无意见轮次。')}</p>}
 </div>
 {!roundId&&<div hidden={!inView('create')}><fieldset disabled={busy||!inputs} className="review-create">
  <legend>{t('新建意见轮次')}</legend>
  <label>{t('上一轮意见')}<select disabled={pinnedParent&&!!initialPreviousRound} value={previousRoundId} onChange={e=>{
   setPreviousRoundId(e.target.value);setUserReturnId('')
   if(!pinnedParent){setVersionId('');setSnapshot(null);setConstraint('')}
  }}>
   <option value="">{t('独立首轮（不关联上一轮）')}</option>
   {rounds.map(r=><option key={r.id} value={r.id}>{t('第 {number} 轮',{number:r.round_number})} · {r.title}</option>)}
  </select></label>
  {userReturnId&&<p>{t('已选择成功发布的回传新稿作为本轮固定输入。')}</p>}
  <label>{t('轮次标题')}<input value={title} maxLength={200} onChange={e=>setTitle(e.target.value)}/></label>
  <label>{t('固定稿件版本')}<select disabled={pinnedParent} value={versionId} onChange={e=>{
   setSnapshot(null);setConstraint('');setVersionId(e.target.value);setUserReturnId('')
  }}>
   <option value="">{t('请选择已发布版本')}</option>
   {inputs?.manuscripts.flatMap(m=>m.versions.filter(v=>v.status==='published').map(v=>
    <option key={v.id} value={v.id}>{v.title||m.title} · {t('版本 {number}',{number:v.revision})}</option>))}
  </select></label>
  {!customer&&<p>{t('允许选择旧版；创建后不会自动切换到最新稿。')}</p>}
  <label>{t(projectType==='sci'?'关联期刊目标（可选）':'固定稿件的学校确认')}
   <select disabled={projectType==='thesis'} value={constraint} onChange={e=>setConstraint(e.target.value)}>
    <option value="">{t('不关联')}</option>
    {(projectType==='sci'?inputs?.journal_targets:inputs?.school_confirmations)?.map(c=><option key={c.id} value={c.id}>{c.label}</option>)}
   </select>
  </label>
 <fieldset><legend>{t('添加意见来源')}</legend><label>{t('来源角色')}<select value={source.role} onChange={e=>changeSource({role:e.target.value as Role})}>{(projectType==='sci'?['editor','reviewer']:['advisor','evaluator','defense']).map(role=><option key={role} value={role}>{t(roles[role as Role])}</option>)}</select></label><label>{t('来源身份')}<input value={source.label} maxLength={120} onChange={e=>changeSource({label:e.target.value})} placeholder={projectType==='sci'?'Reviewer 1':t('导师意见')}/></label><label>{t('收到日期')}<input type="date" value={source.received_on??''} onChange={e=>changeSource({received_on:e.target.value||null})}/></label><label>{t('来源方式')}<select value={source.format} onChange={e=>changeSource({format:e.target.value as Source['format'],text:'',file_id:undefined,document_version_id:undefined})}><option value="text">{t('粘贴原文')}</option><option value="document">{t('已解析 DOCX / PDF')}</option></select></label>{source.format==='text'?<label>{t('意见原文')}<textarea rows={7} value={source.text??''} onChange={e=>changeSource({text:e.target.value})}/></label>:<label>{t('选择固定解析版本')}<select value={source.document_version_id??''} onChange={e=>{const d=available.find(d=>d.document_version_id===e.target.value);changeSource({document_version_id:d?.document_version_id,file_id:d?.file_id})}}><option value="">{t('请选择解析文件')}</option>{available.map(d=><option key={d.document_version_id} value={d.document_version_id}>{d.filename} · {t('版本 {number}',{number:d.version})}</option>)}</select></label>}<button type="button" onClick={()=>void previewSource()}>{t('预览并分条')}</button>
 {preview&&<SourcePreview preview={preview} onChange={setPreview} onSave={saveSource}/>}</fieldset>
 {sources.map((s,i)=><article className="review-source" key={i}><strong>{t(roles[s.role])} · {s.label}</strong><span> · {t('{number} 条意见',{number:s.segments.length})}</span><button type="button" onClick={()=>setSources(old=>old.filter((_,n)=>n!==i))}>{t('移除此来源')}</button></article>)}
 <MaterialPicker documents={available} materials={materials} onChange={changeMaterials}/><button type="button" className="button-primary" onClick={()=>void create()}>{t('创建本轮意见计划')}</button></fieldset></div>}
 <div hidden={!inView('create','supplements','continuation')}>
  {!customer&&<button type="button" aria-expanded={upload} onClick={()=>setUpload(v=>!v)}>
   {t(upload?'收起上传入口':'上传并解析新的 DOCX / PDF')}
  </button>}
  {upload&&<BatchUpload projectId={projectId} active={active&&inView('create','supplements','continuation')}
   reviewDocument={customer} registerLeaveGuard={registerLeaveGuard} embedded={customer} customerView={customer}
   onUnavailable={clear} onChanged={()=>setRefresh(x=>x+1)}/>}
 </div>
 {roundId&&!round&&!error&&<p role="status">{t('正在读取本轮意见……')}</p>}{round&&<><header className="review-round-heading"><h3>{t('第 {number} 轮',{number:round.round_number})} · {round.title}</h3><p>{round.manuscript.title}{customer?<>{' · '}<a href={manuscriptHash(projectId,round.manuscript)}>{t('查看原稿')}</a></>:<> · {t('固定版本 {number}',{number:round.manuscript.revision})}</>}</p><p>{t(round.task.status==='succeeded'?'计划已保存，意见待处理':round.task.status==='waiting_input'?'本轮计划等待补充材料':round.task.status==='waiting_confirmation'?'本轮计划等待用户确认':round.task.status==='failed'?'本轮计划执行失败，请查看任务后安全重试。':'本轮计划处理中')}</p><button type="button" onClick={()=>onOpenTask(round.task.id)}>{t('查看任务与继续本地计划')}</button></header>
 <div hidden={!inView('sources')}>
  {customer?<section aria-label={t('本轮来源原文')}><h4>{t('本轮来源原文')}</h4>{sourceRecords}</section>
   :<details open={!!view}><summary>{t('本轮来源原文')}</summary>{sourceRecords}</details>}
 </div>
 {view&&<section hidden={!inView('items')} aria-label={t('选择处理意见')}><h3>{t('选择处理意见')}</h3>{round.items.map(item=><button className="review-opinion-row" type="button" key={item.id} aria-current={selectedItemId===item.id?'true':undefined} onClick={()=>openItem(item.id)}><strong>{reviewItemLabel(item.number,round.sources.find(s=>s.id===item.source_id)?.label,t)}</strong><span>{item.original_text}</span><small>{t(itemStatuses[item.status])}</small></button>)}</section>}
 <div hidden={!inView('plan')}>
  {view&&<label>{t('当前处理意见')}<select value={selectedItemId??''} onChange={e=>onSelectItem?.(e.target.value)}>
   <option value="">{t('请选择意见')}</option>
   {round.items.map(i=><option key={i.id} value={i.id}>{reviewItemLabel(i.number,round.sources.find(s=>s.id===i.source_id)?.label,t)}</option>)}
  </select></label>}
  {view&&!selectedItem&&<p role={selectedItemId?'alert':'status'}>
   {t(selectedItemId?'指定意见在本轮中不可用。':'请先选择一条意见，再整理处理计划。')}
  </p>}
  <label>{t('查看计划历史')}<select value={history??''} onChange={e=>setHistory(e.target.value?Number(e.target.value):null)}>
   <option value="">{t('当前可编辑计划')}</option>
   {round.versions.map(v=><option key={v.id} value={v.revision}>{t('计划版本 {number}',{number:v.revision})} · {new Date(v.created_at).toLocaleString()}</option>)}
  </select></label>
  {readonly&&<p>{t('历史计划只读，切回当前计划后可继续修改。')}</p>}
  <fieldset disabled={busy||readonly||['queued','running'].includes(round.task.status)}>
   <legend>{t('逐条意见与修改计划')}</legend>
   {shown.map(item=>{
    const edit=readonly?itemEdit(item):edits.find(e=>e.id===item.id)
    return edit&&<div key={item.id} hidden={!!view&&selectedItemId!==item.id}>
     <ReviewItem key={item.id+':'+String(history)} item={item} edit={edit} sources={round.sources} locations={locations}
      documents={available.filter(d=>materials.some(m=>m.id===d.document_version_id))}
      frozenSources={snapshot?.sources??[]} allItems={round.items} onChange={patch=>update(item.id,patch)}/>
    </div>
   })}
   <MaterialPicker documents={available} materials={materials} onChange={changeMaterials}/>
   {!readonly&&<button type="button" className="button-primary" onClick={()=>void savePlan()}>{t('保存本轮计划修改')}</button>}
  </fieldset>
  {!readonly&&displayedDecisions.length>0&&<fieldset disabled={busy}>
   <legend>{t(customer?'此条意见的处理决定':'本轮重要处理决定')}</legend>
   <p>{t('普通计划修改直接保存；仅歧义、冲突、结论变化或不采纳需要明确决定。')}</p>
   {displayedDecisions.map(i=><fieldset hidden={!!view&&selectedItemId!==i.id} key={i.id}>
    <legend>{reviewItemLabel(round.items.find(x=>x.id===i.id)?.number??'—',round.sources.find(s=>s.id===round.items.find(x=>x.id===i.id)?.source_id)?.label,t)}</legend>
    <label>{t('决定')}<select value={decisionDraft[i.id]?.action??'accept'} onChange={e=>{
     draftDirty.current=true
     setDecisionDraft(old=>({...old,[i.id]:{action:e.target.value,reason:old[i.id]?.reason??''}}))
    }}>{Object.entries(decisionLabels).map(([k,v])=><option key={k} value={k}>{t(v)}</option>)}</select></label>
    <label>{t('决定理由')}<textarea value={decisionDraft[i.id]?.reason??''} onChange={e=>{
     draftDirty.current=true
     setDecisionDraft(old=>({...old,[i.id]:{action:old[i.id]?.action??'accept',reason:e.target.value}}))
    }}/></label>
   </fieldset>)}
   <p>{t('选择“已澄清并确认处理”时，理由应写明已澄清的具体处理；尚待答复请暂缓处理。')}</p>
   {!customer&&<p>{t('先保存计划修改，再集中记录决定；采纳计划不会完成改稿。')}</p>}
   <button type="button" disabled={customer&&unsavedEdits} onClick={()=>void saveDecisions()}>
    {t(customer?'保存此条决定':'保存本轮决定')}
   </button>
  </fieldset>}
  <section><h4>{t('处理决定记录')}</h4>{round.decisions.length===0&&<p>{t('尚无决定记录。')}</p>}
   {round.decisions.map(d=><p key={d.id}>{reviewItemLabel(round.items.find(i=>i.id===d.item_id)?.number??'—',round.sources.find(s=>s.id===round.items.find(i=>i.id===d.item_id)?.source_id)?.label,t)} · {t(decisionLabels[d.action])} · {d.reason}</p>)}
  </section>
 </div>
 <div hidden={!inView('continuation')}>
  <ReturnContinuationPanel projectId={projectId} round={round} documents={available} active={active&&inView('continuation')}
   expanded={view==='continuation'} customer={customer} onPrepareNext={onPrepareNext} onOpenTask={onOpenTask}/>
 </div>
 <div hidden={!inView('science')}>
  {onOpenAnalysisDeliveries ? <section className="manuscript-panel">
   <h3>{t('分析材料补充')}</h3>
   <p>{t('从分析项目下载已发布的 Word 材料，在本轮上传解析，然后在处理计划中选择对应的固定材料版本。')}</p>
   <div className="review-inline-actions">
    <button type="button" onClick={onOpenAnalysisDeliveries}>{t('前往已发布分析交付')}</button>
    <button type="button" onClick={()=>onViewChange?.('supplements')}>{t('上传补充材料')}</button>
   </div>
   {round.items.filter(item=>item.needs.length>0).map(item=><article key={item.id}>
    <h4>{reviewItemLabel(item.number,round.sources.find(s=>s.id===item.source_id)?.label,t)} · {t(itemStatuses[item.status])}</h4>
    <ul>{item.needs.map(need=><li key={need.kind+':'+need.description}>{need.description}</li>)}</ul>
   </article>)}
  </section> : <ReviewSciencePanel projectId={projectId} round={round} active={active&&inView('science')}
   expanded={view==='science'} disabled={planDirty} onOpenTask={onOpenTask} onChanged={()=>setRefresh(x=>x+1)}/>}
 </div>
 <div hidden={!inView('supplements')}>
  <ReviewSupplementResume projectId={projectId} round={round} active={active&&inView('supplements')}
   expanded={view==='supplements'} customer={customer} disabled={planDirty} onChanged={()=>setRefresh(x=>x+1)}/>
 </div>
 <div hidden={!inView('revision','comparison','response','documents')}>
  <RevisionPanel selectedItemId={selectedItemId} onSelectItem={onSelectItem} projectId={projectId} round={round} view={view}
   onSelectRun={onSelectRun} onSelectDocument={onSelectDocument} active={active&&inView('revision','comparison','response','documents')}
   disabled={planDirty} initialRun={initialRun} initialDocument={initialDocument} onOpenTask={onOpenTask} customer={customer} evidenceNames={evidenceNames}/>
 </div></>}
 <div hidden={!inView('progress')}><ReviewProgressPanel projectId={projectId} projectType={projectType} inputs={inputs} rounds={rounds} active={active&&inView('progress')} expanded={view==='progress'} customer={customer}/></div>
 </section>
}
const decisionLabels={accept:'采纳计划',clarify:'已澄清并确认处理',not_adopt:'不采纳',defer:'暂缓处理'}
const itemStatuses: Record<Item['status'], string> = {
 pending:'待处理',waiting_confirmation:'待确认',waiting_material:'待补材料',
 not_adopted:'已记录不采纳',executing:'执行中',completed:'有实际修改',
}
function SourcePreview({preview,onChange,onSave}:{preview:Preview;onChange:(v:Preview)=>void;onSave:()=>void}){const {t}=useI18n(),[splitAt,setSplitAt]=useState<Record<number,string>>({});const text=Array.from(preview.original_text);function update(i:number,patch:Partial<Segment>){onChange({...preview,segments:preview.segments.map((s,n)=>n===i?{...s,...patch}:s)})}return <section aria-label={t('原文分条预览')}><h4>{t('原文分条预览')}</h4><pre className="review-original">{preview.original_text}</pre>{preview.warnings.map((w,i)=><p className="warning-panel" key={i}>{t(w)}</p>)}{!preview.supported&&<p role="alert">{t('此文件含不完整或不可提取内容，请提供清洁文本；当前不能创建来源。')}</p>}{preview.segments.map((s,i)=><article className="review-segment" key={i}><label>{t('原始编号')}<input value={s.original_number} onChange={e=>update(i,{original_number:e.target.value})}/></label><pre className="review-original">{text.slice(s.start,s.end).join('')}</pre><SourcePosition value={s.location}/><label>{t('在本条第几个字符后拆分')}<input type="number" min={1} max={s.end-s.start-1} value={splitAt[i]??''} onChange={e=>setSplitAt(old=>({...old,[i]:e.target.value}))}/></label><button type="button" disabled={!(Number.isSafeInteger(Number(splitAt[i]))&&Number(splitAt[i])>0&&Number(splitAt[i])<s.end-s.start)} onClick={()=>{const at=s.start+Number(splitAt[i]);onChange({...preview,segments:preview.segments.flatMap((x,n)=>n===i?[{...s,end:at},{start:at,end:s.end,original_number:s.original_number+'b'}]:[x])})}}>{t('拆分此条')}</button>{i<preview.segments.length-1&&<button type="button" onClick={()=>onChange({...preview,segments:preview.segments.flatMap((x,n)=>n===i?[{...s,end:preview.segments[i+1].end}]:n===i+1?[]:[x])})}>{t('与下一条合并')}</button>}</article>)}<button type="button" disabled={!preview.supported||!validSegments(preview.original_text,preview.segments)} onClick={onSave}>{t('保存来源')}</button></section>}
function MaterialPicker({documents,materials,onChange}:{documents:Inputs['documents'];materials:Material[];onChange:(v:Material[])=>void}){const {t}=useI18n();return <fieldset><legend>{t('补充材料（固定解析版本）')}</legend>{documents.length===0&&<p>{t('暂无已解析资料，可使用上传入口补充。')}</p>}{documents.map(d=><label key={d.document_version_id}><input type="checkbox" checked={materials.some(m=>m.id===d.document_version_id)} onChange={e=>onChange(e.target.checked?[...materials,{kind:'document_version',file_id:d.file_id,id:d.document_version_id}]:materials.filter(m=>m.id!==d.document_version_id))}/>{d.filename} · {t('版本 {number}',{number:d.version})}</label>)}</fieldset>}
type LocationOption=Location&{label:string}
function locationOptions(snapshot:Snapshot|null,t:(key:string,params?:Record<string,string|number>)=>string):LocationOption[]{
 if(!snapshot)return []
 const result:LocationOption[]=[]
 for(const [n,s] of (snapshot.sections??[]).entries()){
  const name=plannedSectionTitle(snapshot,s.id)??t(sectionLabels[s.id as SectionId]??'章节 {number}',{number:n+1})
  result.push({kind:'section',id:s.id,label:name})
  s.paragraphs.forEach((p,i)=>result.push({kind:'paragraph',id:p.id,label:name+' · '+t('段落 {number}',{number:i+1})}))
 }
 snapshot.methods.forEach((p,i)=>result.push({kind:'paragraph',id:p.id,label:t('方法')+' · '+t('段落 {number}',{number:i+1})}))
 for(const g of snapshot.results_groups){
  const owner=snapshot.paper_plan?.sections.find(s=>s.id===g.id)
  const groupLabel=owner?.group_title??owner?.label??g.title
  const prefix=owner?groupLabel+' · ':''
  g.paragraphs.forEach((p,i)=>result.push({kind:'paragraph',id:p.id,label:groupLabel+' · '+t('段落 {number}',{number:i+1})}))
  g.figures.forEach(f=>result.push({kind:'figure',id:f.id,label:prefix+t('图 {number}',{number:f.number})+' · '+f.title}))
  g.tables.forEach((x,i)=>result.push({kind:'table',id:x.id,label:prefix+(owner?x.title:t('表 {number}',{number:x.number??i+1})+' · '+x.title)}))
 }
 return result.filter((x,i)=>result.findIndex(v=>v.kind===x.kind&&v.id===x.id)===i)
}
function ReviewItem({item,edit,sources,locations,documents,frozenSources,allItems,onChange}:{item:Item;edit:ItemEdit;sources:Source[];locations:LocationOption[];documents:Inputs['documents'];frozenSources:{id:string;label:string}[];allItems:Item[];onChange:(patch:Partial<ItemEdit>)=>void}){const {t}=useI18n();return <article className="review-item"><h4>{reviewItemLabel(item.number,sources.find(s=>s.id===item.source_id)?.label,t)} · {t('原始编号 {number}',{number:item.original_number})}</h4><pre className="review-original">{item.original_text}</pre><SourcePosition value={item.source_location}/><p>{t({pending:'待处理',waiting_confirmation:'待确认',waiting_material:'待补材料',not_adopted:'已记录不采纳',executing:'执行中',completed:'有实际修改'}[item.status])}{item.uncompleted_reason&&' · '+t(item.uncompleted_reason)}</p><label>{t('意见类别')}<select value={edit.category} onChange={e=>onChange({category:e.target.value as ItemEdit['category']})}>{Object.entries(categories).map(([k,v])=><option key={k} value={k}>{t(v)}</option>)}</select></label><label>{t('定位到固定稿件')}<select multiple value={edit.locations.map(l=>l.kind+':'+l.id)} onChange={e=>onChange({locations:Array.from(e.target.selectedOptions).flatMap(o=>{const l=locations.find(l=>l.kind+':'+l.id===o.value);return l?[{kind:l.kind,id:l.id}]:[]})})}>{locations.map(l=><option key={l.kind+':'+l.id} value={l.kind+':'+l.id}>{l.label}</option>)}</select></label>{edit.locations.length===0&&<p>{t('尚未定位；请核对固定稿件后选择章节、段落或图表。')}</p>}<label>{t('修改计划')}<textarea value={edit.plan} rows={4} onChange={e=>onChange({plan:e.target.value})}/></label><fieldset><legend>{t('独立人工译文（不改动原文）')}</legend><label>{t('译文语言')}<select value={edit.translation?.language??'zh-CN'} onChange={e=>onChange({translation:{language:e.target.value as 'zh-CN'|'en',text:edit.translation?.text??''}})}><option value="zh-CN">{t('中文')}</option><option value="en">English</option></select></label><label>{t('人工译文')}<textarea value={edit.translation?.text??''} onChange={e=>onChange({translation:e.target.value?{language:edit.translation?.language??'zh-CN',text:e.target.value}:null})}/></label></fieldset><fieldset><legend>{t('依据材料')}</legend>{[...documents.map(d=>({id:d.document_version_id,label:d.filename+' · '+t('版本 {number}',{number:d.version})})),...frozenSources].filter((d,i,a)=>a.findIndex(x=>x.id===d.id)===i).map(d=><label key={d.id}><input type="checkbox" checked={edit.evidence_ids.includes(d.id)} onChange={e=>onChange({evidence_ids:e.target.checked?[...edit.evidence_ids,d.id]:edit.evidence_ids.filter(id=>id!==d.id)})}/>{d.label}</label>)}</fieldset><fieldset><legend>{t('待补需求')}</legend>{edit.needs.map((n,i)=><div className="review-need" key={i}><label>{t('需求类型')}<select value={n.kind} onChange={e=>onChange({needs:edit.needs.map((x,j)=>j===i?{...x,kind:e.target.value as typeof n.kind}:x)})}>{Object.entries({material:'资料',analysis:'分析',experiment:'实验',literature:'文献'}).map(([k,v])=><option key={k} value={k}>{t(v)}</option>)}</select></label><label>{t('需求说明')}<input value={n.description} onChange={e=>onChange({needs:edit.needs.map((x,j)=>j===i?{...x,description:e.target.value}:x)})}/></label><button type="button" onClick={()=>onChange({needs:edit.needs.filter((_,j)=>j!==i)})}>{t('移除需求')}</button></div>)}<button type="button" onClick={()=>onChange({needs:[...edit.needs,{kind:'material',description:''}]})}>{t('添加待补需求')}</button></fieldset><fieldset><legend>{t('风险与冲突')}</legend>{Object.entries({ambiguous:'含糊需澄清',conflict:'与其他意见冲突',conclusion_change:'可能改变结论'}).map(([k,v])=><label key={k}><input type="checkbox" checked={edit.flags.includes(k as ItemEdit['flags'][number])} onChange={e=>onChange({flags:e.target.checked?[...edit.flags,k as ItemEdit['flags'][number]]:edit.flags.filter(f=>f!==k)})}/>{t(v)}</label>)}{allItems.filter(i=>i.id!==item.id).map(i=><label key={i.id}><input type="checkbox" checked={edit.conflicting_item_ids.includes(i.id)} onChange={e=>onChange({conflicting_item_ids:e.target.checked?[...edit.conflicting_item_ids,i.id]:edit.conflicting_item_ids.filter(id=>id!==i.id)})}/>{t('关联冲突意见 {number}',{number:reviewItemLabel(i.number,sources.find(s=>s.id===i.source_id)?.label,t)})}</label>)}</fieldset><label>{t('拟处理方式')}<select value={edit.proposed_action} onChange={e=>onChange({proposed_action:e.target.value as ItemEdit['proposed_action']})}><option value="modify">{t('拟修改')}</option><option value="not_adopt">{t('拟不采纳')}</option></select></label><label>{t('不采纳理由')}<textarea value={edit.not_adopt_reason} onChange={e=>onChange({not_adopt_reason:e.target.value})}/></label></article>}

function SourcePosition({value}:{value:unknown}){const {t}=useI18n();if(!value||typeof value!=='object')return null;const v=value as Record<string,unknown>,page=v.page??v.page_number;if(typeof v.label==='string'&&v.label)return <small>{v.label}</small>;if(typeof page==='number')return <small>{t('来源第 {number} 页',{number:page})}</small>;if(typeof v.start==='number'&&typeof v.end==='number')return <small>{t('来源原文第 {start} 至 {end} 个字符',{start:v.start+1,end:v.end})}</small>;if(typeof v.paragraph_index==='number')return <small>{t('来源段落 {number}',{number:v.paragraph_index+1})}</small>;return null}

const reviewViewLabels:Record<ReviewView,string>={list:'意见轮次',create:'新建意见轮次',sources:'来源原文',items:'逐条意见',plan:'处理计划',revision:'有依据改文',comparison:'修改对照',response:'逐条回复',documents:'固定文档',continuation:'回传续轮',science:'科学补充',supplements:'补料继续',progress:'实际进展'}
