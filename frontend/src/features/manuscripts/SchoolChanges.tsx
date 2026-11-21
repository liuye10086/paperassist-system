import {systemCheckText} from '../../shared/i18n/systemChecks'
import {useManuscriptDraft} from './useManuscriptDraft'
import {useCallback,useEffect,useRef,useState} from 'react'
import {apiFetch,onApiSessionChanged} from '../../shared/api/client'
import {apiError,safeError,useI18n} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import VersionLabel from '../../shared/VersionLabel'
import BatchUpload from '../files/BatchUpload'
import type {FilePage,LibraryFile} from '../files/fileLibraryApi'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import {manuscriptBase,validManuscript,type Manuscript,type ManuscriptVersion} from './manuscriptTypes'
import {isChangeList,isSchoolChange,type Mapping,type SchoolChange} from './schoolChangeTypes'

type TemplateChoice={id:string;name:string;version_label:string;confirmation:{id:string}|null}
const templateLabel=(item:TemplateChoice)=>[item.name,item.version_label].filter(Boolean).join(' · ')
type ParsedVersion={id:string;version:number}
// `templateOnly` is the customer thesis page: template migration only, customer wording (B04 task 9).
// `versions` give VersionLabel its saved times; `initialTarget` is the confirmed template to preselect.
type Props={projectId:string;manuscriptId:string;version:ManuscriptVersion;currentRevision:number;active:boolean;templateOnly?:boolean;versions?:ManuscriptVersion[];initialTarget?:string;onAdopted:(value:Manuscript)=>void}
export default function SchoolChanges(props:Props){return <ChangePanel key={props.version.id} {...props}/>}
function ChangePanel({projectId,manuscriptId,version,currentRevision,active,templateOnly=false,versions=[],initialTarget,onAdopted}:Props){
 const {t}=useI18n();const visible=useDocumentVisible()
 const base=`${manuscriptBase(projectId)}/${encodeURIComponent(manuscriptId)}`
 const project=`/api/v1/projects/${encodeURIComponent(projectId)}`
 const [templates,setTemplates]=useState<TemplateChoice[]>([]),[target,setTarget]=useState('')
 const currentConfirmation=version.snapshot.thesis_context?.confirmation_id
 const [files,setFiles]=useState<LibraryFile[]>([]),[total,setTotal]=useState(0),[filePage,setFilePage]=useState(1)
 const [fileId,setFileId]=useState(''),[parseId,setParseId]=useState(''),[parses,setParses]=useState<ParsedVersion[]>([]),[exportId,setExportId]=useState('')
 const [upload,setUpload]=useState(false),[items,setItems]=useState<SchoolChange[]>([]),[selected,setSelected]=useState<SchoolChange|null>(null)
 const [mappings,setMappings]=useState<Mapping[]>([]),[preview,setPreview]=useState<SchoolChange|null>(null)
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[blocked,setBlocked]=useState(false),[refresh,setRefresh]=useState(0)
 // A target preselected from the change preview is not the customer's edit; choosing another one is.
 const [preset,setPreset]=useState(''),presetUsed=useRef(false),registerButton=useRef<HTMLButtonElement>(null)
 useManuscriptDraft(!!target&&target!==preset||!!fileId||!!exportId||JSON.stringify(mappings)!==JSON.stringify(selected?.mappings??[])||!!error,busy)
 const lifetime=useRef(new AbortController()),alive=useRef(true),lock=useRef(false)
 const attempts=useRef(new Map<string,{body:string;key:string}>())
 const clear=useCallback(()=>{
  alive.current=false;lifetime.current.abort();setBlocked(true);setTemplates([]);setFiles([]);setParses([]);setItems([]);setSelected(null);setPreview(null);setMappings([]);setFileId('');setTarget('');setUpload(false);attempts.current.clear()
 },[])
 useEffect(()=>{alive.current=true;if(lifetime.current.signal.aborted)lifetime.current=new AbortController();const controller=lifetime.current;const unsub=onApiSessionChanged(clear);return()=>{alive.current=false;controller.abort();unsub()}},[clear])
 const request=useCallback(async<T,>(url:string,init?:RequestInit):Promise<T>=>{
  const controller=new AbortController(),parent=lifetime.current.signal
  const abort=()=>controller.abort();parent.addEventListener('abort',abort,{once:true});const timeout=window.setTimeout(abort,15000)
  try{
   const response=await apiFetch(url,{...init,signal:controller.signal});const value=await response.json().catch(()=>null)
   if(!alive.current||parent.aborted)throw new DOMException('Aborted','AbortError')
   if(response.status===401||response.status===403||(response.status===404&&value?.detail?.code==='project_not_found')){clear();throw new DOMException('Unavailable','AbortError')}
   if(!response.ok)throw new Error(apiError(value,'学校版本请求失败，请刷新后重试。'))
   return value as T
  }finally{window.clearTimeout(timeout);parent.removeEventListener('abort',abort)}
 },[clear])
 useEffect(()=>{
  if(!active||!visible||blocked)return;let current=true
  void Promise.all([request<unknown>(base+'/school-changes'),request<{items:TemplateChoice[]}>(project+'/school-templates')]).then(([changes,list])=>{
   if(!current||!alive.current)return
   if(!isChangeList(changes)||!Array.isArray(list.items))throw new Error('学校版本请求失败，请刷新后重试。')
   const confirmed=list.items.filter(item=>item.confirmation)
   setItems(templateOnly?changes.items.filter(item=>item.kind==='template_migration'):changes.items);setTemplates(confirmed);setError('')
   if(initialTarget&&!presetUsed.current){presetUsed.current=true;if(initialTarget!==currentConfirmation&&confirmed.some(item=>item.confirmation!.id===initialTarget)){setTarget(initialTarget);setPreset(initialTarget)}}
  }).catch(cause=>{if(current&&alive.current)setError(safeError(cause,'学校版本请求失败，请刷新后重试。'))})
  return()=>{current=false}
 },[base,project,request,active,visible,blocked,refresh,templateOnly,currentConfirmation,initialTarget])
 useEffect(()=>{if(preset)registerButton.current?.focus()},[preset])
 useEffect(()=>{
  if(templateOnly||!active||!visible||blocked)return;let current=true
  void request<FilePage>(`${project}/files?page=${filePage}&page_size=50`).then(page=>{
   if(!current||!alive.current)return
   setFiles(old=>filePage===1?page.items:[...old.filter(f=>!page.items.some(n=>n.id===f.id)),...page.items]);setTotal(page.total)
  }).catch(cause=>{if(current&&alive.current)setError(safeError(cause,'学校版本请求失败，请刷新后重试。'))})
  return()=>{current=false}
 },[project,request,active,visible,blocked,refresh,filePage,templateOnly])
 useEffect(()=>{
  if(!fileId||!active||blocked)return;let current=true
  void request<{items:ParsedVersion[]}>(`${project}/files/${encodeURIComponent(fileId)}/document-versions?page=1`).then(page=>{
   if(current&&alive.current){setParses(page.items);setParseId(old=>page.items.some(p=>p.id===old)?old:page.items[0]?.id??'')}
  }).catch(cause=>{if(current&&alive.current)setError(safeError(cause,'学校版本请求失败，请刷新后重试。'))})
  return()=>{current=false}
 },[fileId,project,request,active,blocked,refresh])
 async function mutate<T>(url:string,body:unknown,idempotent=false):Promise<T>{
  const serialized=JSON.stringify(body);const headers:Record<string,string>={'Content-Type':'application/json'}
  if(idempotent){const old=attempts.current.get(url);const attempt=old?.body===serialized?old:{body:serialized,key:crypto.randomUUID()};attempts.current.set(url,attempt);headers['Idempotency-Key']=attempt.key}
  return request<T>(url,{method:'POST',headers,body:serialized})
 }
 async function run(action:()=>Promise<void>){
  if(lock.current||blocked)return;lock.current=true;setBusy(true);setError('')
  try{await action()}catch(cause){if(alive.current)setError(safeError(cause,'学校版本请求失败，请刷新后重试。'))}
  finally{lock.current=false;if(alive.current)setBusy(false)}
 }
 function show(value:unknown){
  if(!isSchoolChange(value)||value.manuscript_id!==manuscriptId)throw new Error('学校版本请求失败，请刷新后重试。')
  setSelected(value);setMappings(value.mappings);setPreview(value)
  setItems(old=>[value,...old.filter(item=>item.id!==value.id)])
 }
 async function register(kind:SchoolChange['kind']){
  const body=kind==='template_migration'?{kind,target_confirmation_id:target}:{kind,file_id:fileId,document_version_id:parseId,...(exportId?{base_export_id:exportId}:{})}
  show(await mutate(`${base}/versions/${version.revision}/school-changes`,body,true))
 }
 async function inspect(){if(selected)show(await mutate(`${base}/school-changes/${encodeURIComponent(selected.id)}/preview`,{mappings}))}
 async function adopt(){
  if(!selected||!preview?.can_adopt)return
  const result=await mutate<unknown>(`${base}/school-changes/${encodeURIComponent(selected.id)}/adopt`,{mappings,expected_revision:currentRevision,preview_sha256:preview.preview_sha256},true)
  if(!validManuscript(result,projectId))throw new Error('学校版本请求失败，请刷新后重试。')
  onAdopted(result);setRefresh(n=>n+1)
 }
 const title=templateOnly?'模板迁移':'学校版本与回传稿'
 function templateName(confirmation:string,fallback:string){
  const item=templates.find(template=>template.confirmation?.id===confirmation)
  return item?.name?templateLabel(item):t(fallback)
 }
 const versionLabel=(revision:number)=><VersionLabel revision={revision} savedAt={[version,...versions].find(v=>v.revision===revision)?.created_at??''}/>
 return <section hidden={!active} className="manuscript-panel school-changes" aria-label={t(title)}>
  <header><h3>{t(title)}</h3>{templateOnly?<p>{versionLabel(version.revision)} · {t('迁移后另存为新的一版，原稿保持不变。')}</p>:<p>{t('基于固定版本 {revision}；另存新版本，保留原稿与原导出。',{revision:version.revision})}</p>}<button type="button" disabled={busy||blocked} onClick={()=>setRefresh(n=>n+1)}>{t(templateOnly?'刷新':'刷新版本输入')}</button></header>
  {error&&<p role="alert" className="error-panel">{t(error)}</p>}
  {blocked?<p role="alert">{t('会话或项目访问已变化，请重新打开项目。')}</p>:<>
   <fieldset disabled={busy}><legend>{t('按新模板另存版本')}</legend><p>{templateOnly?t('已下载的 Word 保持原样；第 {N} 版要按新模板导出，需要先把稿件迁移到新模板。',{N:version.revision}):t('新绑定仅影响新建稿；历史稿继续使用原模板。')}</p>
    <label>{t(templateOnly?'选择新模板':'迁移目标模板')}<select value={target} onChange={e=>setTarget(e.target.value)}><option value="">{t(templateOnly?'请选择要改用的学校模板':'请选择已确认模板')}</option>{templates.filter(item=>item.confirmation!.id!==currentConfirmation).map(item=><option key={item.id} value={item.confirmation!.id}>{templateLabel(item)}</option>)}</select></label>
    <button ref={registerButton} type="button" disabled={!target} onClick={()=>void run(()=>register('template_migration'))}>{t(templateOnly?'开始迁移':'登记模板迁移')}</button>
   </fieldset>
   {!templateOnly&&<><fieldset disabled={busy}><legend>{t('上传并采用修改稿')}</legend><p>{t('回传文件先作为新输入保留；数值、图表和引用变化仍须核实。')}</p>
    <button type="button" onClick={()=>setUpload(v=>!v)} aria-expanded={upload}>{t('上传修改后的 Word')}</button>
    <label>{t('回传 DOCX 原件')}<select value={fileId} onChange={e=>{setFileId(e.target.value);setParses([]);setParseId('')}}><option value="">{t('请选择文件')}</option>{files.filter(f=>f.file_type==='docx'||f.filename.toLowerCase().endsWith('.docx')).map(f=><option key={f.id} value={f.id} disabled={f.parse_status!=='parsed'}>{f.filename}{f.parse_status!=='parsed'?` · ${t('等待文件解析')}`:''}</option>)}</select></label>
    {files.length<total&&<button type="button" onClick={()=>setFilePage(n=>n+1)}>{t('读取更多回传原件')}</button>}
    <label>{t('固定解析版本')}<select value={parseId} onChange={e=>setParseId(e.target.value)}><option value="">{t('请选择解析版本')}</option>{parses.map(p=><option key={p.id} value={p.id}>{t('解析版本 {revision}',{revision:p.version})}</option>)}</select></label>
    <label>{t('下载来源 Word（可选）')}<select value={exportId} onChange={e=>setExportId(e.target.value)}><option value="">{t('由固定父稿核对')}</option>{version.exports.filter(e=>e.status==='succeeded').map(e=><option key={e.id} value={e.id}>{e.filename??e.id}</option>)}</select></label>
    <button type="button" disabled={!fileId||!parseId} onClick={()=>void run(()=>register('docx_return'))}>{t('登记回传稿')}</button>
   </fieldset>
   {upload&&<BatchUpload projectId={projectId} active={active} onUnavailable={clear} onChanged={()=>{setFilePage(1);setRefresh(n=>n+1)}}/>}</>}
   {selected&&<section className="school-change-preview" aria-label={t('匹配与重要差异')}>
    <h4>{templateOnly?<>{t('模板迁移')} · {versionLabel(selected.base_revision)}</>:<>{t(selected.kind==='template_migration'?'模板迁移输入':'用户回传输入')} · {t('父版本 {revision}',{revision:selected.base_revision})}</>}</h4>
    {selected.original_download_url&&<ProjectDownloadLink href={selected.original_download_url} filename={selected.source.filename??'回传稿.docx'}>{t('下载回传原件')}</ProjectDownloadLink>}
    <p>{t(templateOnly?'请为每一章选好在新模板中的位置。没选的内容不会被删掉，但要全部选好才能保存。':'每个有内容的输入章节都须对应目标章节；未分配内容不会静默丢弃。')}</p>
    <fieldset disabled={busy||selected.adopted_revision!==null}><legend>{t('章节匹配')}</legend>{selected.input_sections.map(section=><div key={section.id}>
     <label>{t(templateOnly?'“{title}”放到新模板的哪一章':'{title} · 对应章节',{title:section.title})}<select value={mappings.find(m=>m.input_section_id===section.id)?.chapter_id??''} onChange={e=>{setMappings(old=>[...old.filter(m=>m.input_section_id!==section.id),...(e.target.value?[{input_section_id:section.id,chapter_id:e.target.value}]:[])]);setPreview(null)}}><option value="">{t('未分配')}</option>{selected.target_chapters.map(c=><option key={c.id} value={c.id}>{c.title}</option>)}</select></label>
     <small>{t({bookmark:templateOnly?'按原文结构建议':'按原书签建议',title:'按明确标题建议',none:'尚无匹配建议',ambiguous:'匹配有歧义，请指定'}[section.match_method])}</small>
     {templateOnly?section.paragraphs.map((text,i)=><p className="template-text" key={i}>{text}</p>):
      <details><summary>{t('查看输入正文')}</summary>{section.paragraphs.map((text,i)=><p className="template-text" key={i}>{text}</p>)}</details>}
    </div>)}<button type="button" onClick={()=>void run(inspect)}>{t(templateOnly?'查看迁移后的变化':'预览匹配与差异')}</button></fieldset>
    {preview?<><h4>{t('重要差异与检查')}</h4>{preview.differences.length?preview.differences.map((d,i)=>{
     if(templateOnly&&d.kind==='template_changed'&&d.location==='school')return <article key={i}>
      <strong>{t('学校模板变更')}</strong>
      <p>{t('迁移前：{value}',{value:templateName(d.before,'原稿采用的学校模板')})}</p>
      <p>{t('迁移后：{value}',{value:templateName(d.after,'此次迁移采用的学校模板')})}</p>
     </article>
     const values=<><p>{t('原内容：{value}',{value:d.before||'—'})}</p><p>{t(templateOnly?'迁移后：{value}':'新输入：{value}',{value:d.after||'—'})}</p></>
     return <article key={i}><strong>{(systemCheckText(d.message)||t('检查说明不可用，请核对原始记录。'))}</strong>
      {templateOnly?values:<details><summary>{t('查看变更内容')}</summary>{values}</details>}
     </article>
    }):<p>{t('未发现需要列出的重要差异。')}</p>}{preview.issues.map((i,n)=><p key={n} className={i.severity==='error'?'error-panel':'warning-panel'}>{(systemCheckText(i.message)||t('检查说明不可用，请核对原始记录。'))}</p>)}</>:<p role="status">{t(templateOnly?'章节位置已修改，请先重新查看迁移后的变化。':'章节映射已更改，请先重新预览。')}</p>}
    {selected.adopted_revision!==null?<p>{templateOnly?<>{t('已另存为')} {versionLabel(selected.adopted_revision)}</>:t('已另存为版本 {revision}',{revision:selected.adopted_revision})}</p>:<button type="button" className="button-primary" disabled={busy||!preview?.can_adopt} onClick={()=>void run(adopt)}>{t(templateOnly?'确认并保存为新的一版':'确认匹配并另存版本')}</button>}
   </section>}
   <h4>{t(templateOnly?'迁移记录':'保留的版本输入')}</h4>{!items.length&&<p>{t(templateOnly?'尚无模板迁移记录。':'尚无模板迁移或回传输入。')}</p>}{items.map(item=><article key={item.id} className="manuscript-version">{templateOnly?<span>{t('模板迁移')} · {versionLabel(item.base_revision)}{item.adopted_revision!==null&&<> · {t('已另存为')} {versionLabel(item.adopted_revision)}</>}</span>:<span>{t(item.kind==='template_migration'?'模板迁移输入':'用户回传输入')} · {item.source.filename??t('学校模板')} · {t('父版本 {revision}',{revision:item.base_revision})}{item.adopted_revision!==null&&` · ${t('已另存为版本 {revision}',{revision:item.adopted_revision})}`}</span>}<button type="button" disabled={busy} onClick={()=>void run(async()=>show(await request(`${base}/school-changes/${encodeURIComponent(item.id)}`)))}>{t('查看此输入')}</button></article>)}
  </>}
 </section>
}

export function SchoolVersionOrigin({version,versions}:{version:ManuscriptVersion;versions:ManuscriptVersion[]}){
 const {t}=useI18n()
 const snapshot=version.snapshot,change=snapshot.school_change_provenance
 const written=version.parent_version_id&&snapshot.writing_provenance?.base_version_id===version.parent_version_id
 const label=written?'写作发布':snapshot.user_return_provenance?'用户回传':change?.kind==='template_migration'?'模板迁移':change?.kind==='docx_return'?'用户回传':snapshot.review_provenance?'检查修改':snapshot.writing_provenance?'写作发布':'系统生成'
 const parent=versions.find(v=>v.id===version.parent_version_id)
 return <small>{t(label)}{parent&&` · ${t('父版本 {revision}',{revision:parent.revision})}`}</small>
}
export function SchoolOpinionHandoff({version,projectId,manuscriptId}:{version:ManuscriptVersion;projectId?:string;manuscriptId?:string}){
 const {t}=useI18n()
 return <aside className="manuscript-panel"><h4>{t('意见修改')}</h4><p>{t('已选固定版本 {revision}；创建意见轮次后不会自动切换到最新稿。',{revision:version.revision})}</p>{version.status==='published'&&projectId&&manuscriptId?<a href={`#project=${encodeURIComponent(projectId)}&section=reviews&reviewManuscript=${encodeURIComponent(manuscriptId)}&reviewRevision=${version.revision}`}>{t('以此版本处理意见')}</a>:<p>{t('请先选择已发布的固定稿件版本。')}</p>}</aside>
}
