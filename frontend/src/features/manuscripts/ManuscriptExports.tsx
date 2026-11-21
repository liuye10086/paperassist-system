import useManuscriptPendingRequest from './useManuscriptPendingRequest'
import useResearchDraft from '../research-results/useResearchDraft'
import {deliveryHref} from '../research-intake/deliveryPackageContracts'
import {isProfile,validFrontMatter} from '../school-templates/contracts'
import {ManuscriptDraftContext} from './manuscriptDraftContext'
import type {RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {useManuscriptDraft} from './useManuscriptDraft'
import SchoolExportPanel,{SchoolExportDetails} from './SchoolExportPanel'
import ManuscriptPresentation from './ManuscriptPresentation'
import PresentationExportDetails,{PresentationOutput} from './PresentationExportDetails'
import {type SavedPresentation,type PresentationBinding,type PresentationOutputPreview,historicalBlind,validPresentationExport} from './presentationTypes'
import {validSchoolExportPlan,type SchoolExportOptions,type SchoolExportPlan} from './schoolExportTypes'
import LayoutExports from '../layout-exports/LayoutExports'
import { useContext, useEffect, useRef, useState } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { apiError,safeError, useI18n } from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { taskRequest,TaskRequestError } from '../tasks/taskApi'
import {isWorkspace,isTask,sameInputVersion,type TaskWorkspace,type TaskView} from '../tasks/taskTypes'
import { useDocumentVisible } from '../tasks/useDocumentVisible'
import { manuscriptBase, validExport, type ManuscriptExport, type ManuscriptVersion } from './manuscriptTypes'
import PaperPlanSummary from './PaperPlanSummary'
import VersionLabel from '../../shared/VersionLabel'
// `autoStart`: the customer's adopted current version; its Word is generated once when it has none (B03).
// `onOpenMigration` (B04 task 11): opens the template migration of this version with the project's current template.
type Props={autoStart?:boolean;onAutoStarted?:()=>void;customerSci?:boolean;customerThesis?:boolean;revisedResult?:boolean;registerLeaveGuard?:RegisterLeaveGuard;projectId:string;manuscriptId:string;version:ManuscriptVersion;versions?:ManuscriptVersion[];onOpenTask?:(id:string)=>void;active?:boolean;onOpenMigration?:(manuscriptId:string,revision:number,confirmationId:string)=>void}
// The automatic thesis Word is preflighted at most once per version in this browser session, whatever its outcome.
const preflightKey=(projectId:string,versionId:string)=>`paperassist:auto-word-preflight:${projectId}:${versionId}`
function preflightDone(key:string){try{return sessionStorage.getItem(key)!==null}catch{return false}}
function markPreflight(key:string){try{sessionStorage.setItem(key,'1')}catch{/* storage unavailable: the mount guard still holds */}}
export default function ManuscriptExports(props:Props){return <Exports key={`${props.projectId}:${props.manuscriptId}:${props.version.id}`} {...props}/>}
function Exports({autoStart=false,onAutoStarted,customerSci=false,customerThesis=false,revisedResult=false,projectId,manuscriptId,version,versions,onOpenTask,active=true,registerLeaveGuard,onOpenMigration}:Props){
 const contextRegister=useContext(ManuscriptDraftContext),leaveRegister=registerLeaveGuard??contextRegister
 const {t,locale}=useI18n(),visible=useDocumentVisible();const [items,setItems]=useState(version.exports),[loaded,setLoaded]=useState(false),[error,setError]=useState(''),[actionError,setActionError]=useState(''),[busy,setBusy]=useState(false),[attempt,setAttempt]=useState(0),[sessionValid,setSessionValid]=useState(true)
 const school=!!version.snapshot.thesis_context
 const customer=customerSci||customerThesis
 const paperPlan=version.snapshot.paper_plan
 // Customer copy says Word; internal roles keep DOCX.
 const readFailed=customer?'Word 状态读取失败，请刷新。':'DOCX 状态读取失败，请刷新。',unconfirmed=customer?'Word 请求未确认，请刷新状态。':'DOCX 请求未确认，请刷新状态。'
 const wordTitle=t(revisedResult?'修订稿 Word':school?'毕业论文 Word':version.snapshot.sections&&(!paperPlan||version.snapshot.writing_provenance)?'完整稿 Word':customer?'稿件 Word':'事实稿 Word')
 const downloadName=t(revisedResult?'修订稿':school?'毕业论文':'稿件')
 const hasFront=validFrontMatter(version.snapshot.thesis_context?.confirmation?.front_matter)
 const reviewedSchoolOptions=customerThesis&&school&&version.snapshot.writing_provenance?.language_review_id
  ?version.snapshot.writing_provenance.school_export_options as SchoolExportOptions|undefined:undefined
 const initialOptions=():SchoolExportOptions=>version.snapshot.review_school_layout?.options??({
  manual_fields:{author:'',student_id:'',department:'',major:'',class_name:'',supervisor:'',submission_date:''},
  manual_chapters:[],english_title:'',keywords:[],include_toc:true,toc_depth:3,...(hasFront?{field_values:{}}:{}),
 })
 const [optionsDraft,setSchoolOptions]=useResearchDraft(projectId,`manuscript-export-options:${manuscriptId}:${version.id}`,initialOptions),[schoolPlan,setSchoolPlan]=useState<SchoolExportPlan|null>(null)
 const schoolOptions=reviewedSchoolOptions??optionsDraft
 const schoolRequest=school&&!reviewedSchoolOptions?{school:schoolOptions}:{}
 const [cleanOptions,setCleanOptions]=useState(()=>JSON.stringify(initialOptions()))
 const [presentation,setPresentation]=useState<SavedPresentation|null>(null),[languageView,setLanguageView]=useState<PresentationBinding['language_view']>(version.snapshot.output_language)
 // Blind review is removed (B04 task 0.5f): thesis customers only have the identified school Word flow, and saved
 // configurations (staff only) export identified output, so no request carries `review_mode`.
 const activePresentation=customerThesis?null:presentation
 const intent=useManuscriptPendingRequest({projectId,manuscriptId,versionId:version.id,operation:'exports'})
 const [outputPreview,setOutputPreview]=useState<PresentationOutputPreview|null>(null)
 useManuscriptDraft(school&&!reviewedSchoolOptions&&JSON.stringify(schoolOptions)!==cleanOptions||!!actionError||!!intent.pending,busy,registerLeaveGuard)
 const request=useRef<AbortController|null>(null),mounted=useRef(true),key=useRef<string>(crypto.randomUUID())
 const base=`${manuscriptBase(projectId)}/${encodeURIComponent(manuscriptId)}/versions/${version.revision}/exports`
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;request.current?.abort()}},[])
 useEffect(()=>onApiSessionChanged(()=>{request.current?.abort();setSessionValid(false);setItems([]);setPresentation(null);setOutputPreview(null);setSchoolPlan(null);setSchoolOptions({manual_fields:{author:'',student_id:'',department:'',major:'',class_name:'',supervisor:'',submission_date:''},manual_chapters:[],english_title:'',keywords:[],include_toc:true,toc_depth:3,...(hasFront?{field_values:{}}:{})});setError('');setActionError('');setMigrationTarget('')}),[hasFront])
 useEffect(()=>{if(!active||!visible||!sessionValid)return;let live=true,timer=0;const controller=new AbortController()
 async function load(){try{const data=await taskRequest(base,controller,(v):v is {items:ManuscriptExport[]}=>!!v&&typeof v==='object'&&'items'in v&&Array.isArray(v.items)&&v.items.every(e=>validExport(e,projectId,manuscriptId)&&e.version_id===version.id),readFailed);if(!live||controller.signal.aborted)return;setItems(data.items);setLoaded(true);setError('');if(data.items.some(e=>e.status==='queued'||e.status==='running'))timer=window.setTimeout(()=>void load(),3000)}catch(cause){if(live)setError(safeError(cause,readFailed))}}
 void load();return()=>{live=false;controller.abort();window.clearTimeout(timer)}},[base,projectId,manuscriptId,attempt,visible,sessionValid,active,version.id,readFailed])
 // B04 task 11: a thesis version made under the previously adopted template is refused (`task_source_conflict`). Only when
 // the project now uses another confirmation does the customer get the migration notice; other source changes keep the
 // general error.
 const [migrationTarget,setMigrationTarget]=useState('')
 async function templateChanged(cause:unknown,controller:AbortController){
  if(!customerThesis||!school||!(cause instanceof TaskRequestError)||cause.code!=='task_source_conflict')return false
  try{
   const profile=await taskRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/thesis-profile`,controller,isProfile,readFailed)
   const bound=profile.bound_confirmation_id
   if(!bound||bound===version.snapshot.thesis_context?.confirmation_id)return false
   if(mounted.current)setMigrationTarget(bound)
   return true
  }catch{return false}
 }
 async function preview():Promise<SchoolExportPlan|null>{if(request.current||!sessionValid)return null;const controller=new AbortController();request.current=controller;setBusy(true);setActionError('');setMigrationTarget('');try{const result=await taskRequest(`${base}/preview`,controller,(v):v is {schema_version:1;school:SchoolExportPlan}=>!!v&&typeof v==='object'&&'schema_version'in v&&v.schema_version===1&&'school'in v&&validSchoolExportPlan(v.school),'学校排版预览失败，请刷新。',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(schoolRequest)});if(mounted.current&&!controller.signal.aborted){setSchoolPlan(result.school);return result.school}return null}catch(cause){if(mounted.current&&!await templateChanged(cause,controller)&&mounted.current)setActionError(safeError(cause,'学校排版预览失败，请刷新。'));return null}finally{if(request.current===controller)request.current=null;if(mounted.current)setBusy(false)}}
 async function previewOutput(){if(request.current||!sessionValid||!activePresentation)return;const controller=new AbortController();request.current=controller;setBusy(true);setActionError('');const binding={presentation_version_id:activePresentation.id,language_view:languageView}
 try{
  const result=await taskRequest(`${base}/preview`,controller,(v):v is {schema_version:1;presentation:PresentationOutputPreview}=>
   !!v&&typeof v==='object'&&'schema_version'in v&&v.schema_version===1&&
   'presentation'in v&&validPresentationExport(v.presentation)&&Array.isArray((v.presentation as PresentationOutputPreview).preview_paragraphs)&&
   (v.presentation as PresentationOutputPreview).preview_paragraphs.every(p=>typeof p.id==='string'&&typeof p.text==='string'&&['zh-CN','en'].includes(p.target_language))&&
   typeof (v.presentation as PresentationOutputPreview).notice==='string'&&Object.entries(binding).every(([k,value])=>(v.presentation as PresentationOutputPreview).binding[k]===value),
   '输出配置保存或预览失败，请核对后重试。',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(binding)})
  if(mounted.current&&!controller.signal.aborted)setOutputPreview(result.presentation)
 }catch(cause){if(mounted.current)setActionError(safeError(cause,'输出配置保存或预览失败，请核对后重试。'))}finally{if(request.current===controller)request.current=null;if(mounted.current)setBusy(false)}}
 async function submit(retry?:ManuscriptExport,recover=false,automatic=false){
  if(request.current||!sessionValid||intent.pending&&!recover)return
  if(!recover&&!retry&&items.some(item=>item.status==='queued'||item.status==='running'))return
  const controller=new AbortController();request.current=controller;setBusy(true);setActionError('');setMigrationTarget('')
  try{
   let fixed=recover?intent.pending:null,workspace:TaskWorkspace|undefined
   if(!fixed){
    if(retry){
     workspace=await taskRequest(`/api/v1/tasks/${encodeURIComponent(retry.task_id)}/workspace`,controller,(v):v is TaskWorkspace=>isWorkspace(v,projectId,retry.task_id)&&v.task.task_type==='manuscript_docx'&&v.task.status==='failed'&&v.task.input_version.kind==='manuscript'&&v.task.input_version.manuscript_version_id===version.id&&v.allowed_actions.includes('retry'),unconfirmed)
     fixed=intent.begin(`/api/v1/tasks/${encodeURIComponent(retry.task_id)}/resume`,{operation:'retry',wait_id:workspace.wait?.id??null,expected_task_revision:workspace.task.revision,input_version:workspace.task.input_version},key.current)
    }else fixed=intent.begin(base,activePresentation?{presentation_version_id:activePresentation.id,language_view:languageView}:schoolRequest,automatic?`auto-word-${version.id}`:key.current)
   }
   if(!fixed)return
   if(automatic)onAutoStarted?.()
   if(fixed.url.endsWith('/resume')){
    const taskId=decodeURIComponent(fixed.url.split('/').at(-2)!),body=JSON.parse(fixed.body) as {expected_task_revision:number;input_version:TaskView['input_version']}
    workspace??=await taskRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/workspace`,controller,(v):v is TaskWorkspace=>isWorkspace(v,projectId,taskId)&&v.task.task_type==='manuscript_docx'&&sameInputVersion(v.task.input_version,body.input_version),unconfirmed)
    if(workspace.task.revision!==body.expected_task_revision){
     if(workspace.task.revision!==null&&workspace.task.revision>body.expected_task_revision){intent.complete();key.current=crypto.randomUUID();setAttempt(a=>a+1);setActionError('任务状态已推进，请按当前任务状态继续处理。');return}
     throw new TaskRequestError('任务状态已更新，请返回任务核对；原输入保留。',409)
    }
    if(!workspace.allowed_actions.includes('retry'))throw new TaskRequestError('当前任务不允许重试，请返回任务核对。',409)
    await taskRequest(fixed.url,controller,(v):v is TaskView=>isTask(v,projectId,taskId)&&sameInputVersion(v.input_version,body.input_version),unconfirmed,{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':fixed.key},body:fixed.body})
   }else{
    const result=await taskRequest(fixed.url,controller,(v):v is ManuscriptExport=>validExport(v,projectId,manuscriptId)&&v.version_id===version.id,unconfirmed,{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':fixed.key},body:fixed.body})
    if(mounted.current&&!controller.signal.aborted)setItems(old=>[result,...old.filter(e=>e.id!==result.id)])
   }
   if(mounted.current&&!controller.signal.aborted){intent.complete();key.current=school||presentation||retry||fixed.key.startsWith('auto-word-')?crypto.randomUUID():fixed.key;setCleanOptions(JSON.stringify(schoolOptions));setAttempt(a=>a+1)}
  }catch(cause){if(mounted.current){
   // The refusal of an old-template version is definite, so the request is released instead of shown as unconfirmed.
   if(await templateChanged(cause,controller)){if(mounted.current)intent.complete();return}
   if(!mounted.current)return
   if(cause instanceof TaskRequestError&&cause.status>=400&&cause.status<500&&cause.status!==408&&cause.status!==409)intent.complete();else intent.unknown();setActionError(safeError(cause,unconfirmed))}}
  finally{if(request.current===controller)request.current=null;if(mounted.current)setBusy(false)}
 }
 const pending=items.some(e=>e.status==='queued'||e.status==='running')
 // B04 task 10: a historical blind export is never this version's Word. Customers see the newest successful identified
 // Word as current, together with any newer attempt still running or failed; every other row is "earlier".
 const identifiedItems=items.filter(item=>!historicalBlind(item.presentation?.binding))
 const awaitingPublication=customer&&autoStart&&identifiedItems.length===0&&version.status!=='published'
 const currentIndex=identifiedItems.findIndex(item=>item.status==='succeeded')
 const currentItems=currentIndex<0?identifiedItems.slice(0,1):identifiedItems.slice(0,currentIndex+1)
 const earlierItems=items.filter(item=>!currentItems.includes(item))
 // Generated once per mount for an adopted, published version that has no Word yet. The key is the version, so a
 // remount, a second window or a lost response all land on the same export. Failed or unknown results are not retried.
 const autoStarted=useRef(false)
 const autoReady=autoStart&&active&&sessionValid&&loaded&&!error&&version.status==='published'&&identifiedItems.length===0&&!intent.pending
 // B04 task 11: a thesis Word is only submitted after the school layout preview allows it. A blocked or failed check is
 // not repeated for this version in this session; the customer is taken to the cover and contents options instead.
 const optionsHeading=useRef<HTMLHeadingElement>(null),[showOptions,setShowOptions]=useState(false)
 useEffect(()=>{if(showOptions)optionsHeading.current?.focus()},[showOptions])
 async function preflightAuto(){
  const key=preflightKey(projectId,version.id)
  if(preflightDone(key))return
  markPreflight(key)
  const plan=await preview()
  if(!mounted.current)return
  if(plan?.report.can_export){void submit(undefined,false,true);return}
  onAutoStarted?.()
  if(plan)setShowOptions(true)
 }
 // oxlint-disable-next-line react-hooks/exhaustive-deps
 useEffect(()=>{if(!autoReady||autoStarted.current)return;autoStarted.current=true;if(customerThesis&&school)void preflightAuto();else void submit(undefined,false,true)},[autoReady])
 // A historical blind export (blind review removed 2026-11-19) stays read-only: label and download only, keeping
 // its stored file name; no retry, layout derivation or language-confirmation reuse.
 // Customer rows: the version label carries the time the version was saved; the Word's own generation time follows.
 const generatedAt=(iso:string)=>{const time=new Date(iso);return Number.isNaN(time.getTime())?null:t('（生成于 {time}）',{time:time.toLocaleString(locale,{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})})}
 const exportRow=(item:ManuscriptExport,index:number)=>{const legacyBlind=historicalBlind(item.presentation?.binding);return <div key={item.id} className="manuscript-export"><strong>{customer?<><VersionLabel revision={version.revision} savedAt={version.created_at} current={item===identifiedItems[currentIndex]}/>{generatedAt(item.created_at)}</>:t('DOCX 导出 {number}',{number:items.length-index})}</strong> · <span role={item.status==='queued'||item.status==='running'?'status':undefined}>{t({queued:'待执行',running:'运行中',succeeded:'已完成',failed:'执行失败'}[item.status])}</span>{legacyBlind&&<> · <span className="status-badge">{t('历史盲审稿')}</span></>}
 {item.presentation&&!legacyBlind&&!customer&&<p>{t(item.presentation.binding.language_view==='en'?'英文':item.presentation.binding.language_view==='zh-CN'?'中文':'中英逐段对照')} · {t('已保存输出配置')}</p>}
 {item.status==='succeeded'&&item.download_url&&<><ProjectDownloadLink href={item.download_url} filename={(legacyBlind||customer)&&item.filename?item.filename:customer
  ? downloadName+'.docx'
  : `manuscript-v${version.revision}.docx`}>{t(customer?'下载这份 Word':'下载 DOCX')}</ProjectDownloadLink>{!customer&&!legacyBlind&&item.sha256&&<>{item.school?.plan.toc.enabled?<p className="muted">{t('学校目录已完成排版，请直接下载 Word。')}</p>:<LayoutExports registerLeaveGuard={leaveRegister} projectId={projectId} sourceKind="manuscript_export" sourceId={item.id} sourceSha256={item.sha256} sourceLabel={t('稿件 v{revision} · DOCX 导出 {number}',{revision:version.revision,number:items.length-index})} active={active&&sessionValid} onOpenTask={onOpenTask}/>}</>}</>}
 {customer&&item.status==='failed'?<p className="error-panel">{t(onOpenTask&&!legacyBlind?'这一版 Word 没有生成成功。请先查看任务结果。':'这一版 Word 没有生成成功。')}</p>:item.error_code&&<div className="error-panel">{t(apiError({code:item.error_code},'导出失败，请查看导出任务中的处理说明或重试。'))}{!customer&&<details><summary>{t('高级诊断信息')}</summary><span>{item.error_code}</span></details>}</div>}
 {item.school&&<SchoolExportDetails plan={item.school.plan} report={item.school.report} fieldUpdate={item.school.field_update} customerView={customerThesis}/>}
 {item.presentation&&!(customer&&legacyBlind)&&<PresentationExportDetails customerView={customer} figures={[...version.snapshot.results_groups.flatMap(group=>group.figures),...(versions?.find(v=>v.id===item.presentation?.binding.peer_version_id)?.snapshot.results_groups.flatMap(group=>group.figures)??[])]} value={item.presentation}/>}
 {item.status==='failed'&&!legacyBlind&&<button type="button" disabled={busy||!sessionValid||!!intent.pending} onClick={()=>void submit(item)}>{t(customer?'重试':'重试 DOCX')}</button>}
 {onOpenTask&&(!customer||item.status==='failed'&&!legacyBlind)&&<button type="button" onClick={()=>onOpenTask(item.task_id)}>{t(customer?'查看任务结果':'查看导出任务')}</button>}</div>}
 function selectPresentation(value:SavedPresentation|null){
  if(value?.id!==presentation?.id){key.current=crypto.randomUUID();if(value?.config.language_review)setLanguageView(value.config.language_review.language_view)}
  setPresentation(value);setOutputPreview(null)
  if(value?.config.school)setCleanOptions(JSON.stringify(value.config.school.options))
 }
 return <section className="manuscript-panel" aria-label={t(customer?'Word':'DOCX 导出')}><h4>{customer?wordTitle:t('DOCX 导出')}</h4>{!customer&&<p><a href={deliveryHref(projectId,(version.snapshot as unknown as {research_bridge?:{delivery_id?:string}}).research_bridge?.delivery_id)}>{t('进入当前项目交付登记（选择已有成果）')}</a></p>}{!revisedResult&&<p className="muted">{t(school?customer?'稿件和 Word 分别保存，重新生成 Word 不会改动稿件。':'学校稿与 DOCX 分别保存状态。':version.snapshot.sections?(customer?'Word 按所选固定版本导出正文、图表和引用。':'完整稿与 DOCX 分别保存状态。导出七部分、图表、实际引用和待办。'):customer?'Word 按所选固定版本导出写作材料、图表和引用。':'事实稿与 DOCX 分别保存状态。仅导出两章、图表、实际引用和待办。')}</p>}
 {!customer&&<p>{t(school?'毕业论文 Word · 版本 {number}':version.snapshot.sections?'完整稿 Word · 版本 {number}':'事实稿 Word · 版本 {number}',{number:version.revision})}</p>}
 {paperPlan&&<PaperPlanSummary plan={paperPlan} heading="本版 Word 使用的章节与图表" filesOnly
  migration={customerThesis&&version.snapshot.thesis_context&&version.snapshot.school_change_provenance?.kind==='template_migration'
   ?{chapters:version.snapshot.thesis_context.chapters,mappings:version.snapshot.school_change_provenance.mappings}:undefined}/>}
 {sessionValid&&!error&&awaitingPublication&&(version.status==='pending'
  ?<p role="status">{t('正在发布第 {number} 版稿件。发布完成后会自动准备 Word。',{number:version.revision})}</p>
  :<><p role="alert">{t('第 {number} 版稿件发布失败，无法生成 Word。',{number:version.revision})}</p>
   {onOpenTask&&<button type="button" onClick={()=>onOpenTask(version.task_id)}>{t('查看任务结果')}</button>}</>)}
 {sessionValid&&loaded&&!error&&!intent.pending&&identifiedItems.length===0&&!awaitingPublication&&!(customer&&busy)&&<p>{t(revisedResult?'修订稿尚未生成 Word。':'当前版本尚未生成 Word。')}</p>}
 {sessionValid&&loaded&&!error&&(pending||customer&&busy&&!intent.pending&&identifiedItems.length===0)&&<p role={customer?'status':undefined}>{t(customer?'正在准备这一版的 Word……':'Word 正在生成，请等待任务完成。')}</p>}
 {sessionValid&&intent.pending&&(customer?!busy&&<div className="warning-panel"><p>{t('暂时无法确定这次提交是否成功。请先查看提交结果。')}</p><button type="button" onClick={()=>void submit(undefined,true)}>{t('查看提交结果')}</button></div>:<div className="warning-panel"><p>{t('Word 提交结果待核对，原请求和固定输入已保留。')}</p><p>{t('先刷新已有记录；列表不能确认原请求时，可显式用原请求重试。')}</p><button type="button" disabled={busy} onClick={()=>void submit(undefined,true)}>{t('用原请求重试 Word')}</button></div>)}
 {customer?<>{currentItems.map(item=>exportRow(item,items.indexOf(item)))}{earlierItems.length>0&&<section aria-label={t('之前生成的 Word')}><h5>{t('之前生成的 Word')}</h5>{earlierItems.map(item=>exportRow(item,items.indexOf(item)))}</section>}</>:items.map(exportRow)}
 {versions&&<fieldset disabled={busy||!!intent.pending||!sessionValid}><ManuscriptPresentation projectId={projectId} manuscriptId={manuscriptId} version={version} versions={versions} exports={items} active={active&&sessionValid} schoolOptions={school?schoolOptions:undefined} onSchoolOptions={value=>{setSchoolOptions(value);setCleanOptions(JSON.stringify(value));setSchoolPlan(null)}} onSelect={selectPresentation}/></fieldset>}
 {!customerThesis&&presentation&&<fieldset disabled={busy||pending||!!intent.pending||!sessionValid}><legend>{t('固定配置导出选项')}</legend><p>{t('配置版本 {number}',{number:presentation.revision})} · {t('已保存')}</p><label>{t('输出语言视图')}<select disabled={!!presentation.config.language_review} value={languageView} onChange={e=>{setOutputPreview(null);if(e.target.value!==languageView)key.current=crypto.randomUUID();setLanguageView(e.target.value as PresentationBinding['language_view'])}}><option value="zh-CN">{t('中文')}</option><option value="en">{t('英文')}</option><option value="zh-CN-en">{t('中英逐段对照')}</option></select></label><p>{t('导出固定所选保存配置；编辑草稿需另存新版本。')}</p>{presentation.config.language_review&&<p>{t('本配置语言确认绑定当前语言；其他语言视图须移除确认后另存配置。')}</p>}<button type="button" onClick={()=>void previewOutput()}>{t('预览固定输出')}</button></fieldset>}
 {outputPreview&&<PresentationOutput value={outputPreview}/>}
 {school&&sessionValid&&<SchoolExportPanel headingRef={customerThesis?optionsHeading:undefined} version={version} value={schoolOptions} readOnly={!!reviewedSchoolOptions} customerView={customerThesis} revisedResult={revisedResult}
  onChange={value=>{if(!activePresentation&&JSON.stringify(value)!==JSON.stringify(schoolOptions))key.current=crypto.randomUUID();setSchoolOptions(value);setSchoolPlan(null)}}
  onPreview={()=>void preview()} busy={busy} disabled={pending||!!intent.pending||version.status!=='published'} plan={schoolPlan}/>}
 <div className="manuscript-actions"><button type="button" disabled={busy||pending||!!intent.pending||version.status!=='published'||!sessionValid||
  ((customerThesis||!activePresentation)&&schoolPlan?.report.can_export===false)||activePresentation?.can_export===false}
  onClick={()=>void submit()}>{t(busy?'正在提交……':customer?identifiedItems.length?'重新生成 Word':'生成 Word':'生成 DOCX')}</button><button type="button" disabled={busy||!sessionValid} onClick={()=>setAttempt(a=>a+1)}>{t(customer?'刷新 Word 状态':'刷新 DOCX 状态')}</button></div>
 {migrationTarget&&<div role="alert" className="warning-panel"><p>{t('这一版用的是之前的学校模板。已下载的 Word 保持原样；要按新模板导出，需要先把稿件迁移到新模板。')}</p>{onOpenMigration&&<button type="button" onClick={()=>onOpenMigration(manuscriptId,version.revision,migrationTarget)}>{t('迁移到新模板')}</button>}</div>}
 {actionError&&<p role="alert" className="error-panel">{t(actionError)}</p>}{error&&<p role="alert" className="error-panel">{t(error)}</p>}{!sessionValid&&<p role="alert">{t('会话已失效，请重新登录。')}</p>}

 </section>
}
