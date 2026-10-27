import {useCallback,useEffect,useRef,useState} from 'react'
import {apiFetch,onApiSessionChanged} from '../../shared/api/client'
import {apiError,safeError,useI18n} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import BatchUpload from '../files/BatchUpload'
import type {LibraryFile,FilePage} from '../files/fileLibraryApi'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import {type Profile,type Template,type Source,type Fact,type Chapter,type Section,emptyProfile,readable,isProfile,isTemplateList} from './contracts'
import './schoolTemplates.css'
import type {SchoolTemplateNavigation,SchoolTemplateView} from '../projects/manuscriptViews'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
type Props={projectId:string;active:boolean;onChanged?:()=>void;navigation?:SchoolTemplateNavigation;onNavigate?:(next:SchoolTemplateNavigation)=>void;registerLeaveGuard?:RegisterLeaveGuard}
const viewLabels:Record<SchoolTemplateView,string>={list:'模板列表',profile:'学校资料',upload:'新建模板版本',detail:'模板详情',rules:'解析规则',confirm:'规则确认',binding:'项目绑定'}
const fields = {school:'学校',department:'院系',major:'专业',degree_type:'学位类型',education_level:'培养层次',applicable_version:'适用年份 / 版本'} as const
const statusLabels:Record<string,string>={queued:'待执行',running:'运行中',succeeded:'已完成',failed:'执行失败'}
function Provenance({source}:{source?:Source}) {const {t}=useI18n();return source?<details className="template-provenance"><summary>{t('查看来源')}</summary><p>{source.text}</p><small>{source.part} · {source.path}</small></details>:null}
function FactList({title,items}:{title:string;items:(Fact|string)[]}){const {t}=useI18n();return <section><h4>{t(title)}</h4>{items.length?<ul>{items.map((item,index)=><li key={index}>{typeof item==='string'?item:<><strong>{item.label}</strong> {readable(item.value??item.text??item.message)}<Provenance source={item.source}/></>}</li>)}</ul>:<p className="muted">{t('无已记录项目')}</p>}</section>}
function SectionFacts({section,index}:{section:Section;index:number}) {const {t}=useI18n();const pageLabels:Record<string,string>={width_cm:'页面宽度',height_cm:'页面高度',margin_top_cm:'上边距',margin_bottom_cm:'下边距',margin_left_cm:'左边距',margin_right_cm:'右边距'};return <li><h5>{t('第 {index} 节',{index:index+1})}</h5><p>{Object.entries(section.page??{}).map(([key,value])=>`${t(pageLabels[key]??key)} ${value} cm`).join(' · ')}</p><p>{t('首页不同')} {section.different_first_page?'✓':'—'} · {t('奇偶页不同')} {section.different_odd_even_pages?'✓':'—'}</p><p>{t('页码')} · {section.page_number?.format??t('未注明')} · {section.page_number?.mode==='restart'?t('从 {start} 重新编号',{start:section.page_number.start??'—'}):t('延续或默认编号')}</p>{(['headers','footers'] as const).map(kind=><div key={kind}><strong>{t(kind==='headers'?'页眉':'页脚')}</strong><ul>{section[kind]?.map((part,i)=><li key={i}>{t({default:'默认',first:'首页',even:'偶数页'}[part.type]??part.type)} · {t(part.linked_to_previous?'链接前节':'本节定义')} · {part.text||t('无已记录文字')}{!!part.fields?.length&&<p>{t('域代码')}：{part.fields.join(' / ')}</p>}<Provenance source={part.source}/></li>)}</ul></div>)}<Provenance source={section.source}/></li>}
export default function SchoolTemplates(props:Props) {return <SchoolTemplatesPanel key={props.projectId} {...props}/>}
function SchoolTemplatesPanel({projectId,active,onChanged,navigation,onNavigate,registerLeaveGuard}:Props) {
 const {t}=useI18n();const visible=useDocumentVisible()
 const layered=!!navigation;const currentView=navigation?.view??'list'
 const [visited,setVisited]=useState(active)
 useEffect(()=>{if(active)setVisited(true)},[active])
 const go=(view:SchoolTemplateView,templateId='')=>onNavigate?.({view,templateId})
 const [profile,setProfile]=useState<Profile|null>(null);const [draft,setDraft]=useState(emptyProfile)
 const [items,setItems]=useState<Template[]>([]);const [files,setFiles]=useState<LibraryFile[]>([]);const [filePage,setFilePage]=useState(1);const [fileTotal,setFileTotal]=useState(0)
 const [templateFile,setTemplateFile]=useState('');const [supplements,setSupplements]=useState<string[]>([]);const [manuscripts,setManuscripts]=useState<string[]>([])
 const [previous,setPrevious]=useState('')
 const [name,setName]=useState('');const [supplementText,setSupplementText]=useState('');const [showUpload,setShowUpload]=useState(false)
 const [uploadVisited,setUploadVisited]=useState(false)
 useEffect(()=>{if(showUpload)setUploadVisited(true)},[showUpload])
 const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [refresh,setRefresh]=useState(0);const [blocked,setBlocked]=useState(false)
 const baseline=useRef<Profile|null>(null)
 const draftRef=useRef(draft);draftRef.current=draft
 const intakeBaseline=useRef('')
 const intakeSignature=JSON.stringify({templateFile,supplements,manuscripts,previous,name,supplementText})
 if(!intakeBaseline.current)intakeBaseline.current=intakeSignature
 const dirty=!!baseline.current&&Object.keys(fields).some(key=>draft[key as keyof typeof fields]!==baseline.current![key as keyof typeof fields])||intakeSignature!==intakeBaseline.current
 useDraftLeaveGuard(registerLeaveGuard,!blocked&&dirty,busy)
 const profileConflict=!!profile&&profile.revision!==draft.revision
 function adoptProfile(next:Profile){baseline.current=next;draftRef.current=next;setDraft(next)}
 function acceptProfile(next:Profile){
  if(baseline.current&&next.revision<baseline.current.revision)return
  const clean=!baseline.current||Object.keys(fields).every(key=>draftRef.current[key as keyof typeof fields]===baseline.current![key as keyof typeof fields])
  setProfile(next);if(clean)adoptProfile(next)
 }
 const controller=useRef(new AbortController());const alive=useRef(true);const operations=useRef(new Map<string,{body:string;key:string}>());const lock=useRef(false)
 const stop=useCallback(()=>{alive.current=false;controller.current.abort();setBlocked(true);setProfile(null);setDraft(emptyProfile);setItems([]);setFiles([]);setName('');setSupplementText('');setShowUpload(false);setTemplateFile('');setSupplements([]);setManuscripts([]);setPrevious('');operations.current.clear()},[])
 useEffect(()=>{alive.current=true;if(controller.current.signal.aborted)controller.current=new AbortController();const pending=controller.current;const unsubscribe=onApiSessionChanged(stop);return()=>{alive.current=false;pending.abort();unsubscribe()}},[stop])
 const base=`/api/v1/projects/${encodeURIComponent(projectId)}`
 async function request<T>(path:string,init?:RequestInit):Promise<T>{
  const local=new AbortController();const cancel=()=>local.abort();const parent=controller.current.signal;parent.addEventListener('abort',cancel,{once:true});const timeout=window.setTimeout(cancel,15000)
  try {
  const response=await apiFetch(`${base}/${path}`,{...init,signal:local.signal});const result=await response.json().catch(()=>null)
  if(!alive.current||controller.current.signal.aborted)throw new DOMException('Aborted','AbortError')
  if([401,403,404].includes(response.status)&& (response.status!==404||result?.detail?.code==='project_not_found')){stop();throw new DOMException('Unavailable','AbortError')}
  if(!response.ok)throw new Error(apiError(result,response.status===409?'资料或版本已变化，请刷新后核对再重试。':'学校模板请求失败，请重试。'))
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
  if(!active||blocked)return;let current=true
  void request<FilePage>(`files?page=${filePage}&page_size=50`).then(page=>{if(current&&alive.current){setFiles(old=>filePage===1?page.items:[...old.filter(file=>!page.items.some(item=>item.id===file.id)),...page.items]);setFileTotal(page.total)}}).catch(cause=>{if(current&&alive.current)setError(safeError(cause,'学校模板请求失败，请重试。'))})
  return()=>{current=false}
  // eslint-disable-next-line react-hooks/exhaustive-deps
 },[base,active,blocked,refresh,filePage])
 async function mutate(path:string,body:unknown,idempotent=false){const serialized=JSON.stringify(body);let headers:Record<string,string>={'Content-Type':'application/json'}
  if(idempotent){const old=operations.current.get(path);const operation=old?.body===serialized?old:{body:serialized,key:crypto.randomUUID()};operations.current.set(path,operation);headers={...headers,'Idempotency-Key':operation.key}}
  return request<unknown>(path,{method:'POST',headers,body:serialized})
 }
 async function run(action:()=>Promise<void>){if(lock.current||blocked)return;lock.current=true;setBusy(true);setError('');try{await action();if(alive.current){setRefresh(v=>v+1);onChanged?.()}}catch(cause){if(alive.current)setError(safeError(cause,'学校模板请求失败，请重试。'))}finally{lock.current=false;if(alive.current)setBusy(false)}}
 async function saveProfile(){if(!profile)return;if(profile.revision!==draft.revision)throw new Error('学校资料已在其他页面更新；草稿仍基于旧版本。请核对最新资料后重新填写。');const next=await request<Profile>('thesis-profile',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({...Object.fromEntries(Object.keys(fields).map(key=>[key,draft[key as keyof typeof fields].trim()])),expected_revision:draft.revision})});setProfile(next);adoptProfile(next)}
 async function create(){await saveProfile();await mutate('school-templates',{name:name.trim()||files.find(f=>f.id===templateFile)?.filename||'DOCX',school:draft.school.trim(),version_label:draft.applicable_version.trim(),template_file_id:templateFile,supplement_file_ids:supplements,manuscript_file_ids:manuscripts,supplement_text:supplementText,...(previous?{previous_version_id:previous}:{})},true);intakeBaseline.current=intakeSignature}
 if(!visited&&!active)return null
 return <section hidden={!active} className="school-templates project-form" aria-label={t('学校模板')}><header><h2>{t('学校模板')}</h2><p>{t('保存原始模板和新旧版本关系，确认后显式绑定。旧稿继续使用原模板，可在稿件页另存迁移版或上传修改稿。')}</p><button type="button" disabled={busy||blocked} onClick={()=>setRefresh(v=>v+1)}>{t('刷新学校模板')}</button></header>
 {error&&<p role="alert" className="error-panel">{t(error)}</p>}{blocked&&<p role="alert">{t('会话或项目访问已变化，请重新打开项目。')}</p>}
 {profileConflict&&!blocked&&<div className="warning-panel"><p role="alert">{t('学校资料已在其他页面更新；草稿仍基于旧版本。请核对最新资料后重新填写。')}</p><button type="button" disabled={busy} onClick={()=>{if(profile)adoptProfile(profile)}}>{t('使用最新学校资料')}</button></div>}
 {!blocked&&<>
 {layered&&<><nav className="school-view-nav" aria-label={t('学校模板视图')}>{(['list','profile','upload'] as const).map(view=><button key={view} type="button" aria-current={currentView===view?'page':undefined} onClick={()=>go(view)}>{t(viewLabels[view])}</button>)}</nav>
 {currentView==='list'&&<section aria-label={t('模板版本列表')}><div className="school-list-heading"><h3>{t('模板版本列表')}</h3><span className="muted">{t('共 {count} 个模板版本',{count:items.length})}</span></div>{items.length?<div className="school-template-list">{items.map(item=><article key={item.id}><div><strong>{item.name}</strong><p>{item.school} · {item.version_label||t('版本未注明')}</p><small>{t(statusLabels[item.task.status]??'状态未知')} · {t(item.confirmation?'已确认':'待确认')}{profile?.bound_confirmation_id===item.confirmation?.id&&<> · {t('当前绑定版本')}</>}</small></div><button type="button" aria-label={t('查看模板 {name}',{name:item.name})} onClick={()=>go('detail',item.id)}>{t('查看模板')}</button></article>)}</div>:<p className="muted">{t('还没有模板版本，请先填写学校资料并上传模板。')}</p>}</section>}
 {['detail','rules','confirm','binding'].includes(currentView)&&<><nav className="school-view-nav" aria-label={t('模板详情视图')}>{(['detail','rules','confirm','binding'] as const).map(view=><button key={view} type="button" aria-current={currentView===view?'page':undefined} onClick={()=>go(view,navigation.templateId)}>{t(viewLabels[view])}</button>)}</nav>{!items.some(item=>item.id===navigation.templateId)&&<p role="status">{t('模板版本尚未读取或已不可用，请返回列表核对。')}</p>}</>}
 </>}
 <form hidden={layered&&!['profile','upload'].includes(currentView)} onSubmit={event=>{event.preventDefault();void run(layered&&currentView==='profile'?saveProfile:create)}}><fieldset disabled={busy||!profile}><legend>{t(currentView==='upload'&&layered?'模板与来源材料':'适用信息')}</legend><div hidden={layered&&currentView!=='profile'}><p>{t('由上传者填写适用信息；未注明的年份或版本请如实记录，不以文件时间推断。')}</p><div className="project-fields">{Object.entries(fields).map(([key,label])=><label key={key}>{t(label)}<input required={key==='school'&&(!layered||currentView==='profile')} maxLength={key==='degree_type'||key==='education_level'?100:300} value={draft[key as keyof typeof fields]} onChange={event=>setDraft(old=>({...old,[key]:event.target.value}))}/></label>)}</div><button type="button" disabled={profileConflict} onClick={()=>void run(saveProfile)}>{t('保存学校资料')}</button></div>
 <div hidden={layered&&currentView!=='upload'}>{layered&&<p>{t('当前学校')}：{draft.school||t('未填写')} · <button type="button" onClick={()=>go('profile')}>{t('编辑适用信息')}</button></p>}<h3>{t('模板与来源材料')}</h3><p>{t('每项来源只能选择一次；补充规范和已有稿件各最多 10 项。')}</p><button type="button" className="button-primary" onClick={()=>setShowUpload(value=>!value)} aria-expanded={showUpload}>{t('上传学校论文模板')}</button><p>{t('上传后在下方选择已保留的原件；补充规范必须完成文件解析。原模板内说明是规则来源，示例正文不代表所有专业。')}</p>
 <label>{t('模板名称')}<input value={name} onChange={event=>setName(event.target.value)} maxLength={200}/></label>
 <label>{t('更新自模板版本（可选）')}<select value={previous} onChange={event=>setPrevious(event.target.value)}><option value="">{t('独立模板版本')}</option>{items.filter(item=>item.confirmation).map(item=><option key={item.id} value={item.id}>{item.name} · {item.version_label}</option>)}</select></label><p>{t('上传新版本保留原模板；绑定不会自动迁移历史稿。')}</p>
 <label>{t('模板 DOCX 原件')}<select required={!layered||currentView==='upload'} value={templateFile} onChange={event=>setTemplateFile(event.target.value)}><option value="">{t('请选择文件')}</option>{files.filter(f=>f.filename.toLowerCase().endsWith('.docx')).map(f=><option key={f.id} value={f.id}>{f.filename}</option>)}</select></label>
 <label>{t('补充规范 DOCX / PDF')}<select multiple value={supplements} onChange={event=>setSupplements(Array.from(event.target.selectedOptions,option=>option.value))}>{files.filter(f=>/\.(docx|pdf)$/i.test(f.filename)).map(f=><option key={f.id} value={f.id} disabled={f.parse_status!=='parsed'}>{f.filename}{f.parse_status!=='parsed'?` (${t('等待文件解析')})`:''}</option>)}</select></label>
 <label>{t('已有稿件')}<select multiple value={manuscripts} onChange={event=>setManuscripts(Array.from(event.target.selectedOptions,option=>option.value))}>{files.filter(f=>/\.(docx|pdf)$/i.test(f.filename)).map(f=><option key={f.id} value={f.id}>{f.filename}</option>)}</select></label>
 {files.length<fileTotal&&<button type="button" onClick={()=>setFilePage(page=>page+1)}>{t('读取更多原件')}</button>}
 <label>{t('补充规范文本')}<textarea rows={4} value={supplementText} onChange={event=>setSupplementText(event.target.value)} maxLength={20000}/></label><button className="button-primary" disabled={profileConflict||!templateFile||!draft.school.trim()||supplements.length>10||manuscripts.length>10||new Set([templateFile,...supplements,...manuscripts]).size!==1+supplements.length+manuscripts.length} type="submit">{t('提交模板解析')}</button></div></fieldset></form>
 {(showUpload||uploadVisited)&&<div hidden={!showUpload||layered&&currentView!=='upload'}><BatchUpload projectId={projectId} active={active&&showUpload&&(!layered||currentView==='upload')} registerLeaveGuard={registerLeaveGuard} onUnavailable={stop} onChanged={()=>{setFilePage(1);setRefresh(v=>v+1)}}/></div>}
 {items.map(item=><TemplateReview hidden={layered&&(!['detail','rules','confirm','binding'].includes(currentView)||navigation.templateId!==item.id)} view={layered?currentView:undefined} registerLeaveGuard={registerLeaveGuard} key={`${item.id}:${item.analysis_sha256??'pending'}`} item={item} previousLabel={items.find(old=>old.id===item.previous_version_id)?.name} onUpdate={()=>{setPrevious(item.id);setName(item.name+' 更新版');setTemplateFile('');setShowUpload(true);go('upload')}} projectId={projectId} bound={profile?.bound_confirmation_id===item.confirmation?.id} busy={busy} onConfirm={body=>run(async()=>{await mutate(`school-templates/${encodeURIComponent(item.id)}/confirm`,body,true)})} onBind={()=>run(async()=>{const next=await mutate('thesis-template-binding',{confirmation_id:item.confirmation?.id,expected_revision:profile?.revision}) as Profile;acceptProfile(next)})} onRetry={()=>run(async()=>{await mutate(`school-templates/${encodeURIComponent(item.id)}/retry`,{},true)})}/>)}
 </>}</section>
}
function TemplateReview({item,previousLabel,onUpdate,projectId,bound,busy,onConfirm,onBind,onRetry,hidden,view,registerLeaveGuard}:{hidden?:boolean;view?:SchoolTemplateView;registerLeaveGuard?:RegisterLeaveGuard;item:Template;previousLabel?:string;onUpdate:()=>void;projectId:string;bound:boolean;busy:boolean;onConfirm:(body:unknown)=>Promise<void>;onBind:()=>Promise<void>;onRetry:()=>Promise<void>}){
 const {t}=useI18n();const analysis=item.analysis;const [decisions,setDecisions]=useState<Record<string,string>>(()=>Object.fromEntries((item.confirmation?.decisions??[]).map(decision=>[decision.conflict_id,decision.option_id])));const [chapters,setChapters]=useState<Chapter[]>(()=>item.confirmation?.chapters??analysis?.chapters??[])
 const [textDecisions,setTextDecisions]=useState<Record<string,string>>(()=>Object.fromEntries((item.confirmation?.text_decisions??[]).map(decision=>[decision.id,decision.choice])))
 const [reviewBaseline]=useState(()=>JSON.stringify({decisions,chapters,textDecisions}))
 useDraftLeaveGuard(registerLeaveGuard,!item.confirmation&&reviewBaseline!==JSON.stringify({decisions,chapters,textDecisions}),false)
 const textOptions=item.text_decision_options??[]
 const unresolvedText=textOptions.some(option=>!option.choices.includes(textDecisions[option.id] as 'text'|'attributes'))
 const unresolved=analysis?.conflicts.some(conflict=>!conflict.options.some(option=>option.id===decisions[conflict.id]))
 return <article hidden={hidden} className="template-version" id={`template-${item.id}`}><header><h3>{item.name}</h3><p>{item.school} · {item.version_label||t('版本未注明')}</p><p role="status">{t(statusLabels[item.task.status]??'状态未知')}{bound&&<> · <strong>{t('当前绑定版本')}</strong></>}</p>{item.previous_version_id&&<p>{t('原模板版本')}：{previousLabel??item.previous_version_id}</p>}{item.confirmation&&<button type="button" disabled={busy} onClick={onUpdate}>{t('上传此模板的新版本')}</button>}</header>
 <div hidden={!!view&&view!=='detail'}><h4>{t('保留的来源原件')}</h4><ul>{(item.sources??[]).map(source=><li key={source.id}>{t({template:'模板原件',supplement:'补充规范',manuscript:'已有稿件'}[source.role]??'来源文件')} · {source.filename} <ProjectDownloadLink href={`/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(source.file_id)}/download`} filename={source.filename}>{t('下载原文件')}</ProjectDownloadLink></li>)}</ul>
 {item.supplement_text&&<details><summary>{t('补充规范文本')}</summary><p className="template-text">{item.supplement_text}</p></details>}
 {item.task.status==='failed'&&<><p role="alert">{t('模板解析失败，请保留原件后重试。')}</p><button type="button" disabled={busy} onClick={()=>void onRetry()}>{t('重试模板解析')}</button></>}</div>
 {analysis&&<><div hidden={!!view&&view!=='rules'}><details open={view==='rules'}><summary>{t('模板规则（{count} 项）',{count:(item.confirmation?.rules??analysis.rules??[]).length})}</summary><FactList title="模板规则" items={item.confirmation?.rules??analysis.rules??[]}/></details><details><summary>{t('分节与页眉页脚实际属性')}</summary><ul>{analysis.sections?.map((section,index)=><SectionFacts key={section.id??index} section={section} index={index}/>)}</ul></details>
 <details><summary>{t('内嵌说明与引用（{count} 项）',{count:(analysis.notes??[]).length})}</summary><FactList title="内嵌说明与引用" items={analysis.notes??[]}/></details><FactList title="缺失信息" items={item.confirmation?.missing??analysis.missing??[]}/><FactList title="解析限制" items={item.confirmation?.unsupported??analysis.unsupported??[]}/><FactList title="身份与签名字段" items={analysis.identity_fields??[]}/><p>{t('姓名、学号及签名等必填字段须由本人核对；系统不会代签或推断身份。')}</p></div>
 <fieldset hidden={!!view&&view!=='confirm'} disabled={busy||!!item.confirmation}><legend>{t('章节配置')}</legend><p>{t('核对并保存本项目适用章节；模板章节可能只是示例。')}</p>{chapters.map((chapter,index)=><div className="template-chapter" key={chapter.id}><label>{t('章节标题 {index}',{index:index+1})}<input maxLength={500} value={chapter.title} onChange={event=>setChapters(current=>current.map((entry,i)=>i===index?{...entry,title:event.target.value}:entry))}/></label><label>{t('标题级别 {index}',{index:index+1})}<input type="number" min="1" max="9" value={chapter.level} onChange={event=>setChapters(current=>current.map((entry,i)=>i===index?{...entry,level:Number(event.target.value)}:entry))}/></label><button type="button" onClick={()=>setChapters(current=>current.filter((_,i)=>i!==index))}>{t('移除此章节')}</button><Provenance source={chapter.source}/></div>)}<button type="button" onClick={()=>setChapters(current=>[...current,{id:crypto.randomUUID(),title:'',level:1}])}>{t('添加章节')}</button>
 <h4>{t('规则冲突')}</h4>{analysis.conflicts?.map(conflict=><div key={conflict.id}><label>{conflict.label??t('规则冲突')}<select value={decisions[conflict.id]??''} onChange={event=>setDecisions(old=>({...old,[conflict.id]:event.target.value}))}><option value="">{t('请选择采用的来源值')}</option>{conflict.options.map(option=><option key={option.id} value={option.id}>{readable(option.value)} · {option.source?.text??option.source?.part??''}</option>)}</select></label>{conflict.options.map(option=><Provenance key={option.id} source={option.source}/>)}</div>)}
 {textOptions.length>0&&(!item.confirmation||!!item.confirmation.text_decisions?.length)&&<><h4>{t('文字规范采用方式')}</h4><p>{t('原选择仅供参考；新版本须明确选择本次采用的来源。')}</p>{textOptions.map(option=><div key={option.id}><label>{option.label}<select value={textDecisions[option.id]??''} onChange={event=>setTextDecisions(old=>({...old,[option.id]:event.target.value}))}><option value="">{t('请选择采用的来源值')}</option>{option.choices.includes('text')&&<option value="text">{t('采用文字说明')} · {option.text_value}</option>}<option value="attributes">{t('采用原样式属性')}</option></select></label><p>{option.source_text??t('原文字说明在此版本中缺失。')}</p>{option.changed&&<p className="warning-panel">{t('来源或样式已变化，请重新核对。')}</p>}{option.suggested_choice&&<p>{t('先前选择可沿用')}：{t(option.suggested_choice==='text'?'采用文字说明':'采用原样式属性')}</p>}<details><summary>{t('查看原样式属性')}</summary><p>{readable(option.attribute_value)}</p></details></div>)}</>}
 {unresolved&&<p role="status">{t('请先逐项解决规则冲突。')}</p>}
 <button type="button" className="button-primary" disabled={!!unresolved||unresolvedText||!chapters.length||chapters.length>300||!item.analysis_sha256||chapters.some(chapter=>!chapter.title.trim()||!Number.isInteger(chapter.level)||chapter.level<1||chapter.level>9)} onClick={()=>void onConfirm({analysis_sha256:item.analysis_sha256,decisions:analysis.conflicts.map(conflict=>({conflict_id:conflict.id,option_id:decisions[conflict.id]})),chapters:chapters.map(({id,title,level})=>({id,title:title.trim(),level})),...(textOptions.length?{text_decisions:textOptions.map(option=>({id:option.id,choice:textDecisions[option.id],source_sha256:option.source_sha256}))}:{})})}>{t('确认模板规则')}</button></fieldset></>}
 {view==='binding'&&!item.confirmation&&<p>{t('请先完成规则确认，再绑定此模板版本。')}</p>}
 {item.confirmation&&<div hidden={!!view&&view!=='binding'} className="template-binding"><p>{t('规则已确认；绑定后才用于此项目，原解析与原件继续保留。')}</p>{!bound&&<button type="button" className="button-primary" disabled={busy} onClick={()=>void onBind()}>{t('绑定此确认版本')}</button>}</div>}
 </article>
}
