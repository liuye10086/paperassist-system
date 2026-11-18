import LanguageItemLocation from './LanguageItemLocation'
import {unlocatedEmptyImage,type ReviewFigure} from './languageImageLocation'
import ReadableDetails from '../../shared/components/ReadableDetails'
import SchoolExportPanel from './SchoolExportPanel'
import type {SchoolExportOptions} from './schoolExportTypes'
import {protocolLabel,inventoryKinds,inventoryScopes,exceptionKinds} from '../../shared/i18n/protocolLabels'
import {useManuscriptDraft} from './useManuscriptDraft'
import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {useResearchRead} from '../research-results/api'
import {manuscriptBase,validManuscript,type Manuscript} from './manuscriptTypes'
import {codepointRange,listOf,validLanguageContext,validLanguageArtifact,validFigureVersion,type ScienceReview,type LanguageContext,type LanguageArtifact,type LanguagePreparation,type LanguageException,type FigureVersion,type InventoryItem} from './writingLiveTypes'
import {useWritingOperation} from './useWritingOperation'
import ManuscriptPreview from './ManuscriptPreview'
import FigureLanguagePanel from './FigureLanguagePanel'
export type ItemDecision={decision:''|'target_language'|'no_text'|'provided_literal';reason:string;exceptions:LanguageException[]}
type SavedLanguageReview={id:string;created_at:string}

function preservesReference(item:InventoryItem,school:boolean){
 return item.preserve_reference===true||school&&item.kind==='export_text'&&item.scope==='reference_metadata'
}

function plannedDecision(item:InventoryItem,school:boolean):ItemDecision['decision']{
 if(item.protected_identity===true||preservesReference(item,school))return 'provided_literal'
 if(item.kind!=='image')return 'target_language'
 if(item.language_known!==true)return ''
 return item.no_text===true?'no_text':'target_language'
}

export function LanguageItem({item,value,onChange,index,figures,inventory,customerSci=false,readable=false,school=false}:{customerSci?:boolean;readable?:boolean;school?:boolean;figures?:ReviewFigure[];inventory?:InventoryItem[];index?:number;item:InventoryItem;value:ItemDecision;onChange:(v:ItemDecision)=>void}){
 const {t}=useI18n(),[selection,setSelection]=useState({start:0,end:0}),[kind,setKind]=useState<LanguageException['kind']>('proper_name'),[reason,setReason]=useState('')
 const kindLabel=item.kind==='export_text'?t(customerSci?'Word 导出文字':'学校导出文本'):protocolLabel(inventoryKinds,item.kind,'未知类型')
 const ExceptionGroup=readable?'fieldset':'details',ExceptionTitle=readable?'legend':'summary'
 const requiredDecision=plannedDecision(item,school)
 const unknownImage=readable&&requiredDecision===''
 const imageItem=readable&&item.kind==='image'
 return <fieldset disabled={unknownImage||unlocatedEmptyImage(item,figures)}>
  <legend>{t('核对项目')} {index??''} · {kindLabel}</legend>
  <LanguageItemLocation item={item} figures={figures} inventory={inventory} customerView={readable}/>
  {unknownImage?<p role="status">{t('图中文字待核对。请创建并选择图语言版本，然后重新预览。')}</p>:<>
   {!imageItem&&<p>{protocolLabel(inventoryScopes,item.scope,'未知范围')}</p>}
   {typeof item.target_language==='string'&&<p>{t(item.target_language==='en'?'英文':'中文')}</p>}
   {!imageItem&&<label>{t('清单精确文字（可选择局部范围）')}
    <textarea readOnly value={item.text} onSelect={e=>setSelection(codepointRange(item.text,e.currentTarget.selectionStart,e.currentTarget.selectionEnd))}/>
   </label>}
   <label>{t('此项语言决定')}<select value={value.decision} onChange={e=>onChange({...value,decision:e.target.value as ItemDecision['decision']})}>
    <option value="">{t('尚未判断')}</option>
    {requiredDecision==='provided_literal'?<option value="provided_literal">{t(preservesReference(item,school)?'已核对参考文献原文':'已逐项核对用户提供的身份原文')}</option>:<>
     {(!readable||requiredDecision==='target_language')&&<option value="target_language">{t('目标语言文字已逐项核对')}</option>}
     {(!readable||requiredDecision==='no_text')&&<option value="no_text">{t('已明确检查此图没有文字')}</option>}
    </>}
   </select></label>
   <label>{t('此项语言审核理由')}<textarea value={value.reason} onChange={e=>onChange({...value,reason:e.target.value})}/></label>
   {requiredDecision!=='provided_literal'&&(!readable||selection.end>selection.start)&&<ExceptionGroup>
    <ExceptionTitle>{t('仅对所选短片段添加局部例外')}</ExceptionTitle>
    {readable?<blockquote>{Array.from(item.text).slice(selection.start,selection.end).join('')}</blockquote>:<p>{t('Unicode 码点区间')} [{selection.start},{selection.end}) · {Array.from(item.text).slice(selection.start,selection.end).join('')}</p>}
    <label>{t('局部例外类型')}<select value={kind} onChange={e=>setKind(e.target.value as LanguageException['kind'])}>
     <option value="proper_name">{t('专名')}</option><option value="unit">{t('单位')}</option><option value="reference_metadata">{t('真实参考文献元数据')}</option>
    </select></label>
    <label>{t('局部例外理由')}<input value={reason} onChange={e=>setReason(e.target.value)}/></label>
    <button type="button" disabled={selection.end<=selection.start||!reason.trim()} onClick={()=>{onChange({...value,exceptions:[...value.exceptions,{...selection,kind,reason}]});setReason('')}}>{t('添加此局部例外')}</button>
    <p>{t('正文、图注和分面说明不可整项豁免；标签类型和范围由服务端验证。')}</p>
    {value.exceptions.map((x,i)=><p key={i}>[{x.start},{x.end}) {protocolLabel(exceptionKinds,x.kind,'未知类型')} · {x.reason}
     <button type="button" onClick={()=>onChange({...value,exceptions:value.exceptions.filter((_,j)=>j!==i)})}>{t('移除例外')}</button>
    </p>)}
   </ExceptionGroup>}
  </>}
 </fieldset>
}
export default function WritingLanguageReview({projectId,manuscriptId,baseRevision,review,onPublished,customerSci=false,customerThesis=false}:{customerSci?:boolean;customerThesis?:boolean;projectId:string;manuscriptId:string;baseRevision:number;review:ScienceReview;onPublished:(v:Manuscript)=>void}){
 const readable=(customerSci||customerThesis)&&!!review.candidate.paper_plan
 const school=!!review.candidate.thesis_context
 const initialSchool:SchoolExportOptions={manual_fields:{author:'',student_id:'',department:'',major:'',class_name:'',supervisor:'',submission_date:''},manual_chapters:[],english_title:'',keywords:[],include_toc:true,toc_depth:3,field_values:{}}
 const {t,locale}=useI18n(),op=useWritingOperation(),base=`${manuscriptBase(projectId)}/${encodeURIComponent(manuscriptId)}/writing-requests/${encodeURIComponent(review.request_id)}`,[context,setContext]=useState<LanguageContext|null>(null),[preparation,setPreparation]=useState<LanguagePreparation>({schema_version:school?3:2,...(school?{school:initialSchool}:{}),review_id:review.id,review_sha256:review.review_sha256,edits:[],figure_versions:[]}),[dirty,setDirty]=useState(true),[decisions,setDecisions]=useState<Record<string,ItemDecision>>({}),[versions,setVersions]=useState<FigureVersion[]>([]),[artifacts,setArtifacts]=useState<LanguageArtifact[]>([]),[selected,setSelected]=useState<LanguageArtifact|null>(null),[artifactId,setArtifactId]=useState(''),[confirmed,setConfirmed]=useState(false)
 const history=useResearchRead<{items:SavedLanguageReview[]}>(`${base}/reviews/${encodeURIComponent(review.id)}/language-reviews`,op.valid)
 const savedReviews=new Map((history.data?.items??[]).map(item=>[item.id,item]))
 for(const artifact of artifacts)if(!savedReviews.has(artifact.id))savedReviews.set(artifact.id,{id:artifact.id,created_at:''})
 const [savedPreparation,setSavedPreparation]=useState(()=>JSON.stringify(preparation))
 useManuscriptDraft(JSON.stringify(preparation)!==savedPreparation||Object.keys(decisions).length>0||confirmed)
 function invalidate(){setDirty(true);setDecisions({});setSelected(null);setConfirmed(false)}
 function figureLanguage(identity:string){
  const candidate=review.candidate
  if(!school)return candidate.output_language
  const owners=candidate.sections?.filter(c=>c.result_group_ids?.some(id=>candidate.results_groups.some(g=>g.id===id&&g.figures.some(f=>f.id===identity))))??[]
  return owners.length===1?owners[0].output_language:undefined
 }
 function figureCreated(version:FigureVersion){
  setVersions(old=>[...old.filter(item=>item.id!==version.id),version])
 }
 async function loadFigures(){
  const existingIds=new Set(versions.map(item=>item.id))
  const result=await op.run(`/api/v1/projects/${encodeURIComponent(projectId)}/manuscript-figure-language-versions`,listOf((v):v is FigureVersion=>validFigureVersion(v,projectId)))
  if(!result)return
  const loadedIds=new Set(result.items.map(item=>item.id))
  setVersions(old=>[...result.items,...old.filter(item=>!existingIds.has(item.id)&&!loadedIds.has(item.id))])
 }
 async function load(preview=false){setSelected(null);setConfirmed(false);const result=await op.run(`${base}/reviews/${encodeURIComponent(review.id)}/language-context`,(v):v is LanguageContext=>validLanguageContext(v,projectId,review),preview||school?preparation:undefined,school?{timeoutMs:110000}:undefined);if(!result)return;if(result){setContext(result);setDirty(false);setDecisions({});if(!preview&&!school)setPreparation({schema_version:2,review_id:review.id,review_sha256:review.review_sha256,edits:[],figure_versions:[]})}if(!customerSci||result.candidate.results_groups.some(g=>g.figures.length))await loadFigures()}
 const inventoryFigures=context?.candidate.results_groups.flatMap(group=>group.figures)??[]
 const ready=context&&!dirty&&context.inventory.length>0&&context.inventory.every(item=>{
  const decision=decisions[item.location]
  if(!decision?.decision||!decision.reason.trim()||unlocatedEmptyImage(item,inventoryFigures))return false
  if(readable)return decision.decision===plannedDecision(item,school)
  return plannedDecision(item,school)==='provided_literal'?decision.decision==='provided_literal':['target_language','no_text'].includes(decision.decision)
 })
 async function save(){if(!context||!ready)return;const result=await op.run(`${base}/language-reviews`,(v):v is LanguageArtifact=>validLanguageArtifact(v,projectId,review),{...preparation,inventory_sha256:context.inventory_sha256,decisions:context.inventory.map(i=>({location:i.location,content_sha256:i.content_sha256,...decisions[i.location]}))});if(result){setArtifacts(old=>[...old.filter(a=>a.id!==result.id),result]);setSelected(null);setConfirmed(false);setDecisions({});setSavedPreparation(JSON.stringify(preparation));history.refresh()}}
 async function chooseArtifact(id:string){
  setSelected(null);setConfirmed(false)
  if(!id)return
  const found=artifacts.find(a=>a.id===id)
  const result=found??await op.run(`${base}/language-reviews/${encodeURIComponent(id)}`,(v):v is LanguageArtifact=>validLanguageArtifact(v,projectId,review)&&v.id===id)
  if(result){if(!found)setArtifacts(old=>[...old.filter(a=>a.id!==result.id),result]);setSelected(result)}
 }
 async function publish(){if(!selected||!confirmed)return;const result=await op.run(`${base}/publish`,(v):v is Manuscript=>validManuscript(v,projectId)&&v.id===manuscriptId&&v.current_revision>baseRevision,{schema_version:2,expected_revision:baseRevision,review_id:review.id,review_sha256:review.review_sha256,language_review_id:selected.id,language_review_sha256:selected.artifact_sha256});if(result)onPublished(result)}
 return <section aria-label={t('独立语言审核与发布')}><h4>{t('独立语言审核与发布')}</h4><p>{t('已绑定所选科学审核产物')} · {t('稿件版本')} {baseRevision}</p><ManuscriptPreview customerSci={customerSci} customerView={readable} snapshot={review.candidate} label="科学审后版本"/><fieldset disabled={op.busy||!op.valid}><button type="button" onClick={()=>void load()}>{t('读取真实 DOCX 全语言清单')}</button></fieldset>{school&&op.valid&&<SchoolExportPanel version={{revision:baseRevision,snapshot:review.candidate}} customerView={customerThesis} value={preparation.school??initialSchool} onChange={value=>{invalidate();setPreparation(old=>({...old,school:value}))}} onPreview={()=>void load(true)} busy={op.busy} disabled={!op.valid} plan={null}/>}
 {op.valid&&<FigureLanguagePanel projectId={projectId} snapshot={review.candidate}
  confirmOnly={customerSci&&!readable} reviewLanguageForFigure={readable?figureLanguage:undefined}
  onCreated={readable?figureCreated:customerSci?()=>void loadFigures():undefined}/>}
 {context&&op.valid&&<><fieldset disabled={op.busy}><legend>{t('仅修改服务端列出的图表文字')}</legend><p>{t('正文、题摘或文献改写须返回科学审核，不可在语言审核绕过。')}</p>{context.editable_fields.map((f,index)=>{const edit=preparation.edits.find(e=>e.path===f.path);return <fieldset key={f.path}><legend>{t(f.path.endsWith('caption')?'图表说明':f.path.endsWith('title')?'图表标题':f.path.includes('panel')?'图表面板文字':f.path.includes('table')?'表格文字':'图表文字项目')} {index+1}</legend><blockquote>{f.text}</blockquote><label>{t('局部语言修正')}<textarea value={edit?.text??f.text} onChange={e=>{invalidate();setPreparation(old=>({...old,edits:[...old.edits.filter(v=>v.path!==f.path),{path:f.path,original_sha256:f.original_sha256,text:e.target.value,reason:edit?.reason??''}]}))}}/></label><label>{t('局部修正理由')}<input value={edit?.reason??''} onChange={e=>{invalidate();setPreparation(old=>({...old,edits:[...old.edits.filter(v=>v.path!==f.path),{path:f.path,original_sha256:f.original_sha256,text:edit?.text??f.text,reason:e.target.value}]}))}}/></label>{edit&&<button type="button" onClick={()=>{invalidate();setPreparation(old=>({...old,edits:old.edits.filter(v=>v.path!==f.path)}))}}>{t('撤销此修正')}</button>}</fieldset>})}
 {review.candidate.results_groups.flatMap(group=>group.figures).map(figure=>{
  const source=review.candidate.sources.find(item=>item.id===figure.source_ids[0])
  const language=figureLanguage(figure.id)
  const available=versions.filter(version=>source&&version.output_language===language&&
   version.original.file_id===source.file_id&&version.original.kind===source.kind&&version.original.id===source.id&&
   version.original.sha256===figure.sha256&&(version.original.image_id??null)===(figure.image_id??null))
  return <label key={figure.id}>{t('明确选择独立图版本')} {figure.title}
   <select value={preparation.figure_versions.find(item=>item.figure_id===figure.id)?.version_id??''} onChange={e=>{
    const versionId=e.target.value
    invalidate()
    setPreparation(old=>({...old,figure_versions:[...old.figure_versions.filter(item=>item.figure_id!==figure.id),
     ...(versionId?[{figure_id:figure.id,version_id:versionId,original_sha256:figure.sha256}]:[])]}))
   }}>
    <option value="">{t('保留原图（仍须语言核对）')}</option>
    {available.map((version,index)=><option key={version.id} value={version.id}>{version.title} · {t('图版本')} {index+1} · {t(version.output_language==='en'?'英文':'中文')}</option>)}
   </select>
  </label>
 })}
 <button type="button" onClick={()=>void load(true)}>{t('预览修正后的完整语言清单')}</button></fieldset>{dirty?<p role="alert">{t('材料已更改，旧清单决定和发布选择已失效。请重新预览。')}</p>:<><p>{t('已读取当前固定版本的语言核对清单')}</p><ManuscriptPreview customerSci={customerSci} customerView={readable} snapshot={context.candidate} label="完整语言审核候选"/><fieldset disabled={op.busy}>{context.inventory.map((i,index)=><LanguageItem customerSci={customerSci} readable={readable} school={school} figures={inventoryFigures} inventory={context.inventory} index={index+1} key={i.location+':'+i.content_sha256} item={i} value={decisions[i.location]??{decision:'',reason:'',exceptions:[]}} onChange={value=>{setDecisions(old=>({...old,[i.location]:value}));setSelected(null);setConfirmed(false)}}/>)}<button type="button" disabled={!ready} onClick={()=>void save()}>{t('封存独立语言审核')}</button></fieldset></>}</>}{op.valid&&<fieldset disabled={op.busy} style={{minWidth:0,overflowWrap:'anywhere'}}><legend>{t('选择语言产物并显式发布')}</legend>{history.error&&<p role="alert">{t(history.error)} <button type="button" onClick={history.refresh}>{t('重试')}</button></p>}{!readable&&<details><summary>{t('高级设置：按编号回读历史语言产物')}</summary><label>{t('历史语言产物编号')}<input value={artifactId} onChange={e=>setArtifactId(e.target.value)}/></label><button type="button" disabled={!artifactId.trim()} onClick={()=>void chooseArtifact(artifactId.trim())}>{t('回读语言产物')}</button></details>}<label>{t('明确选择语言审核产物')}<select value={selected?.id??''} onChange={e=>void chooseArtifact(e.target.value)}><option value="">{t('尚未选择')}</option>{[...savedReviews.values()].map((a,index)=><option key={a.id} value={a.id}>{t('语言审核产物')} {index+1} · {a.created_at?new Date(a.created_at).toLocaleString(locale):review.candidate.title}</option>)}</select></label>{selected&&<div style={{minWidth:0,overflowWrap:'anywhere'}}><p>{t('已选定固定审核候选；仅在下方明确确认后发布。')}</p>{school&&(readable?<section><h5>{t('已固定的学校导出选项')}</h5><ReadableDetails value={selected.candidate.writing_provenance?.school_export_options}/></section>:<details><summary>{t('已固定的学校导出选项')}</summary><ReadableDetails value={{[t('学校导出选项')]:selected.candidate.writing_provenance?.school_export_options}}/></details>)}<ManuscriptPreview customerSci={customerSci} customerView={readable} snapshot={selected.candidate} label="待显式发布的最终版本"/></div>}<label><input type="checkbox" checked={confirmed} disabled={!selected} onChange={e=>setConfirmed(e.target.checked)}/>{t('我已核对所选科学与语言产物及最终版本，明确发布为不可变新版本。')}</label><button type="button" disabled={!selected||!confirmed} onClick={()=>void publish()}>{t('显式发布审核后版本')}</button></fieldset>}{op.error&&<p role="alert">{t(op.error)}</p>}</section>
}
