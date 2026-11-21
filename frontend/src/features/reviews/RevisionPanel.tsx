import {systemCheckText} from '../../shared/i18n/systemChecks'
import {protocolLabel,severities,unexecutedStates} from '../../shared/i18n/protocolLabels'
import {useReviewDraftGuard} from './reviewActivityContext'
import type {ReviewView} from '../projects/reviewViews'
import {useContext} from 'react'
import {ReviewActivityContext} from './reviewActivityContext'
import FixedEvidenceDetails,{FixedChangeValue,EvidenceLabel} from './FixedEvidenceDetails'
import {useEffect,useLayoutEffect,useRef,useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import {manuscriptVersionPath,validManuscriptVersion,type ManuscriptVersion} from '../manuscripts/manuscriptTypes'
import ManuscriptPreview from '../manuscripts/ManuscriptPreview'
import ManuscriptExports from '../manuscripts/ManuscriptExports'
import type {Round} from './reviewTypes'
import {reviewItemLabel} from './reviewTypes'
import {operationNames,object,reviewBase,revisionHash,validRevisionContext,validRevisionPreview,validRevision,type Revision,type RevisionContext,type RevisionPreview,type Operation,type Change} from './revisionTypes'
import {useReviewRequest} from './useReviewRequest'
import ReviewDocuments from './ReviewDocuments'
import {customerChangeText,customerEvidenceLabel,customerGroundedAdvice,customerReviewLocation,renderPlanReferences,unchangedInitialPlan} from './customerReviewDisplay'
type Props={selectedItemId?:string;onSelectItem?:(id:string)=>void;view?:ReviewView;
 onSelectRun?:(id:string,automatic?:boolean)=>void;onSelectDocument?:(id:string,automatic?:boolean)=>void;
 projectId:string;round:Round;active:boolean;disabled:boolean;onOpenTask:(id:string)=>void;
 initialRun?:string;initialDocument?:string;customer?:boolean;evidenceNames?:ReadonlyMap<string,string>}
export default function RevisionPanel(props:Props){return <Panel key={`${props.projectId}:${props.round.id}`} {...props}/>}
function Panel({selectedItemId,onSelectItem,view,onSelectRun,onSelectDocument,projectId,round,active,disabled,onOpenTask,initialRun,initialDocument,customer=false,evidenceNames}:Props){
 const {t,locale}=useI18n(),visible=useDocumentVisible(),api=useReviewRequest(),base=reviewBase(projectId),path=base+'/rounds/'+encodeURIComponent(round.id)
 const registerLeaveGuard=useContext(ReviewActivityContext),layered=!!view,editing=!view||view==='revision',showDocuments=!view||['comparison','response','documents'].includes(view)
 const showManuscript = editing || customer&&view==='documents'
 const [open,setOpen]=useState(!!initialRun||!!view),[context,setContext]=useState<RevisionContext|null>(null),[revisions,setRevisions]=useState<Revision[]>([]),[refresh,setRefresh]=useState(0),[selectedRun,setSelectedRun]=useState(initialRun??'')
 const [itemId,setItemId]=useState(''),[kind,setKind]=useState<Operation['kind']>('replace_paragraph'),[locationId,setLocationId]=useState(''),[content,setContent]=useState(''),[reason,setReason]=useState(''),[evidenceIds,setEvidenceIds]=useState<string[]>([]),[adoptionIds,setAdoptionIds]=useState<string[]>([]),[figureIds,setFigureIds]=useState<string[]>([]),[numericIds,setNumericIds]=useState<string[]>([]),[order,setOrder]=useState<string[]>([]),[operations,setOperations]=useState<Operation[]>([]),[preview,setPreview]=useState<RevisionPreview|null>(null),[publishedVersion,setPublishedVersion]=useState<ManuscriptVersion|null>(null)
 const selectedRef=useRef(selectedRun),activity=useRef(active);useLayoutEffect(()=>{selectedRef.current=selectedRun;activity.current=active&&editing},[selectedRun,active,editing])
 useEffect(()=>{if(initialRun!==undefined&&initialRun!==selectedRef.current){setSelectedRun(initialRun);setPublishedVersion(null)}},[initialRun])
 const [draftChanged,setDraftChanged]=useState(false)
 const dirty=useRef(false),contextBase=useRef<number|null>(null),[stale,setStale]=useState(false)
 const {request,run,available,busy,error,setError}=api
 const awaitingPlan=customer&&!round.items.length&&['queued','running'].includes(round.task?.status)
 const [readError,setReadError]=useState('')
 const selected=revisions.find(r=>r.id===selectedRun)??(!selectedRun?revisions[0]:undefined)
 useEffect(()=>{if(!open||!active||!visible||!available||awaitingPlan)return;let alive=true,timer=0
  async function load(){try{const [c,r]=await Promise.all([request(path+'/revision-context',(v):v is RevisionContext=>validRevisionContext(v,round.id)),request(path+'/revisions',(v):v is {items:Revision[]}=>object(v)&&Array.isArray(v.items)&&v.items.every(x=>validRevision(x,projectId,round.id)))]);if(!alive)return;setReadError('');if(!dirty.current){setContext(c);contextBase.current=c.plan_revision;setStale(false)}else if(contextBase.current!==c.plan_revision)setStale(true);setRevisions(r.items);if(!selectedRef.current&&r.items[0]&&active){setSelectedRun(r.items[0].id);if(customer)onSelectRun?.(r.items[0].id,true);else onSelectRun?.(r.items[0].id)}if(r.items.some(r=>['queued','running'].includes(r.task.status)||r.result&&r.output_status!=='published'))timer=window.setTimeout(()=>void load(),3000)}catch(cause){if(alive)setReadError(cause instanceof Error?cause.message:'修改成果读取失败。')}}void load();return()=>{alive=false;window.clearTimeout(timer)}
 },[open,active,visible,available,path,round.id,projectId,request,awaitingPlan,refresh,round.revision,onSelectRun,customer])
 useEffect(()=>{
  if(!selected?.result||selected.task.status!=='succeeded'||selected.output_status!=='published'||!showManuscript||!active||!visible||!available)return
  const c=new AbortController(), output=selected.result.output
  void request(manuscriptVersionPath(projectId,output.manuscript_id,output.revision),
   (value):value is ManuscriptVersion=>validManuscriptVersion(value,projectId,output.manuscript_id),undefined,c.signal)
   .then(version=>{
    if(!c.signal.aborted)setPublishedVersion(version.id===output.version_id&&version.revision===output.revision&&version.status==='published'?version:null)
   }).catch(()=>{})
  return()=>c.abort()
 },[selected,showManuscript,projectId,active,visible,available,request])
 function edit(){dirty.current=true;setDraftChanged(true);setPreview(null)}
 useReviewDraftGuard(draftChanged||!!(content||reason||operations.length||figureIds.length))
 const [visitedRuns,setVisitedRuns]=useState<string[]>([])
 if(selected?.output_status==='published'&&!visitedRuns.includes(selected.id))setVisitedRuns(old=>[...old,selected.id])
 const label=(id:string)=>{const i=round.items.find(i=>i.id===id);return i?reviewItemLabel(i.number,round.sources.find(s=>s.id===i.source_id)?.label,t):t('待补事项')}
 const locations=context?.locations.filter(l=>kind==='figure_caption'||kind==='remove_figure'?l.kind==='figure':kind==='section_title'||kind==='reorder_paragraphs'?l.kind==='section':l.kind==='paragraph')??[]
 const currentLocation=context?.locations.find(l=>l.id===locationId),sectionParagraphs=context?.locations.filter(l=>l.kind==='paragraph'&&l.section_id===locationId)??[]
 function selectLocation(id:string){edit();setLocationId(id);setOrder(context?.locations.filter(l=>l.kind==='paragraph'&&l.section_id===id).map(l=>l.id)??[])}
 function add(){if(!itemId||!locationId||!reason.trim()||!evidenceIds.length||!['reorder_paragraphs','remove_figure'].includes(kind)&&!content.trim()){setError('请选择意见、固定位置和证据，填写具体改文与理由。');return}edit();setOperations(old=>[...old,{item_id:itemId,kind,location_id:locationId,evidence_ids:evidenceIds,reason:reason.trim(),...(numericIds.length&&kind!=='remove_figure'?{numeric_bindings:context?.analysis_facts?.filter(f=>numericIds.includes(f.id)&&context.analysis_adoptions?.some(a=>adoptionIds.includes(a.id)&&a.source.id===f.source_id)).map(f=>({fact_id:f.id,value:f.value}))??[]}:{}),...(kind==='reorder_paragraphs'?{paragraph_ids:order}:kind==='remove_figure'?{}:{text:content})}]);setContent('');setReason('');setNumericIds([])}
 const body=context?{plan_revision:context.plan_revision,expected_current_revision:context.expected_current_revision,operations,analysis_adoption_ids:adoptionIds,...(figureIds.length?{figure_adoption_ids:figureIds}:{})}:null
 const checks=preview?[...preview.public_issues,...preview.constraint_issues].map(issue=>({
  severity:protocolLabel(severities,issue.severity),
  message:systemCheckText(issue.message)||t('检查说明不可用，请核对原始记录。'),
 })):[]
 const displayedChecks=customer?Array.from(new Map(checks.map(check=>[
  check.severity+'\n'+check.message,check,
 ])).values()):checks
 if(!available)return <p role="status">{t('会话或项目不可用，请重新打开项目。')}</p>
 return <section className="manuscript-panel" aria-label={t('有依据修改与成果')}><h3>{t(showDocuments&&layered?view==='response'?'逐条回复':view==='comparison'?'修改对照':'固定评审文档':'有依据修改与成果')}</h3>{!customer&&<button hidden={layered} type="button" onClick={()=>setOpen(v=>!v)}>{t(open?'收起本批修改':'执行本批修改')}</button>}{(open||layered)&&<>
 {customer&&!!revisions.length&&<label>{t('查看实际修改批次')}<select disabled={busy} value={selected?.id??''} onChange={e=>{setSelectedRun(e.target.value);setPublishedVersion(null);onSelectRun?.(e.target.value)}}>{revisions.map((r,i)=><option key={r.id} value={r.id}>{t('修改批次 {number}',{number:revisions.length-i})} · {customer?new Date(r.created_at).toLocaleString(locale):r.created_at} · {t(r.output_status==='published'?'公共新稿已完成':'等待实际成果')}</option>)}</select></label>}
 {customer&&selected?.result&&publishedVersion?.id===selected.result.output.version_id&&
  <section className="review-word-output" hidden={!showManuscript} aria-label={t('修订稿 Word')}>
   <ManuscriptExports projectId={projectId} manuscriptId={selected.result.output.manuscript_id}
    version={publishedVersion} active={active&&showManuscript} registerLeaveGuard={registerLeaveGuard} onOpenTask={onOpenTask}
    customerSci={round.project_type==='sci'} customerThesis={round.project_type==='thesis'} revisedResult/>
  </section>}
 <div hidden={!editing}><p>{t('本批使用固定材料和具体改文；未完成实验、文献与分析继续待补。任务成功和下载不会改变投稿或评审进展。')}</p>
 {disabled&&<p className="warning-panel">{t('请先保存本轮计划和重要决定，再执行本批修改。')}</p>}{stale&&<p className="warning-panel">{t('计划已有新版本；本地改文已保留，请先核对原基线。')}</p>}{awaitingPlan&&<p role="status">{t('正在读取本轮意见……')}</p>}{(error||readError)&&<p role="alert" className="error-panel">{t(error||readError)}</p>}
 <button disabled={busy} type="button" onClick={()=>setRefresh(n=>n+1)}>{t('刷新本批成果')}</button><button type="button" disabled={busy} onClick={()=>{dirty.current=false;setPreview(null);setStale(false);setRefresh(n=>n+1)}}>{t('保留操作并更新核对基线')}</button>
 {context&&<><p>{customer?t('改文以本轮选定的原稿为依据，采用后另存修订稿。'):t('固定父稿：版本 {base}；当前最新版本 {current}。本批仍以固定父稿另存新稿。',{base:context.manuscript.revision,current:context.expected_current_revision})}</p>
 <GroundedPlans context={context} round={round} label={label} customer={customer} evidenceNames={evidenceNames}/>
 <fieldset disabled={busy||disabled||stale}><legend>{t('具体修改操作')}</legend>{!!context.analysis_adoptions?.length&&<fieldset><legend>{t('本批采用的新分析')}</legend>{context.analysis_adoptions.map(a=><label key={a.id}><input type="checkbox" checked={adoptionIds.includes(a.id)} onChange={e=>{edit();setAdoptionIds(old=>e.target.checked?[...old,a.id]:old.filter(id=>id!==a.id));setNumericIds([])}}/>{t('本批采用分析')} · {a.source.label}</label>)}</fieldset>}{!!context.figure_adoptions?.length&&<fieldset><legend>{t('本批采用的新图')}</legend>{context.figure_adoptions.map(a=><label key={a.id}><input type="checkbox" checked={figureIds.includes(a.id)} onChange={e=>{edit();setFigureIds(old=>e.target.checked?[...old,a.id]:old.filter(id=>id!==a.id))}}/>{t('本批采用新图')} · {a.source.label}</label>)}</fieldset>}<label>{t('本次处理意见')}<select value={itemId} onChange={e=>{edit();setItemId(e.target.value)}}><option value="">{t('请选择')}</option>{round.items.map(i=><option key={i.id} value={i.id}>{label(i.id)} · {i.original_text}</option>)}</select></label>
 <label>{t('编辑操作')}<select value={kind} onChange={e=>{edit();setKind(e.target.value as Operation['kind']);setLocationId('');setContent('');setNumericIds([])}}>{Object.entries(operationNames).map(([k,v])=><option key={k} value={k}>{t(v)}</option>)}</select></label>
 <label>{t('固定修改位置')}<select value={locationId} onChange={e=>selectLocation(e.target.value)}><option value="">{t('请选择')}</option>{locations.map((l,i)=><option key={l.id} value={l.id}>{customer?customerReviewLocation(l,t):l.section_title??t('固定章节')} · {t('位置 {number}',{number:i+1})}{l.text&&' · '+l.text.slice(0,100)}</option>)}</select></label>{currentLocation?.text&&<blockquote>{currentLocation.text}</blockquote>}
 {kind==='remove_figure'?<p>{t('此操作明确移出旧图；仍需具体改写引用该图的正文，新图继续待补。')}</p>:kind==='reorder_paragraphs'?<ol>{order.map((id,i)=><li key={id}>{sectionParagraphs.find(p=>p.id===id)?.text}<button disabled={i===0} type="button" onClick={()=>{edit();setOrder(old=>{const n=[...old];[n[i-1],n[i]]=[n[i],n[i-1]];return n})}}>{t('上移段落')}</button></li>)}</ol>:kind==='bind_citation'?<label>{t('已有核验引用段落')}<select aria-label={t('具体修改内容')} value={content} onChange={e=>{edit();setContent(e.target.value)}}><option value="">{t('请选择')}</option>{context.citation_candidates.map(c=><option key={c.id} value={c.id}>{c.text}</option>)}</select></label>:<label>{t('具体修改内容')}<textarea value={content} onChange={e=>{edit();setContent(e.target.value)}}/></label>}
 {kind==='split_paragraph'&&<p>{t('用空白行分隔拆分后的段落。')}</p>}<fieldset><legend>{t(customer?'选择修改依据':'固定证据与版本')}</legend>{context.evidence.map(e=><div key={e.id}><label><input type="checkbox" checked={evidenceIds.includes(e.id)} onChange={x=>{edit();setEvidenceIds(old=>x.target.checked?[...old,e.id]:old.filter(id=>id!==e.id))}}/><EvidenceLabel evidence={e} customer={customer} names={evidenceNames}/></label><FixedEvidenceDetails evidence={e} customer={customer} names={evidenceNames}/></div>)}</fieldset>{!!adoptionIds.length&&kind!=='remove_figure'&&<fieldset><legend>{t('绑定本次改文的公开数值事实')}</legend><p>{t('逐值选择与具体改文一致的新事实；不会自动沿用旧样本量或 P 值。')}</p>{context.analysis_facts?.filter(f=>context.analysis_adoptions?.some(a=>adoptionIds.includes(a.id)&&a.source.id===f.source_id)).map(f=><label key={f.id}><input type="checkbox" checked={numericIds.includes(f.id)} onChange={e=>{edit();setNumericIds(old=>e.target.checked?[...old,f.id]:old.filter(id=>id!==f.id))}}/>{customer?f.value:t('绑定事实 {path} = {value}',{path:f.path,value:f.value})}</label>)}</fieldset>}<label>{t('修改理由')}<textarea value={reason} onChange={e=>{edit();setReason(e.target.value)}}/></label><button type="button" onClick={add}>{t('加入本批操作')}</button></fieldset>
 <ol>{operations.map((o,i)=><li key={i}>{label(o.item_id)} · {t(operationNames[o.kind])} · {(o.kind==='bind_citation'?context.citation_candidates.find(c=>c.id===o.text)?.text:o.text)??o.paragraph_ids?.map(id=>context.locations.find(l=>l.id===id)?.text).join(' → ')}<p>{o.reason}</p><button type="button" disabled={busy} onClick={()=>{edit();setOperations(old=>old.filter((_,n)=>n!==i))}}>{t('移除此操作')}</button></li>)}</ol>
 <button disabled={busy||disabled||stale||!(operations.length||figureIds.length)} type="button" onClick={()=>void run(async()=>setPreview(await request(path+'/revisions/preview',(v):v is RevisionPreview=>validRevisionPreview(v,context),body)))}>{t('预览实际差异与检查')}</button>
 {preview&&<><ChangeList changes={preview.actual_changes} label={label} customer={customer} evidenceNames={evidenceNames} locations={context.locations}/>{preview.unexecuted.map((u,i)=><p key={i} className="warning-panel">{label(u.item_id)} · {u.reason}</p>)}<h4>{t('公共检查与固定规范检查')}</h4>{displayedChecks.map((check,i)=><p key={i}>{check.severity} · {check.message}</p>)}{!preview.public_issues.length&&!preview.constraint_issues.length&&<p>{t('本次候选未发现公共硬错误；科学质量与未支持规范仍需人工核对。')}</p>}<button disabled={busy||disabled||stale||!preview.can_adopt||!preview.actual_changes.length} type="button" onClick={()=>void run(async()=>{const r=await request(path+'/revisions',(v):v is Revision=>validRevision(v,projectId,round.id),{...body,preview_sha256:preview.preview_sha256});setRevisions(old=>[r,...old.filter(x=>x.id!==r.id)]);if(activity.current){setSelectedRun(r.id);if(customer)onSelectRun?.(r.id,true);else onSelectRun?.(r.id)}setPreview(null);dirty.current=false;setDraftChanged(false);setOperations([]);setAdoptionIds([]);setFigureIds([]);setNumericIds([]);setRefresh(x=>x+1)})}>{t('统一采用并另存公共新稿')}</button></>}
 </>}
 </div>{!customer&&!!revisions.length&&<label>{t('查看实际修改批次')}<select disabled={busy} value={selected?.id??''} onChange={e=>{setSelectedRun(e.target.value);setPublishedVersion(null);onSelectRun?.(e.target.value)}}>{revisions.map((r,i)=><option key={r.id} value={r.id}>{t('修改批次 {number}',{number:revisions.length-i})} · {r.created_at} · {t(r.output_status==='published'?'公共新稿已完成':'等待实际成果')}</option>)}</select></label>}
 {selectedRun&&!selected&&<p role="alert">{t('指定修改批次不可用；不会自动替换为最新成果。')}</p>}
 {selected&&<article>
  <div hidden={!editing}>
   <p>{t(selected.output_status==='published'?'公共新稿已完成':'修改任务与公共稿件任务尚待完成')}</p>
   <button type="button" onClick={()=>onOpenTask(selected.task.id)}>{t('查看实际修改任务')}</button>
   <a href={revisionHash(projectId,round.id,selected.id)}>{t('此批固定成果链接')}</a>
   {selected.result&&<>
    <ChangeList changes={selected.result.actual_changes} label={label} customer={customer} evidenceNames={evidenceNames} locations={context?.locations}/>
    {selected.result.unexecuted.map((u,i)=><p key={i}>{label(u.item_id)} · {protocolLabel(unexecutedStates,u.status)} · {u.reason}</p>)}
    <button type="button" onClick={()=>onOpenTask(selected.result!.output.task_id)}>{t('查看公共稿件任务')}</button>
   </>}
  </div>
  {!customer&&selected.result&&publishedVersion?.id===selected.result.output.version_id&&<details hidden={!showManuscript}
   >
   <summary>{t('查看固定修改稿')}</summary>
   <ManuscriptPreview snapshot={publishedVersion.snapshot}/>
   <ManuscriptExports projectId={projectId} manuscriptId={selected.result.output.manuscript_id}
    version={publishedVersion} active={active&&showManuscript} registerLeaveGuard={registerLeaveGuard} onOpenTask={onOpenTask}/>
  </details>}
  {customer&&selected.result&&publishedVersion?.id===selected.result.output.version_id&&
   <div hidden={!showManuscript}>
    <ManuscriptPreview customerView customerSci={round.project_type==='sci'} snapshot={publishedVersion.snapshot} label="修订稿预览"/>
   </div>}
 </article>}
 {revisions.filter(r=>r.output_status==='published'&&visitedRuns.includes(r.id)).map(r=><div key={r.id} hidden={!showDocuments||selected?.id!==r.id}><ReviewDocuments selectedItemId={selectedItemId} onSelectItem={onSelectItem} view={view} customer={customer} evidenceNames={evidenceNames} onSelectDocument={onSelectDocument} documentDefaults={round.document_defaults} projectId={projectId} revision={r} projectType={context?.project_type??round.project_type} outputLanguage={context?.output_language??'zh-CN'} active={active&&showDocuments&&selected?.id===r.id} onOpenTask={onOpenTask} initialDocument={selected?.id===r.id?initialDocument:undefined}/></div>)}
 {!customer&&<p className="muted">{t('当前使用稳定章节、段落和图表定位；没有可核验的 PDF 页/行映射。Word/WPS 分页可能不同。')}</p>}
 </>}</section>
}
type GroundedProps = {
 context:RevisionContext;round:Round;label:(id:string)=>string;customer:boolean;evidenceNames?:ReadonlyMap<string,string>
}
function GroundedPlans({context,round,label,customer,evidenceNames}:GroundedProps) {
 const {t}=useI18n()
 const title=t('已有资料支持的具体计划')
 const plans=context.grounded_plans.map(plan=>{
  const item=round.items.find(item=>item.id===plan.item_id)
  const locations=plan.locations??context.locations.filter(location=>item?.locations?.some(chosen=>chosen.id===location.id))
  const positions=[...new Set(locations.map(location=>customerReviewLocation(location,t)))]
  let text=plan.plan
  if(customer){
   const saved=item?.plan
   if(plan.location_spans&&(saved===undefined||item&&round.generated_plan_locations?.[item.id]&&unchangedInitialPlan(round,item,round.revision))){
    const names=new Map(plan.evidence.map(source=>[source.id,customerEvidenceLabel(source,t,evidenceNames)]))
    const options=context.locations.map(location=>({...location,label:customerReviewLocation(location,t)}))
    text=renderPlanReferences(plan.plan,plan.location_spans,options,t,names)
   }else text=saved??customerGroundedAdvice(item?.category,t)
  }
  return <article key={plan.item_id}>
   <h5>{label(plan.item_id)}</h5>
   <blockquote>{plan.original_text}</blockquote>
   {customer&&positions.length>0&&<p>{positions.join('、')}</p>}
   <p>{text}</p>
   {customer
    ? <p>{customerChangeText(plan.existing_content,t)}</p>
    : <p>{typeof plan.existing_content==='string'?plan.existing_content:JSON.stringify(plan.existing_content)}</p>}
   {plan.evidence.map(evidence=><FixedEvidenceDetails key={evidence.id} evidence={evidence} customer={customer} names={evidenceNames}/>)}
   {plan.missing.map((message,index)=><p key={index} className="warning-panel">{message}</p>)}
  </article>
 })
 if(customer) return <section className="review-grounded-plans"><h4>{title}</h4>{plans}</section>
 return <details open><summary>{title}</summary>{plans}</details>
}

function ChangeList({changes,label,customer,evidenceNames,locations}:{
 changes:Change[];label:(id:string)=>string;customer:boolean;evidenceNames?:ReadonlyMap<string,string>;locations?:RevisionContext['locations']
}) {
 const {t}=useI18n()
 return <div className="review-change-list">{changes.map((change,index)=><article key={index}>
  <h4>{label(change.item_id)} · {customer
   ? customerReviewLocation(change.location,t)
   : [change.location.section_title,change.location.kind].join(' · ')}</h4>
  <dl>
   <dt>{t('修改前')}</dt>
   <dd>{customer?customerChangeText(change.before,t,change.kind,change.before,locations):<FixedChangeValue value={change.before}/>}</dd>
   <dt>{t('修改后')}</dt>
   <dd>{customer?customerChangeText(change.after,t,change.kind,change.before,locations):<FixedChangeValue value={change.after}/>}</dd>
   <dt>{t('修改依据')}</dt>
   <dd>{change.reason}{change.evidence.map(evidence=><FixedEvidenceDetails key={evidence.id} evidence={evidence} customer={customer} names={evidenceNames}/>)}</dd>
  </dl>
 </article>)}</div>
}
