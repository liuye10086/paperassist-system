import {useEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError,useI18n} from '../../shared/i18n'
import {taskRequest,TaskRequestError} from '../tasks/taskApi'
import {manuscriptBase,roleLabels,sectionLabels,validManuscript,type Manuscript,type ManuscriptVersion,type Snapshot} from './manuscriptTypes'
import {canonical,displayed,record,validContext,validReview,type Review,type ReviewContext,type ReviewInput} from './reviewTypes'
import ManuscriptPreview from './ManuscriptPreview'
import ReviewEditors,{DecisionEditor} from './ReviewEditors'
import FrozenConfirmations from './FrozenConfirmations'
import {formatValue,metadataLabels,targetLabel,studyQuestion} from './reviewPresentation'
import ReviewSnapshot,{ReviewReport} from './ReviewSnapshot'
export type ReviewProps={projectId:string;manuscriptId:string;version:ManuscriptVersion;currentRevision:number;onPublished:(value:Manuscript)=>void;active?:boolean}
type Intent={url:string;body:string;key:string}&({kind:'create';preserveEdits?:boolean}|{kind:'publish';reviewId:string;candidate:Snapshot})
function validPublished(value:unknown,projectId:string,manuscriptId:string,version:ManuscriptVersion,reviewId:string,candidate:Snapshot):value is Manuscript{
 return validManuscript(value,projectId)&&value.id===manuscriptId&&value.current_revision>=version.revision+1&&value.versions.some(v=>v.revision===version.revision+1&&v.parent_version_id===version.id&&v.snapshot.review_provenance?.review_id===reviewId&&canonical(v.snapshot)===canonical(candidate))
}
const initialInput=(revision:number):ReviewInput=>({base_revision:revision,decisions:[],metadata:[],associations:[],corrections:[],selected_sources:[]})
const readFailure='资料检查读取失败，请回读记录重试。',unknownFailure='请求结果未确认；请回读记录或使用原请求重试。'
export default function ManuscriptReview(props:ReviewProps){return <ReviewWorkbench key={`${props.projectId}:${props.manuscriptId}:${props.version.id}:${props.version.revision}`} {...props}/>}
function ReviewWorkbench({projectId,manuscriptId,version,currentRevision,onPublished,active=true}:ReviewProps){
 const {t}=useI18n(),[context,setContext]=useState<ReviewContext|null>(null),[items,setItems]=useState<Review[]>([]),[selected,setSelected]=useState<Review|null>(null),[input,setInput]=useState(()=>initialInput(version.revision)),[error,setError]=useState(''),[loading,setLoading]=useState(false),[busy,setBusy]=useState(false),[validSession,setValidSession]=useState(true),[attempt,setAttempt]=useState(0),[uncertain,setUncertain]=useState(false),[stale,setStale]=useState(false),[category,setCategory]=useState('all'),[severity,setSeverity]=useState('all'),[readReady,setReadReady]=useState(false)
 const root=useRef<HTMLElement|null>(null),mounted=useRef(true),read=useRef<AbortController|null>(null),request=useRef<AbortController|null>(null),intent=useRef<Intent|null>(null)
 const base=`${manuscriptBase(projectId)}/${encodeURIComponent(manuscriptId)}/reviews`,historicalVersion=version.revision!==currentRevision||version.status!=='published'
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;read.current?.abort();request.current?.abort();intent.current=null}},[])
 useEffect(()=>onApiSessionChanged(()=>{read.current?.abort();request.current?.abort();read.current=null;request.current=null;intent.current=null;setValidSession(false);setContext(null);setItems([]);setSelected(null);setInput(initialInput(version.revision));setError('');setUncertain(false);setBusy(false);setLoading(false);setReadReady(false)}),[version.revision])
 useEffect(()=>{if(!active){read.current?.abort();request.current?.abort();return}if(!validSession)return;let live=true;const controller=new AbortController();read.current=controller
 async function load(){
  await Promise.resolve();if(!live||controller.signal.aborted)return;setLoading(true);setReadReady(false)
  const results=await Promise.allSettled([taskRequest(`${base}/context?revision=${version.revision}`,controller,(v):v is ReviewContext=>validContext(v,projectId,version),readFailure),taskRequest(base,controller,(v):v is {items:Review[]}=>record(v)&&Array.isArray(v.items)&&v.items.every(r=>validReview(r,projectId,manuscriptId))&&new Set(v.items.map(r=>(r as Review).id)).size===v.items.length,readFailure)])
  if(!live||read.current!==controller)return
  if(controller.signal.aborted){setError(readFailure);setReadReady(false);return}
  const [materials,history]=results
  if(materials.status==='fulfilled')setContext(materials.value)
  if(history.status==='fulfilled'){
   setItems(history.value.items)
   setSelected(old=>old?history.value.items.find(r=>r.id===old.id)??old:null)
   const pending=intent.current
   // List records do not identify the Idempotency-Key of a create intent.
   // Only an explicit retry with that unchanged key/body can resolve creation.
   if(pending?.kind==='publish'){
    const found=history.value.items.find(r=>r.id===pending.reviewId&&r.status==='published')
    if(found){
     try{
      const manuscript=await taskRequest(
       `${manuscriptBase(projectId)}/${encodeURIComponent(manuscriptId)}`,controller,
       (v):v is Manuscript=>validPublished(v,projectId,manuscriptId,version,found.id,found.candidate),readFailure)
      if(!live||controller.signal.aborted)return
      intent.current=null
      setUncertain(false)
      onPublished(manuscript)
     }catch(cause){
      if(live&&!controller.signal.aborted)setError(safeError(cause,readFailure))
      return
     }
    }
   }
  }
  if(materials.status==='rejected'||history.status==='rejected'){setError(readFailure);setReadReady(false)}else{setReadReady(true);setError(intent.current?unknownFailure:'')}
 }
 void load().finally(()=>{if(live&&read.current===controller)setLoading(false)})
 return()=>{live=false;controller.abort()}
 },[active,validSession,attempt,base,projectId,manuscriptId,version,onPublished])
 function locate(location:string){
  const nodes=[...(root.current?[root.current]:[]),...Array.from(root.current?.querySelectorAll<HTMLElement>('[data-review-location]')??[])]
  const node=nodes.find(n=>n.dataset.reviewLocation===location)??nodes.find(n=>location.endsWith(':'+n.dataset.reviewLocation))??(location.startsWith('section:')?Array.from(root.current?.querySelectorAll<HTMLElement>('[data-review-section]')??[]).find(n=>n.dataset.reviewSection===location.slice(8))??nodes.find(n=>n.dataset.reviewLocation==='sections'):undefined)
  if(!node)return
  for(let parent=node.parentElement;parent;parent=parent.parentElement)if(parent instanceof HTMLDetailsElement)parent.open=true
  if(node instanceof HTMLDetailsElement)node.open=true
  node.scrollIntoView?.({block:'center',behavior:'smooth'});node.focus()
 }
 function validInput(){
  if(input.decisions.some(d=>!d.reason.trim()||['supplied','selected'].includes(d.status)&&(!d.value.trim()||!d.evidence.trim())))return false
  if(input.metadata.some(m=>!m.value.trim()||!m.evidence.trim()||m.field==='display_precision'&&!/^(?:[0-9]|1[0-2])$/.test(m.value)))return false
  if(new Set(input.metadata.map(m=>`${m.target_id}:${m.field}`)).size!==input.metadata.length)return false
  if(input.associations.some(a=>!a.research_question.trim()||!a.evidence.trim()))return false
  return input.corrections.every(c=>c.text.trim()&&c.numeric_bindings.every(b=>context?.facts.some(f=>f.id===b.fact_id&&c.source_ids.includes(f.source_id))&&b.value.trim()))
 }
 async function send(next:Intent){
  if(request.current||!active||!validSession)return
  const controller=new AbortController();request.current=controller;intent.current=next;setBusy(true);setError('')
  const init={method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':next.key},body:next.body}
  try{
   if(next.kind==='create'){
    const result=await taskRequest(next.url,controller,(v):v is Review=>validReview(v,projectId,manuscriptId)&&v.base_revision===version.revision&&v.base_version_id===version.id&&canonical(v.input)===canonical(JSON.parse(next.body)),unknownFailure,init)
    if(!mounted.current||controller.signal.aborted)return
    intent.current=null;setUncertain(false);setItems(old=>[result,...old.filter(r=>r.id!==result.id)]);setSelected(result);if(!next.preserveEdits)setInput(initialInput(version.revision))
   }else{
    const result=await taskRequest(next.url,controller,(v):v is Manuscript=>validPublished(v,projectId,manuscriptId,version,next.reviewId,next.candidate),unknownFailure,init)
    if(!mounted.current||controller.signal.aborted)return
    intent.current=null;setUncertain(false);onPublished(result)
   }
  }catch(cause){if(!mounted.current||request.current!==controller)return
   if(cause instanceof TaskRequestError&&cause.status>=400&&cause.status<500){intent.current=null;setUncertain(false);if(cause.status===409){setStale(true);setError('基础版本或来源已变化，请重新读取稿件并选择当前版本；候选仍保留。')}else setError(safeError(cause,'资料检查输入无效，请核对目标、理由和证据。'))}
   else{setUncertain(true);setError(unknownFailure)}
  }finally{if(request.current===controller)request.current=null;if(mounted.current)setBusy(false)}
 }
 function create(refresh=false){if(busy||uncertain||historicalVersion||stale||!readReady||!context)return;if(!refresh&&!validInput()){setError('请填写理由、证据和已知事实绑定；显示小数位须为 0–12。');return}void send({url:base,body:JSON.stringify(refresh?initialInput(version.revision):input),key:crypto.randomUUID(),kind:'create',preserveEdits:refresh})}
 const disabled=busy||uncertain||!validSession||!active||historicalVersion||stale||!readReady,report=selected?.report
 const historyOnly=!!selected&&(selected.base_revision!==version.revision||selected.base_version_id!==version.id)
 const canPublish=selected&&selected.base_revision===version.revision&&selected.base_version_id===version.id&&selected.status==='candidate'&&report?.can_publish&&!historyOnly&&!disabled
 const issues=(report?.issues??context?.issues??[]).filter(i=>(category==='all'||i.category===category)&&(severity==='all'||i.severity===severity))
 return <section ref={root} className="manuscript-panel manuscript-review" data-review-location="manuscript" tabIndex={-1} aria-label={t('研究资料与检查')}><h3>{t('研究资料与检查')}</h3><p>{t('基础版本 {number}',{number:version.revision})} · {t('用户确认不代表科研验证；确定性检查无法判断自由文本的科学含义。')}</p>
 {historicalVersion&&<p className="warning-panel">{t('历史版本只读，请选择当前已发布版本后创建检查。')}</p>}
 <div className="manuscript-actions"><button type="button" disabled={busy||!validSession||!active} onClick={()=>setAttempt(n=>n+1)}>{t('回读检查记录')}</button><button type="button" disabled={disabled} onClick={()=>create(true)}>{t('重新检查并保存候选')}</button></div><p className="muted">{t('回读仅读取；重新检查会显式保存新候选，发布需再次确认。')}</p>
 {loading&&<p role="status">{t('正在读取研究资料……')}</p>}{error&&<p role="alert">{t(error)}</p>}{!validSession&&<p role="alert">{t('会话已失效，请重新登录。')}</p>}{uncertain&&<button type="button" disabled={busy||!active||!validSession} onClick={()=>intent.current&&void send(intent.current)}>{t('使用原请求重试')}</button>}
 {context&&<><details className="review-context" data-review-location="sections" tabIndex={-1} open><summary>{t('研究问题、方法与实际正文')}</summary><p data-testid="review-study-question"><strong>{t('研究问题')}</strong> · <span>{studyQuestion(version.snapshot,context.relationships.research_question,t)}</span></p><FrozenConfirmations snapshot={version.snapshot}/>{displayed(version.snapshot).map((p,index)=><article key={p.id} tabIndex={-1} data-review-location={p.id} data-review-section={p.section_id}><h4>{version.snapshot.thesis_context?(version.snapshot.sections?.find(s=>s.id===p.section_id)?.title??p.section_id):t(sectionLabels[p.section_id as keyof typeof sectionLabels])} · {t('段落')} {index+1}</h4><p>{p.text}</p><small>{p.source_ids.map(id=>version.snapshot.sources.find(s=>s.id===id)?.label??id).join(' · ')}</small></article>)}{version.snapshot.results_groups.flatMap(g=>g.figures).map(f=><article key={f.id} tabIndex={-1} data-review-location={f.id}><h4>{f.title}</h4><p>{f.caption}</p>{f.panels?.map((p,index)=><p key={p.label} tabIndex={-1} data-review-location={`panel:${f.id}:${index}`}>{p.label} · {p.description}</p>)}</article>)}</details>
 <details open><summary>{t('固定数值事实')}</summary><p>{t('同值不同指标各有独立身份；原始值不自动换算或重算。')}</p><div className="field-table-scroll"><table className="field-table"><thead><tr>{['来源','指标路径','原始精确值','单位','显示小数位'].map(s=><th key={s}>{t(s)}</th>)}</tr></thead><tbody>{context.facts.map(f=><tr key={f.id} tabIndex={-1} data-review-location={f.id}><td>{version.snapshot.sources.find(s=>s.id===f.source_id)?.label??f.source_id}</td><td>{f.path}<details><summary>{t('事实身份与依据')}</summary><p>{f.id}</p><p>{f.source_sha256}</p>{version.snapshot.review?.metadata.filter(m=>m.target_id===f.id).map((m,i)=><p key={i}>{t(metadataLabels[m.field])} · {m.value} · {m.evidence}{m.stale&&<> · {t('已过期，须重新确认')}</>}</p>)}</details></td><td>{f.value}</td>{(['unit','display_precision'] as const).map(field=><td key={field}>{version.snapshot.review?.metadata.find(m=>m.target_id===f.id&&m.field===field&&!m.stale)?.value??t('未知，待核实')}</td>)}</tr>)}</tbody></table></div>{!context.facts.length&&<p>{t('此版本没有固定统计数值。')}</p>}</details>
 <details><summary>{t('冻结的表格与参考文献')}</summary>{version.snapshot.results_groups.flatMap(g=>g.tables).map(table=><article key={table.id} tabIndex={-1} data-review-location={`table:${table.id}`}><h4>{table.title}</h4><div className="field-table-scroll"><table className="field-table"><thead><tr>{table.columns.map((column,i)=><th key={i}>{column}</th>)}</tr></thead><tbody>{table.rows.map((row,i)=><tr key={i}>{row.map((cell,j)=><td key={j}>{cell}</td>)}</tr>)}</tbody></table></div></article>)}<article data-review-location="references" tabIndex={-1}><h4>{t('参考文献')}</h4><ol>{version.snapshot.references.map(r=><li key={r.number} value={r.number}>{r.text}</li>)}</ol></article></details>
 <details><summary>{t('来源角色、版本与原始资料')}</summary>{version.snapshot.sources.map(s=><article key={s.id} data-review-location={s.id} tabIndex={-1}><strong>{s.label}</strong><p>{t(roleLabels[s.role])} · {s.kind}</p><details><summary>{t('来源版本与内容')}</summary><p>{s.id} · {s.sha256}</p><pre>{formatValue(s.content)}</pre></details></article>)}</details>
 {context.relationships.associations.length>0&&<details><summary>{t('已记录的研究关联')}</summary>{context.relationships.associations.map(a=><article key={a.id}><p>{a.research_question} · {[...a.method_ids,...a.source_ids,...a.paragraph_ids,...a.figure_ids].join(' · ')} · {a.evidence}</p><button type="button" disabled={disabled||input.associations.some(item=>item.id===a.id)} onClick={()=>setInput(old=>({...old,associations:[...old.associations,structuredClone(a)]}))}>{t('编辑关联')}</button></article>)}</details>}
 {(context.current_changes.length>0||version.current_changes.length>0)&&<aside className="warning-panel"><strong>{t('来源变化，原正文保持冻结')}</strong>{context.current_changes.map(c=><p key={c.id}>{version.snapshot.sources.find(s=>s.id===c.id)?.label??c.id} · {c.reasons.join(' · ')} <button type="button" onClick={()=>locate(c.id)}>{t('定位资料')}</button></p>)}</aside>}
 <div className="project-fields"><label>{t('问题类别')}<select value={category} onChange={e=>setCategory(e.target.value)}><option value="all">{t('全部')}</option>{['structure','numeric','unit','terminology','illustration','caption','reference','material','uncertainty','source'].map(c=><option key={c} value={c}>{t({structure:'结构',numeric:'数值',unit:'单位',terminology:'术语',illustration:'图表',caption:'图注',reference:'文献',material:'研究资料',uncertainty:'不确定性',source:'来源'}[c]!)}</option>)}</select></label><label>{t('问题级别')}<select value={severity} onChange={e=>setSeverity(e.target.value)}><option value="all">{t('全部')}</option><option value="error">{t('硬错误')}</option><option value="warning">{t('提醒')}</option><option value="human_review">{t('需人工核实')}</option></select></label></div>
 <fieldset disabled={disabled} className="review-issues"><legend>{t('问题与确认')}</legend>{issues.map(issue=><article key={issue.id}><p><strong>{t(issue.severity==='error'?'硬错误':issue.severity==='warning'?'提醒':'需人工核实')}</strong> · {t(targetLabel(issue.location))}</p><details><summary>{t('问题依据与预期')}</summary><p>{issue.id==='workflow:v2_scientific_language_review'?t(issue.message):issue.message}</p><p>{t('位置')} · {issue.location}</p><p>{t('实际内容')} · {formatValue(issue.actual)}</p><p>{t('期望内容')} · {formatValue(issue.expected)}</p><p>{t('证据依据')} · {formatValue(issue.source_evidence)}</p><p>{t('规则版本')} · {issue.rules_version}</p></details><button type="button" onClick={()=>locate(issue.location)}>{t('定位资料')}</button><DecisionEditor issue={issue} input={input} setInput={setInput} snapshot={version.snapshot}/></article>)}</fieldset>
 <ReviewEditors context={context} snapshot={version.snapshot} input={input} setInput={setInput} disabled={disabled}/><button type="button" disabled={disabled} onClick={()=>create()}>{t('生成检查候选')}</button></>}
 <details open><summary>{t('检查记录')}</summary>{items.map((r,i)=><article key={r.id}><p>{t('基础版本 {number}',{number:r.base_revision})} · {t(r.status==='published'?'已发布':'检查候选')} · {new Date(r.created_at).toLocaleString()}</p><button type="button" disabled={busy||!validSession||uncertain} onClick={()=>setSelected(r)}>{t('查看检查记录 {number}',{number:items.length-i})}</button></article>)}{!items.length&&!loading&&<p>{t('暂无检查记录。')}</p>}</details>
 {selected&&<div className="review-selected"><h4>{t('候选基于版本 {number}',{number:selected.base_revision})}</h4><ReviewReport report={selected.report} onLocate={locate}/>{(historyOnly||selected.base_revision!==version.revision)&&<p className="warning-panel">{t('该检查基于其他版本，仅供历史查阅；请基于当前版本重新检查。')}</p>}<details><summary>{t('本次提交的修正与来源选择')}</summary><pre>{formatValue(selected.input)}</pre></details><ReviewSnapshot review={selected.candidate.review!} historical={historyOnly} historicalNotice="该检查基于其他版本，仅供历史查阅；请基于当前版本重新检查。"/><ManuscriptPreview snapshot={selected.candidate} label="资料检查候选预览"/><button type="button" className="button-primary" disabled={!canPublish} onClick={()=>void send({url:`${base}/${encodeURIComponent(selected.id)}/publish`,body:JSON.stringify({expected_revision:selected.base_revision}),key:crypto.randomUUID(),kind:'publish',reviewId:selected.id,candidate:selected.candidate})}>{t('确认保存检查为新版本')}</button></div>}
 </section>
}
