import FrontMatterEditor from './FrontMatterEditor'
import SchoolRuleSuggestions from './SchoolRuleSuggestions'
import type {SuggestionSelection} from './suggestionContracts'
import type {FrontMatter} from './contracts'
import {useCallback,useEffect,useRef,useState,type ReactNode} from 'react'
import {apiFetch,onApiSessionChanged} from '../../shared/api/client'
import {STANDARD_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
import {apiError,safeError,useI18n} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import BatchUpload from '../files/BatchUpload'
import type {LibraryFile,FilePage} from '../files/fileLibraryApi'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import {type Profile,type Template,type Source,type Fact,type Chapter,type Section,emptyProfile,readable,isProfile,isTemplateList} from './contracts'
import './schoolTemplates.css'
import {customerSchoolTemplateView,type SchoolTemplateNavigation,type SchoolTemplateView} from '../projects/manuscriptViews'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {AdoptActions,ConflictCards,type AdoptionState} from './CustomerTemplateAdopt'
import {customerSource,lineRuleId,readableAttributes,readableRuleValue,ruleDetailLabel} from './templateSourceLabel'
import TemplateChangePreview from './TemplateChangePreview'
import {isBindingPreview,type AffectedManuscript,type BindingPreview} from './contracts'
type Props={projectId:string;active:boolean;customerView?:boolean;onChanged?:()=>void;navigation?:SchoolTemplateNavigation;onNavigate?:(next:SchoolTemplateNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard
 /** Customer only: called once a template is adopted or changed (not on every action like onChanged). */
 onAdopted?:(confirmationId:string)=>void
 /** Customer only: the place a return token points to; adds "完成并返回 {place}" beside the main button. */
 returnPlace?:string
 /** Customer only: "继续 写作资料与引用" after adoption. */
 onContinue?:()=>void
 /** Customer only: "迁移到新模板" on the change preview; called after the change succeeded (B04 task 6). */
 onOpenMigration?:(manuscriptId:string,revision:number,confirmationId:string)=>void}
class RequestFailure extends Error{readonly status:number;constructor(message:string,status:number){super(message);this.status=status}}
type BindingIntent={templateId:string;confirmationId:string;previousBinding:string|null}
const viewLabels:Record<SchoolTemplateView,string>={list:'模板列表',profile:'学校资料',upload:'新建模板版本',detail:'模板详情',rules:'解析规则',confirm:'规则确认',binding:'项目绑定'}
const fields = {school:'学校',department:'院系',major:'专业',degree_type:'学位类型',education_level:'培养层次',applicable_version:'适用年份 / 版本'} as const
const statusLabels:Record<string,string>={queued:'待执行',running:'运行中',succeeded:'已完成',failed:'执行失败'}
function Provenance({source,customerView=false}:{source?:Source;customerView?:boolean}){
 const {t}=useI18n()
 if(!source)return null
 if(customerView){
  const {label,quote}=customerSource(source)
  return <p className="template-provenance">{t('来源')}：{label}{quote&&` · ${quote}`}</p>
 }
 return <details className="template-provenance"><summary>{t('查看来源')}</summary><p>{source.text}</p><small>{source.part} · {source.path}</small></details>
}
const ruleIdLike=/^[\w.-]+$/
function FactList({title,items,customerView=false}:{title:string;items:(Fact|string)[];customerView?:boolean}){
 const {t}=useI18n()
 const rules=new Map(items.flatMap(item=>typeof item!=='string'&&item.id?[[item.id,item.value] as const]:[]))
 return <section><h4>{t(title)}</h4>{items.length?<ul>{items.map((item,index)=>{
  if(typeof item==='string')return <li key={index}>{item}</li>
  const label=customerView&&item.id&&item.value!==undefined?ruleDetailLabel(item.id,item.label&&!ruleIdLike.test(item.label)?item.label:undefined):item.label
  const value=item.value??item.text??item.message
  return <li key={index}><strong>{label}</strong> {customerView?readableRuleValue(item.id,value,rules.get(lineRuleId(item.id)??'')):readable(value)}<Provenance source={item.source} customerView={customerView}/></li>
 })}</ul>:<p className="muted">{t('无已记录项目')}</p>}</section>
}
const pageNumberFormats:Record<string,string>={decimal:'阿拉伯数字',upperRoman:'大写罗马数字',lowerRoman:'小写罗马数字',upperLetter:'大写英文字母',lowerLetter:'小写英文字母',chineseCounting:'中文数字',chineseCountingThousand:'中文数字',ideographTraditional:'中文数字'}
function SectionFacts({section,index,customerView=false}:{section:Section;index:number;customerView?:boolean}) {const {t}=useI18n();const pageLabels:Record<string,string>={width_cm:'页面宽度',height_cm:'页面高度',margin_top_cm:'上边距',margin_bottom_cm:'下边距',margin_left_cm:'左边距',margin_right_cm:'右边距'};const format=section.page_number?.format;return <li><h5>{t('第 {index} 节',{index:index+1})}</h5><p>{Object.entries(section.page??{}).map(([key,value])=>`${t(pageLabels[key]??key)} ${value} cm`).join(' · ')}</p><p>{t('首页不同')} {section.different_first_page?'✓':'—'} · {t('奇偶页不同')} {section.different_odd_even_pages?'✓':'—'}</p><p>{t('页码')} · {customerView?t(format?pageNumberFormats[format]??'其他编号格式':'未注明'):format??t('未注明')} · {section.page_number?.mode==='restart'?t('从 {start} 重新编号',{start:section.page_number.start??'—'}):t('延续或默认编号')}</p>{(['headers','footers'] as const).map(kind=><div key={kind}><strong>{t(kind==='headers'?'页眉':'页脚')}</strong><ul>{section[kind]?.map((part,i)=><li key={i}>{t({default:'默认',first:'首页',even:'偶数页'}[part.type]??(customerView?'其他页':part.type))} · {t(part.linked_to_previous?'链接前节':'本节定义')} · {part.text||t('无已记录文字')}{!customerView&&!!part.fields?.length&&<p>{t('域代码')}：{part.fields.join(' / ')}</p>}<Provenance source={part.source} customerView={customerView}/></li>)}</ul></div>)}<Provenance source={section.source} customerView={customerView}/></li>}
export default function SchoolTemplates(props:Props) {return <SchoolTemplatesPanel key={props.projectId} {...props}/>}
function SchoolTemplatesPanel({projectId,active,customerView=false,onChanged,navigation,onNavigate,registerLeaveGuard,onAdopted,returnPlace,onContinue,onOpenMigration}:Props) {
 const {t}=useI18n();const visible=useDocumentVisible()
 const layered=!!navigation;const currentView=customerView?customerSchoolTemplateView(navigation?.view??'list'):navigation?.view??'list'
 const uploadActive=active&&(!layered||currentView==='upload')
 const [visited,setVisited]=useState(active)
 useEffect(()=>{if(active)setVisited(true)},[active])
 const go=(view:SchoolTemplateView,templateId='')=>onNavigate?.({view,templateId})
 const [profile,setProfile]=useState<Profile|null>(null);const [draft,setDraft]=useState(emptyProfile)
 const [items,setItems]=useState<Template[]>([]);const [files,setFiles]=useState<LibraryFile[]>([]);const [filePage,setFilePage]=useState(1);const [fileTotal,setFileTotal]=useState(0)
 const [templateFile,setTemplateFile]=useState('');const [supplements,setSupplements]=useState<string[]>([]);const [manuscripts,setManuscripts]=useState<string[]>([])
 const [previous,setPrevious]=useState('')
 const [name,setName]=useState('');const [supplementText,setSupplementText]=useState('');const [showUpload,setShowUpload]=useState(false)
 const [uploadVisited,setUploadVisited]=useState(customerView&&currentView==='upload')
 useEffect(()=>{if(showUpload||customerView&&currentView==='upload')setUploadVisited(true)},[showUpload,customerView,currentView])
 const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [refresh,setRefresh]=useState(0);const [blocked,setBlocked]=useState(false)
 const baseline=useRef<Profile|null>(null)
 const draftRef=useRef(draft);draftRef.current=draft
 const intakeBaseline=useRef('')
 const intakeSignature=JSON.stringify({templateFile,supplements,manuscripts,previous,name,supplementText})
 if(!intakeBaseline.current)intakeBaseline.current=intakeSignature
 const profileDirty=!!baseline.current&&Object.keys(fields).some(key=>draft[key as keyof typeof fields]!==baseline.current![key as keyof typeof fields])
 const dirty=profileDirty||intakeSignature!==intakeBaseline.current
 useDraftLeaveGuard(registerLeaveGuard,!blocked&&dirty,busy)
 const profileConflict=!!profile&&profile.revision!==draft.revision
 const docxFiles=files.filter(file=>/\.docx$/i.test(file.filename))
 const supplementFiles=customerView?docxFiles:files.filter(file=>/\.(docx|pdf)$/i.test(file.filename))
 function adoptProfile(next:Profile){baseline.current=next;draftRef.current=next;setDraft(next)}
 function acceptProfile(next:Profile){
  if(baseline.current&&next.revision<baseline.current.revision)return
  const clean=!baseline.current||Object.keys(fields).every(key=>draftRef.current[key as keyof typeof fields]===baseline.current![key as keyof typeof fields])
  setProfile(next);if(clean)adoptProfile(next)
 }
 const [preview,setPreview]=useState<{templateId:string;body:unknown;data:BindingPreview}|null>(null)
 const controller=useRef(new AbortController());const alive=useRef(true);const operations=useRef(new Map<string,{body:string;key:string}>());const lock=useRef(false)
 const stop=useCallback(()=>{alive.current=false;controller.current.abort();setBlocked(true);setProfile(null);setDraft(emptyProfile);setItems([]);setFiles([]);setName('');setSupplementText('');setShowUpload(false);setTemplateFile('');setSupplements([]);setManuscripts([]);setPrevious('');setPreview(null);operations.current.clear()},[])
 useEffect(()=>{alive.current=true;if(controller.current.signal.aborted)controller.current=new AbortController();const pending=controller.current;const unsubscribe=onApiSessionChanged(stop);return()=>{alive.current=false;pending.abort();unsubscribe()}},[stop])
 const base=`/api/v1/projects/${encodeURIComponent(projectId)}`
 async function request<T>(path:string,init?:RequestInit,timeoutMs=15000):Promise<T>{
  const local=new AbortController();const cancel=()=>local.abort();const parent=controller.current.signal;parent.addEventListener('abort',cancel,{once:true});const timeout=window.setTimeout(cancel,timeoutMs)
  try {
  const response=await apiFetch(`${base}/${path}`,{...init,signal:local.signal});const result=await response.json().catch(()=>null)
  if(!alive.current||controller.current.signal.aborted)throw new DOMException('Aborted','AbortError')
  if([401,403,404].includes(response.status)&& (response.status!==404||result?.detail?.code==='project_not_found')){stop();throw new DOMException('Unavailable','AbortError')}
  if(!response.ok)throw new RequestFailure(apiError(result,response.status===409?'资料或版本已变化，请刷新后核对再重试。':'学校模板请求失败，请重试。'),response.status)
  return result as T
  } finally {window.clearTimeout(timeout);parent.removeEventListener('abort',cancel)}
 }
 useEffect(()=>{
  if(!active||!visible||blocked)return
  let current=true;let timer=0
  async function load(){try{
   const [next,list]=await Promise.all([request<Profile>('thesis-profile'),request<{items:Template[]}>('school-templates')])
   if(!current||!alive.current)return
   if(!isProfile(next)||!isTemplateList(list))throw new Error('学校模板请求失败，请重试。')
   acceptProfile(next);setItems(list.items);setError('')
   if(list.items.some(item=>['queued','running'].includes(item.task.status)))timer=window.setTimeout(()=>void load(),3000)
  }catch(cause){if(current&&alive.current)setError(safeError(cause,'学校模板请求失败，请重试。'))}}
  void load();return()=>{current=false;window.clearTimeout(timer)}
  // A refresh must not replace unsaved applicability edits.
  // eslint-disable-next-line react-hooks/exhaustive-deps
 },[base,active,visible,blocked,refresh])
 useEffect(()=>{
  if(!(customerView?uploadActive:active)||blocked)return;let current=true
  void request<FilePage>(`files?page=${filePage}&page_size=50`).then(page=>{if(current&&alive.current){setFiles(old=>filePage===1?page.items:[...old.filter(file=>!page.items.some(item=>item.id===file.id)),...page.items]);setFileTotal(page.total)}}).catch(cause=>{if(current&&alive.current)setError(safeError(cause,'学校模板请求失败，请重试。'))})
  return()=>{current=false}
  // eslint-disable-next-line react-hooks/exhaustive-deps
 },[base,active,blocked,refresh,filePage,customerView,uploadActive])
 async function mutate(path:string,body:unknown,idempotent=false,timeoutMs?:number){const serialized=JSON.stringify(body);let headers:Record<string,string>={'Content-Type':'application/json'}
  if(idempotent){const old=operations.current.get(path);const operation=old?.body===serialized?old:{body:serialized,key:crypto.randomUUID()};operations.current.set(path,operation);headers={...headers,'Idempotency-Key':operation.key}}
  return request<unknown>(path,{method:'POST',headers,body:serialized},timeoutMs)
 }
 async function run(action:()=>Promise<void|false>,changes=true){if(lock.current||blocked)return;lock.current=true;setBusy(true);setError('');try{const result=await action();if(alive.current&&changes&&result!==false){setRefresh(v=>v+1);onChanged?.()}}catch(cause){if(alive.current)setError(safeError(cause,'学校模板请求失败，请重试。'))}finally{lock.current=false;if(alive.current)setBusy(false)}}
 // A binding retry keeps the original confirmation and the binding the customer intended to replace.
 const confirmedIds=useRef(new Map<string,string>())
 const [adoption,setAdoption]=useState<(BindingIntent&{state:AdoptionState})|null>(null)
 const afterAdoption=useRef<((confirmationId:string)=>void)|null>(null)
 function finishAdoption(intent:BindingIntent){
  if(!alive.current)return
  setAdoption({...intent,state:'adopted'});setPreview(null);onAdopted?.(intent.confirmationId)
  const after=afterAdoption.current;afterAdoption.current=null;after?.(intent.confirmationId)
 }
 async function readBinding(intent:BindingIntent){
  let latest:Profile
  try{
   const value=await request<unknown>('thesis-profile',undefined,STANDARD_REQUEST_TIMEOUT_MS)
   if(!isProfile(value))throw new Error('学校模板请求失败，请重试。')
   latest=value
  }catch{
   if(alive.current)setAdoption({...intent,state:'bindUnknown'})
   return null
  }
  acceptProfile(latest)
  if(latest.bound_confirmation_id!==intent.confirmationId&&latest.bound_confirmation_id!==intent.previousBinding){
   afterAdoption.current=null;setPreview(null)
   throw new Error('学校模板资料已更新，请重新打开这份模板。')
  }
  return latest
 }
 async function adoptConfirmation(intent:BindingIntent,mode:'submit'|'retry'|'check'):Promise<void|false>{
  setAdoption(null)
  let latest=mode==='submit'?profile:await readBinding(intent)
  if(!latest)return false
  if(latest.bound_confirmation_id===intent.confirmationId)return finishAdoption(intent)
  if(mode==='check'){setAdoption({...intent,state:'bindFailed'});return}
  for(let attempt=0;attempt<2;attempt++){
   try{
    const next=await mutate('thesis-template-binding',{confirmation_id:intent.confirmationId,expected_revision:latest.revision},false,STANDARD_REQUEST_TIMEOUT_MS)
    if(!isProfile(next)||next.bound_confirmation_id!==intent.confirmationId)throw new Error('学校模板请求失败，请重试。')
    acceptProfile(next)
   }catch(cause){
    if(!alive.current)return
    const conflict=cause instanceof RequestFailure&&cause.status===409
    if(conflict||!(cause instanceof RequestFailure)||cause.status===408||cause.status>=500){
     latest=await readBinding(intent)
     if(!latest)return false
     if(latest.bound_confirmation_id===intent.confirmationId)return finishAdoption(intent)
     if(conflict&&attempt===0)continue
    }
    setAdoption({...intent,state:'bindFailed'});return
   }
   return finishAdoption(intent)
  }
 }
 // A pending write can finish after the first readback and before the ordinary profile refresh.
 useEffect(()=>{
  if(active&&adoption&&(!navigation||navigation.templateId===adoption.templateId)&&adoption.state!=='adopted'&&profile?.bound_confirmation_id===adoption.confirmationId)finishAdoption(adoption)
  // eslint-disable-next-line react-hooks/exhaustive-deps
 },[active,adoption,navigation?.templateId,profile?.bound_confirmation_id])
 function adopt(item:Template,body:unknown,after:((confirmationId:string)=>void)|null=null){return run(async()=>{
  afterAdoption.current=after
  let confirmationId=item.confirmation?.id??confirmedIds.current.get(item.id)
  if(!confirmationId){
   const saved=await mutate(`school-templates/${encodeURIComponent(item.id)}/confirm`,body,true) as {id?:unknown}|null
   if(typeof saved?.id!=='string')throw new Error('学校模板请求失败，请重试。')
   confirmationId=saved.id;confirmedIds.current.set(item.id,confirmationId)
  }
  return adoptConfirmation({templateId:item.id,confirmationId,previousBinding:profile?.bound_confirmation_id??null},'submit')
 })}
 // Changing an adopted template: read-only preview first. A confirmed target only needs its version and the
 // profile revision; otherwise the body is the confirmation body (a dry run). A 409 rereads the profile.
 function previewChange(item:Template,body:unknown){return run(async()=>{
  setPreview(null)
  const confirmed=!!(item.confirmation?.id??confirmedIds.current.get(item.id))
  const target={template_version_id:item.id,expected_revision:profile?.revision??0}
  let data:unknown
  try{data=await mutate('thesis-template-binding/preview',confirmed?target:{...(body as object),...target})}
  catch(cause){
   if(!(cause instanceof RequestFailure&&cause.status===409))throw cause
   const latest=await request<Profile>('thesis-profile');if(isProfile(latest))acceptProfile(latest)
   throw new Error('学校模板资料已更新，请重新打开这份模板。')
  }
  if(!isBindingPreview(data))throw new Error('学校模板请求失败，请重试。')
  if(alive.current)setPreview({templateId:item.id,body,data})
 },false)}
 function migrateAfterChange(item:Template,manuscript:AffectedManuscript){
  if(!preview)return
  return adopt(item,preview.body,confirmationId=>onOpenMigration?.(manuscript.manuscript_id,manuscript.revision,confirmationId))
 }
 function retryAdoption(item:Template){
  return adoption?.templateId===item.id?run(()=>adoptConfirmation(adoption,adoption.state==='bindUnknown'?'check':'retry')):Promise.resolve()
 }
 async function saveProfile(){if(!profile)return;if(profile.revision!==draft.revision)throw new Error('学校资料已在其他页面更新；草稿仍基于旧版本。请核对最新资料后重新填写。');const next=await request<Profile>('thesis-profile',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({...Object.fromEntries(Object.keys(fields).map(key=>[key,draft[key as keyof typeof fields].trim()])),expected_revision:draft.revision})});setProfile(next);adoptProfile(next)}
 async function create(){
  if(!customerView||profileDirty)await saveProfile()
  const result=await mutate('school-templates',{name:name.trim()||files.find(f=>f.id===templateFile)?.filename||'DOCX',school:draft.school.trim(),version_label:draft.applicable_version.trim(),template_file_id:templateFile,supplement_file_ids:supplements,manuscript_file_ids:manuscripts,supplement_text:supplementText,...(previous?{previous_version_id:previous}:{})},true)
  intakeBaseline.current=intakeSignature
  if(customerView&&result&&typeof result==='object'&&'id'in result&&typeof result.id==='string')go('detail',result.id)
 }
 if(!visited&&!active)return null
 return <section hidden={!active} className="school-templates project-form" aria-label={t('学校模板')}><header>{!customerView&&<h2>{t('学校模板')}</h2>}<p>{t(customerView?'核对规则后采用这份模板。改用其他模板后，可在章节与复核中核对差异并另存新版本。':'保存原始模板和新旧版本关系，确认后显式绑定。旧稿继续使用原模板，可在稿件页另存迁移版或上传修改稿。')}</p><button type="button" disabled={busy||blocked} onClick={()=>setRefresh(v=>v+1)}>{t('刷新学校模板')}</button></header>
 {error&&<p role="alert" className="error-panel">{t(error)}</p>}{blocked&&<p role="alert">{t('会话或项目访问已变化，请重新打开项目。')}</p>}
 {customerView&&profile&&navigation?.templateId&&!items.some(item=>item.id===navigation.templateId)&&
   <p role="alert">{t('指定学校模板版本不可用。')}</p>}
 {profileConflict&&!blocked&&<div className="warning-panel"><p role="alert">{t('学校资料已在其他页面更新；草稿仍基于旧版本。请核对最新资料后重新填写。')}</p><button type="button" disabled={busy} onClick={()=>{if(profile)adoptProfile(profile)}}>{t('使用最新学校资料')}</button></div>}
 {!blocked&&<>
 {layered&&<><nav className="school-view-nav" aria-label={t('学校模板视图')}>{(['list','profile','upload'] as const).map(view=><button key={view} type="button" aria-current={currentView===view?'page':undefined} onClick={()=>go(view)}>{t(viewLabels[view])}</button>)}</nav>
 {currentView==='list'&&<section aria-label={t('模板版本列表')}><div className="school-list-heading"><h3>{t('模板版本列表')}</h3><span className="muted">{t('共 {count} 个模板版本',{count:items.length})}</span></div>{items.length?<div className="school-template-list">{items.map(item=><article key={item.id}><div><strong>{item.name}</strong><p>{item.school} · {item.version_label||t('版本未注明')}</p><small>{t(statusLabels[item.task.status]??'状态未知')} · {t(item.confirmation?'已确认':'待确认')}{item.confirmation&&profile?.bound_confirmation_id===item.confirmation.id&&<> · {t(customerView?'当前采用的模板':'当前绑定版本')}</>}</small></div><button type="button" aria-label={t('查看模板 {name}',{name:item.name})} onClick={()=>go('detail',item.id)}>{t('查看模板')}</button></article>)}</div>:<p className="muted">{t('还没有模板版本，请先填写学校资料并上传模板。')}</p>}</section>}
 {['detail','rules','confirm','binding'].includes(currentView)&&<>{!customerView&&<nav className="school-view-nav" aria-label={t('模板详情视图')}>{(['detail','rules','confirm','binding'] as const).map(view=><button key={view} type="button" aria-current={currentView===view?'page':undefined} onClick={()=>go(view,navigation.templateId)}>{t(viewLabels[view])}</button>)}</nav>}{!items.some(item=>item.id===navigation.templateId)&&<p role="status">{t('模板版本尚未读取或已不可用，请返回列表核对。')}</p>}</>}
 </>}
 {customerView&&(uploadVisited||currentView==='upload')&&<section hidden={currentView!=='upload'} aria-label={t('上传学校论文模板')}>
   <h3>{t('上传学校论文模板')}</h3>
   <p>{t('模板原件须为 Word 文件。上传后在下方选择原件，补充规范须完成解析。')}</p>
   <BatchUpload projectId={projectId} active={uploadActive} embedded customerView schoolTemplate registerLeaveGuard={registerLeaveGuard}
     onUnavailable={stop} onChanged={()=>{setFilePage(1);setRefresh(v=>v+1)}}/>
 </section>}
 <form hidden={layered&&!['profile','upload'].includes(currentView)} onSubmit={event=>{event.preventDefault();void run(layered&&currentView==='profile'?saveProfile:create)}}><fieldset disabled={busy||!profile}><legend>{t(currentView==='upload'&&layered?'模板与来源材料':'适用信息')}</legend><div hidden={layered&&currentView!=='profile'}><p>{t('由上传者填写适用信息；未注明的年份或版本请如实记录，不以文件时间推断。')}</p><div className="project-fields">{Object.entries(fields).map(([key,label])=><label key={key}>{t(label)}<input required={key==='school'&&(!layered||currentView==='profile')} maxLength={key==='degree_type'||key==='education_level'?100:300} value={draft[key as keyof typeof fields]} onChange={event=>setDraft(old=>({...old,[key]:event.target.value}))}/></label>)}</div><button type="button" disabled={profileConflict||customerView&&!draft.school.trim()} onClick={()=>void run(saveProfile)}>{t('保存学校资料')}</button></div>
 <div hidden={layered&&currentView!=='upload'}>{layered&&<p>{t('当前学校')}：{draft.school||t('未填写')} · <button type="button" onClick={()=>go('profile')}>{t('编辑适用信息')}</button></p>}{!layered&&<h3>{t('模板与来源材料')}</h3>}
 {!customerView&&<><p>{t('每项来源只能选择一次；补充规范和已有稿件各最多 10 项。')}</p><button type="button" className="button-primary" onClick={()=>setShowUpload(value=>!value)} aria-expanded={showUpload}>{t('上传学校论文模板')}</button><p>{t('上传后在下方选择已保留的原件；补充规范必须完成文件解析。原模板内说明是规则来源，示例正文不代表所有专业。')}</p></>}
 <label>{t('模板名称')}<input value={name} onChange={event=>setName(event.target.value)} maxLength={200}/></label>
 <label>{t(customerView?'更新自以前的模板（可选）':'更新自模板版本（可选）')}<select value={previous} onChange={event=>setPrevious(event.target.value)}><option value="">{t('独立模板版本')}</option>{items.filter(item=>item.confirmation).map(item=><option key={item.id} value={item.id}>{item.name} · {item.version_label}</option>)}</select></label><p>{t(customerView?'上传新版本会保留原模板。':'上传新版本保留原模板；绑定不会自动迁移历史稿。')}</p>
 <label>{t(customerView?'模板 Word 原件':'模板 DOCX 原件')}<select required={!layered||currentView==='upload'} value={templateFile} onChange={event=>setTemplateFile(event.target.value)}><option value="">{t('请选择文件')}</option>{docxFiles.map(f=><option key={f.id} value={f.id}>{f.filename}</option>)}</select></label>
 <label>{t(customerView?'补充规范 Word':'补充规范 DOCX / PDF')}<select multiple value={supplements} onChange={event=>setSupplements(Array.from(event.target.selectedOptions,option=>option.value))}>{supplementFiles.map(f=><option key={f.id} value={f.id} disabled={f.parse_status!=='parsed'}>{f.filename}{f.parse_status!=='parsed'?` (${t('等待文件解析')})`:''}</option>)}</select></label>
 {!customerView&&<label>{t('已有稿件')}<select multiple value={manuscripts} onChange={event=>setManuscripts(Array.from(event.target.selectedOptions,option=>option.value))}>{files.filter(f=>/\.(docx|pdf)$/i.test(f.filename)).map(f=><option key={f.id} value={f.id}>{f.filename}</option>)}</select></label>}
 {files.length<fileTotal&&<button type="button" onClick={()=>setFilePage(page=>page+1)}>{t('读取更多原件')}</button>}
 <label>{t('补充规范文本')}<textarea rows={4} value={supplementText} onChange={event=>setSupplementText(event.target.value)} maxLength={20000}/></label><button className="button-primary" disabled={profileConflict||!templateFile||!draft.school.trim()||supplements.length>10||manuscripts.length>10||new Set([templateFile,...supplements,...manuscripts]).size!==1+supplements.length+manuscripts.length} type="submit">{t('提交模板解析')}</button></div></fieldset></form>
 {!customerView&&(showUpload||uploadVisited)&&<div hidden={!showUpload||layered&&currentView!=='upload'}><BatchUpload projectId={projectId} active={showUpload&&uploadActive} registerLeaveGuard={registerLeaveGuard} onUnavailable={stop} onChanged={()=>{setFilePage(1);setRefresh(v=>v+1)}}/></div>}
 {items.map(item=><TemplateReview active={active} customerView={customerView} onUnavailable={stop} onFork={()=>run(async()=>{const next=await mutate(`school-templates/${encodeURIComponent(item.id)}/fork`,{},true) as {id:string};go('confirm',next.id)})} hidden={layered&&(!['detail','rules','confirm','binding'].includes(currentView)||navigation.templateId!==item.id)} view={layered&&!customerView?currentView:undefined}
   adoption={adoption?.templateId===item.id?adoption.state:undefined} preview={preview?.templateId===item.id?preview.data:undefined}
   onPreview={body=>previewChange(item,body)} onKeep={()=>{setPreview(null);go('list')}} onConfirmChange={()=>{if(preview)void adopt(item,preview.body)}} onMigrate={onOpenMigration?manuscript=>void migrateAfterChange(item,manuscript):undefined} change={!!profile?.bound_confirmation_id&&profile.bound_confirmation_id!==item.confirmation?.id} returnPlace={returnPlace} onContinue={onContinue}
   onAdopt={body=>adopt(item,body)} onRetryAdoption={()=>retryAdoption(item)} registerLeaveGuard={registerLeaveGuard} key={`${item.id}:${item.analysis_sha256??'pending'}`} item={item} previousLabel={items.find(old=>old.id===item.previous_version_id)?.name} onUpdate={()=>{setPrevious(item.id);setName(item.name+' 更新版');setTemplateFile('');setShowUpload(true);go('upload')}} projectId={projectId} bound={!!item.confirmation&&profile?.bound_confirmation_id===item.confirmation.id} busy={busy} onConfirm={body=>run(async()=>{await mutate(`school-templates/${encodeURIComponent(item.id)}/confirm`,body,true);if(customerView)go('binding',item.id)})} onBind={()=>run(async()=>{const next=await mutate('thesis-template-binding',{confirmation_id:item.confirmation?.id,expected_revision:profile?.revision}) as Profile;acceptProfile(next)})} onRetry={()=>run(async()=>{await mutate(`school-templates/${encodeURIComponent(item.id)}/retry`,{},true)})}/>)}
 </>}</section>
}
type CustomerAdoptProps={adoption?:AdoptionState;change:boolean;returnPlace?:string;onContinue?:()=>void;onAdopt:(body:unknown)=>Promise<void>;onRetryAdoption:()=>Promise<void>
 preview?:BindingPreview;onPreview:(body:unknown)=>Promise<void>;onKeep:()=>void;onConfirmChange:()=>void;onMigrate?:(manuscript:AffectedManuscript)=>void}
function TemplateReview({item,previousLabel,onUpdate,projectId,bound,busy,onConfirm,onBind,onRetry,hidden,view,registerLeaveGuard,active,onFork,onUnavailable,customerView,adoption,change,returnPlace,onContinue,onAdopt,onRetryAdoption,preview,onPreview,onKeep,onConfirmChange,onMigrate}:{hidden?:boolean;view?:SchoolTemplateView;registerLeaveGuard?:RegisterLeaveGuard;item:Template;previousLabel?:string;onUpdate:()=>void;projectId:string;bound:boolean;busy:boolean;onConfirm:(body:unknown)=>Promise<void>;onBind:()=>Promise<void>;onRetry:()=>Promise<void>;active:boolean;onFork:()=>Promise<void>;onUnavailable:()=>void;customerView:boolean}&CustomerAdoptProps){
 const {t}=useI18n();const analysis=item.analysis;const [decisions,setDecisions]=useState<Record<string,string>>(()=>Object.fromEntries((item.confirmation?.decisions??[]).map(decision=>[decision.conflict_id,decision.option_id])));const [chapters,setChapters]=useState<Chapter[]>(()=>item.confirmation?.chapters??analysis?.chapters??[])
 const [textDecisions,setTextDecisions]=useState<Record<string,string>>(()=>Object.fromEntries((item.confirmation?.text_decisions??[]).map(decision=>[decision.id,decision.choice])))
 const [frontMatter,setFrontMatter]=useState<FrontMatter|null>(()=>item.confirmation?.front_matter??null)
 const [formatProfile,setFormatProfile]=useState(item.confirmation?.format_profile)
 const [suggestion,setSuggestion]=useState<SuggestionSelection|null>(null);const [suggestionPending,setSuggestionPending]=useState(false)
 const frontSources=item.front_matter_sources??analysis?.front_matter_sources??[]
 const invalidFront=!!frontMatter&&(frontMatter.fields.some(f=>!f.label.trim()||!frontSources.some(s=>s.id===f.source_id)||f.chapter_id!==null&&!chapters.some(c=>c.id===f.chapter_id))||frontMatter.content_requirements.some(r=>!chapters.some(c=>c.id===r.chapter_id)))
 const [reviewBaseline]=useState(()=>JSON.stringify({decisions,chapters,textDecisions,frontMatter,formatProfile}))
 useDraftLeaveGuard(registerLeaveGuard,!item.confirmation&&reviewBaseline!==JSON.stringify({decisions,chapters,textDecisions,frontMatter,formatProfile}),false)
 const textOptions=item.text_decision_options??[]
 const unresolvedText=textOptions.some(option=>!option.choices.includes(textDecisions[option.id] as 'text'|'attributes'))
 const unresolved=analysis?.conflicts.some(conflict=>!conflict.options.some(option=>option.id===decisions[conflict.id]))
 function ruleSection(title:string,children:ReactNode,open=false){
  return customerView?<section>{title&&<h4>{title}</h4>}{children}</section>:<details open={open}><summary>{title}</summary>{children}</details>
 }
 const invalidChapters=!chapters.length||chapters.length>300||chapters.some(chapter=>!chapter.title.trim()||!Number.isInteger(chapter.level)||chapter.level<1||chapter.level>9)
 const confirmBody=()=>({...(frontMatter?{front_matter:frontMatter}:{}),...(formatProfile?{format_profile:formatProfile}:{}),analysis_sha256:item.analysis_sha256,decisions:analysis!.conflicts.map(conflict=>({conflict_id:conflict.id,option_id:decisions[conflict.id]})),chapters:chapters.map(({id,title,level})=>({id,title:title.trim(),level})),...(textOptions.length?{text_decisions:textOptions.map(option=>({id:option.id,choice:textDecisions[option.id],source_sha256:option.source_sha256}))}:{}),...(suggestion?{schema_version:2,...suggestion}:{})})
 const chapterEditors=<>{chapters.map((chapter,index)=><div className="template-chapter" key={chapter.id}><label>{t('章节标题 {index}',{index:index+1})}<input maxLength={500} value={chapter.title} onChange={event=>setChapters(current=>current.map((entry,i)=>i===index?{...entry,title:event.target.value}:entry))}/></label><label>{t('标题级别 {index}',{index:index+1})}<input type="number" min="1" max="9" value={chapter.level} onChange={event=>setChapters(current=>current.map((entry,i)=>i===index?{...entry,level:Number(event.target.value)}:entry))}/></label><button type="button" onClick={()=>setChapters(current=>current.filter((_,i)=>i!==index))}>{t('移除此章节')}</button><Provenance source={chapter.source} customerView={customerView}/></div>)}<button type="button" onClick={()=>setChapters(current=>[...current,{id:crypto.randomUUID(),title:'',level:1}])}>{t('添加章节')}</button></>
 if(customerView){
  // One customer view (B04 task 5): status, remaining choices, conflict cards, chapters, text rules, front matter, one action.
  const frozen=!!item.confirmation
  const remaining=frozen||!analysis?0:analysis.conflicts.filter(conflict=>!conflict.options.some(option=>option.id===decisions[conflict.id])).length+textOptions.filter(option=>!option.choices.includes(textDecisions[option.id] as 'text'|'attributes')).length
  const ready=frozen||!!analysis&&!remaining&&!invalidFront&&!invalidChapters&&!!item.analysis_sha256
  // B04 task 6: changing another adopted template shows the read-only preview page in place of the review.
  if(preview&&adoption!=='adopted')return <article hidden={hidden} className="template-version" id={`template-${item.id}`}>
   <TemplateChangePreview preview={preview} targetRules={item.confirmation?.rules??analysis?.rules} busy={busy} bindFailed={adoption==='bindFailed'} bindUnknown={adoption==='bindUnknown'} onKeep={onKeep} onChange={onConfirmChange} onRetry={()=>void onRetryAdoption()} onMigrate={onMigrate}/>
  </article>
  return <article hidden={hidden} className="template-version" id={`template-${item.id}`}><header><h3>{item.name}</h3><p>{item.school} · {item.version_label||t('版本未注明')}</p><p role="status">{t(statusLabels[item.task.status]??'状态未知')}{bound&&<> · <strong>{t('当前采用的模板')}</strong></>}</p>{item.previous_version_id&&<p>{t('原模板版本')}：{previousLabel??t('原模板版本不可用')}</p>}{item.confirmation&&<button type="button" disabled={busy} onClick={onUpdate}>{t('上传此模板的新版本')}</button>}</header>
  <h4>{t('保留的来源原件')}</h4><ul>{(item.sources??[]).map(source=><li key={source.id}>{t({template:'模板原件',supplement:'补充规范',manuscript:'已有稿件'}[source.role]??'来源文件')} · {source.filename} <ProjectDownloadLink href={`/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(source.file_id)}/download`} filename={source.filename}>{t('下载原文件')}</ProjectDownloadLink></li>)}</ul>
  {item.supplement_text&&<section><h4>{t('补充规范文本')}</h4><p className="template-text">{item.supplement_text}</p></section>}
  {item.task.status==='failed'&&<><p role="alert">{t('模板解析失败，请保留原件后重试。')}</p><button type="button" disabled={busy} onClick={()=>void onRetry()}>{t('重试模板解析')}</button></>}
  {analysis&&<>
   {remaining>0&&<p className="template-remaining" role="status">{t('还有 {n} 处需要选择',{n:remaining})}</p>}
   <ConflictCards conflicts={analysis.conflicts} decisions={decisions} disabled={busy||frozen} onDecide={(conflictId,optionId)=>setDecisions(old=>({...old,[conflictId]:optionId}))}/>
   <fieldset disabled={busy||frozen}><legend>{t('章节核对')}</legend><p>{t('核对并保存本项目适用章节；模板章节可能只是示例。')}</p>{chapterEditors}</fieldset>
   {textOptions.length>0&&(!item.confirmation||!!item.confirmation.text_decisions?.length)&&<fieldset disabled={busy||frozen}><legend>{t('文字规范采用方式')}</legend><p>{t('原选择仅供参考；新版本须明确选择本次采用的来源。')}</p>{textOptions.map(option=><div key={option.id}><label>{t(option.label)}<select value={textDecisions[option.id]??''} onChange={event=>setTextDecisions(old=>({...old,[option.id]:event.target.value}))}><option value="">{t('请选择采用的来源值')}</option>{option.choices.includes('text')&&<option value="text">{t('采用文字说明')} · {option.text_value}</option>}<option value="attributes">{t('采用原样式属性')}</option></select></label><p>{option.source_text??t('原文字说明在此版本中缺失。')}</p>{option.changed&&<p className="warning-panel">{t('来源或样式已变化，请重新核对。')}</p>}{option.suggested_choice&&<p>{t('先前选择可沿用')}：{t(option.suggested_choice==='text'?'采用文字说明':'采用原样式属性')}</p>}<p>{t('原样式属性')}：{readableAttributes(option.attribute_value)}</p></div>)}</fieldset>}
   <FactList title="模板规则" items={item.confirmation?.rules??analysis.rules??[]} customerView/>
   <section><h4>{t('分节与页眉页脚实际属性')}</h4><ul>{analysis.sections?.map((section,index)=><SectionFacts key={section.id??index} section={section} index={index} customerView/>)}</ul></section>
   <FactList title="内嵌说明与引用" items={analysis.notes??[]} customerView/>
   <FactList title="缺失信息" items={item.confirmation?.missing??analysis.missing??[]} customerView/><FactList title="解析限制" items={item.confirmation?.unsupported??analysis.unsupported??[]} customerView/><FactList title="身份与签名字段" items={analysis.identity_fields??[]} customerView/><p>{t('姓名、学号及签名等必填字段须由本人核对；系统不会代签或推断身份。')}</p>
   <fieldset disabled={busy||frozen}><FrontMatterEditor customerView value={frontMatter} onChange={setFrontMatter} sources={frontSources} sections={analysis.sections} chapters={chapters}/>
   {item.available_format_profile==='bsu-gs501-academic-masters-2026'&&<label><input type="checkbox" checked={formatProfile===item.available_format_profile} onChange={event=>setFormatProfile(event.target.checked?item.available_format_profile:undefined)}/>{t('采用北体 GS501 学术型硕士排版')}</label>}</fieldset>
   <AdoptActions name={item.name} change={change} bound={bound} state={adoption} busy={busy} ready={ready} returnPlace={returnPlace} onContinue={onContinue}
    onAdopt={()=>{const body=frozen?{}:confirmBody();void(change?onPreview(body):onAdopt(body))}} onRetry={()=>void onRetryAdoption()}/>
  </>}
  </article>
 }
 return <article hidden={hidden} className="template-version" id={`template-${item.id}`}><header><h3>{item.name}</h3><p>{item.school} · {item.version_label||t('版本未注明')}</p><p role="status">{t(statusLabels[item.task.status]??'状态未知')}{bound&&<> · <strong>{t('当前绑定版本')}</strong></>}</p>{item.previous_version_id&&<p>{t('原模板版本')}：{previousLabel??item.previous_version_id}</p>}{item.confirmation&&<button type="button" disabled={busy} onClick={onUpdate}>{t('上传此模板的新版本')}</button>}</header>
 <div hidden={!!view&&view!=='detail'}><h4>{t('保留的来源原件')}</h4><ul>{(item.sources??[]).map(source=><li key={source.id}>{t({template:'模板原件',supplement:'补充规范',manuscript:'已有稿件'}[source.role]??'来源文件')} · {source.filename} <ProjectDownloadLink href={`/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(source.file_id)}/download`} filename={source.filename}>{t('下载原文件')}</ProjectDownloadLink></li>)}</ul>
 {item.supplement_text&&<details><summary>{t('补充规范文本')}</summary><p className="template-text">{item.supplement_text}</p></details>}
 {item.task.status==='failed'&&<><p role="alert">{t('模板解析失败，请保留原件后重试。')}</p><button type="button" disabled={busy} onClick={()=>void onRetry()}>{t('重试模板解析')}</button></>}</div>
 {analysis&&<><div hidden={!!view&&view!=='rules'}>
 {ruleSection(customerView?'':t('模板规则（{count} 项）',{count:(item.confirmation?.rules??analysis.rules??[]).length}),<FactList title="模板规则" items={item.confirmation?.rules??analysis.rules??[]}/>,view==='rules')}
 {ruleSection(t('分节与页眉页脚实际属性'),<ul>{analysis.sections?.map((section,index)=><SectionFacts key={section.id??index} section={section} index={index}/>)}</ul>)}
 {ruleSection(customerView?'':t('内嵌说明与引用（{count} 项）',{count:(analysis.notes??[]).length}),<FactList title="内嵌说明与引用" items={analysis.notes??[]}/>)}
 <FactList title="缺失信息" items={item.confirmation?.missing??analysis.missing??[]}/><FactList title="解析限制" items={item.confirmation?.unsupported??analysis.unsupported??[]}/><FactList title="身份与签名字段" items={analysis.identity_fields??[]}/><p>{t('姓名、学号及签名等必填字段须由本人核对；系统不会代签或推断身份。')}</p></div>
 {!customerView&&<div hidden={!!view&&view!=='confirm'}><SchoolRuleSuggestions projectId={projectId} item={item} active={active&&!hidden&&(!view||view==='confirm')} busy={busy} registerLeaveGuard={registerLeaveGuard} onSelection={setSuggestion} onPendingChange={setSuggestionPending} onFork={onFork} onUnavailable={onUnavailable}/></div>}
 <fieldset hidden={!!view&&view!=='confirm'} disabled={busy||!!item.confirmation}><legend>{t('章节配置')}</legend><p>{t('核对并保存本项目适用章节；模板章节可能只是示例。')}</p>{chapters.map((chapter,index)=><div className="template-chapter" key={chapter.id}><label>{t('章节标题 {index}',{index:index+1})}<input maxLength={500} value={chapter.title} onChange={event=>setChapters(current=>current.map((entry,i)=>i===index?{...entry,title:event.target.value}:entry))}/></label><label>{t('标题级别 {index}',{index:index+1})}<input type="number" min="1" max="9" value={chapter.level} onChange={event=>setChapters(current=>current.map((entry,i)=>i===index?{...entry,level:Number(event.target.value)}:entry))}/></label><button type="button" onClick={()=>setChapters(current=>current.filter((_,i)=>i!==index))}>{t('移除此章节')}</button><Provenance source={chapter.source}/></div>)}<button type="button" onClick={()=>setChapters(current=>[...current,{id:crypto.randomUUID(),title:'',level:1}])}>{t('添加章节')}</button>
 <h4>{t('规则冲突')}</h4>{analysis.conflicts?.map(conflict=><div key={conflict.id}><label>{conflict.label??t('规则冲突')}<select value={decisions[conflict.id]??''} onChange={event=>setDecisions(old=>({...old,[conflict.id]:event.target.value}))}><option value="">{t('请选择采用的来源值')}</option>{conflict.options.map(option=><option key={option.id} value={option.id}>{readable(option.value)} · {option.source?.text??option.source?.part??''}</option>)}</select></label>{conflict.options.map(option=><Provenance key={option.id} source={option.source}/>)}</div>)}
 {textOptions.length>0&&(!item.confirmation||!!item.confirmation.text_decisions?.length)&&<><h4>{t('文字规范采用方式')}</h4><p>{t('原选择仅供参考；新版本须明确选择本次采用的来源。')}</p>{textOptions.map(option=><div key={option.id}><label>{option.label}<select value={textDecisions[option.id]??''} onChange={event=>setTextDecisions(old=>({...old,[option.id]:event.target.value}))}><option value="">{t('请选择采用的来源值')}</option>{option.choices.includes('text')&&<option value="text">{t('采用文字说明')} · {option.text_value}</option>}<option value="attributes">{t('采用原样式属性')}</option></select></label><p>{option.source_text??t('原文字说明在此版本中缺失。')}</p>{option.changed&&<p className="warning-panel">{t('来源或样式已变化，请重新核对。')}</p>}{option.suggested_choice&&<p>{t('先前选择可沿用')}：{t(option.suggested_choice==='text'?'采用文字说明':'采用原样式属性')}</p>}<details><summary>{t('查看原样式属性')}</summary><p>{readable(option.attribute_value)}</p></details></div>)}</>}
 <FrontMatterEditor value={frontMatter} onChange={setFrontMatter} sources={frontSources} sections={analysis.sections} chapters={chapters}/>
 {item.available_format_profile==='bsu-gs501-academic-masters-2026'&&<label><input type="checkbox" checked={formatProfile===item.available_format_profile} onChange={event=>setFormatProfile(event.target.checked?item.available_format_profile:undefined)}/>{t('采用北体 GS501 学术型硕士排版')}</label>}
 {unresolved&&<p role="status">{t('请先逐项解决规则冲突。')}</p>}
 <button type="button" className="button-primary" disabled={suggestionPending||invalidFront||!!unresolved||unresolvedText||!chapters.length||chapters.length>300||!item.analysis_sha256||chapters.some(chapter=>!chapter.title.trim()||!Number.isInteger(chapter.level)||chapter.level<1||chapter.level>9)} onClick={()=>void onConfirm({...(frontMatter?{front_matter:frontMatter}:{}),...(formatProfile?{format_profile:formatProfile}:{}),analysis_sha256:item.analysis_sha256,decisions:analysis.conflicts.map(conflict=>({conflict_id:conflict.id,option_id:decisions[conflict.id]})),chapters:chapters.map(({id,title,level})=>({id,title:title.trim(),level})),...(textOptions.length?{text_decisions:textOptions.map(option=>({id:option.id,choice:textDecisions[option.id],source_sha256:option.source_sha256}))}:{}),...(suggestion?{schema_version:2,...suggestion}:{})})}>{t('确认模板规则')}</button></fieldset></>}
 {view==='binding'&&!item.confirmation&&<p>{t('请先完成规则确认，再绑定此模板版本。')}</p>}
 {item.confirmation&&<div hidden={!!view&&view!=='binding'} className="template-binding"><p>{t('规则已确认；绑定后才用于此项目，原解析与原件继续保留。')}</p>{!bound&&<button type="button" className="button-primary" disabled={busy} onClick={()=>void onBind()}>{t('绑定此确认版本')}</button>}</div>}
 </article>
}
