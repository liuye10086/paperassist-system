import {systemCheckText} from '../../shared/i18n/systemChecks'
import {protocolLabel,severities} from '../../shared/i18n/protocolLabels'
import {useReviewDraftGuard} from './reviewActivityContext'
import {useEffect,useRef,useState} from 'react'
import useResearchDraft from '../research-results/useResearchDraft'
import {canonicalJson,wireDigest} from '../manuscripts/writingLiveTypes'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import {safeError,useI18n} from '../../shared/i18n'
import {useDocumentVisible} from '../tasks/useDocumentVisible'
import type {Inputs,Round} from './reviewTypes'
import {reviewHash} from './reviewTypes'
import {reviewBase,revisionHash,contentText} from './revisionTypes'
import {manuscriptHash,validContinuation,validReturn,type ContinuationContext,type ManuscriptInput,type NextRoundInput,type UserReturn,type ReturnMapping} from './continuationTypes'
import {useReviewRequest} from './useReviewRequest'
import {customerReturnLocation,reviewSectionTitle} from './customerReviewDisplay'
import VersionLabel from '../../shared/VersionLabel'
import {versionLabelText} from '../../shared/versionLabelText'
import type {ManuscriptPlace} from './ReviewsWorkspace'
type Document=Inputs['documents'][number]
type Props={expanded?:boolean;customer?:boolean;projectId:string;projectType?:'sci'|'thesis';round:Round;documents:Inputs['documents'];recentFileIds?:string[];active:boolean;onPrepareNext:(input:NextRoundInput)=>void;onOpenTask:(id:string)=>void
 // Customer navigation stays inside the customer address (and its return token) instead of operator hash links.
 onOpenRound?:(roundId:string)=>void;onOpenManuscript?:(manuscript:ManuscriptInput,place:ManuscriptPlace)=>void}
// Customer selections; an absent key means "use the carried default" (B04 task 12, wireframe 16). They are kept for
// this browser tab per account and round, so a refresh does not ask again (B05 task 8); never in the address.
type Choice={version?:string;run?:string;export?:string;parse?:string}
const noChoice=():Choice=>({})
const noFiles:string[]=[]
export default function ReturnContinuationPanel(props:Props){return <Panel key={`${props.projectId}:${props.round.id}`} {...props}/>}
const customerSteps=['上传返回的 Word','核对差异','采用返回稿','用返回稿开始下一轮']
const customerReturnChecks = new Map([
 ['正文改变；改变段落不继承原支持绑定。','正文有改动。请重新核对改动段落的依据。'],
 ['固定导出的封面、目录、图题、书目或人工附加内容变化；保留原件并须人工核对。','送审 Word 的封面、目录、图题、参考文献或手动添加的内容有改动。请保留送审稿和返回稿，逐项核对改动。'],
 ['已核对固定导出中未变的封面、目录、图表说明和人工附加内容；保留在原导出与回传原件，未当作新增研究正文。','两份 Word 中未改动的封面、目录、图表说明和手动添加的内容已核对并保留。这些内容不计入新增正文。'],
 ['无固定导出可核对页眉页脚、脚注或尾注。','缺少可供对照的送审 Word，无法核对页眉、页脚、脚注或尾注。'],
 ['已绑定论述发生变化，不能继承原支持；请先重新核实。','论述已改动。请重新核对依据是否支持改动后的表述。'],
])
function Panel({expanded,projectId,projectType,round,documents,recentFileIds=noFiles,active,onPrepareNext,onOpenTask,onOpenRound,onOpenManuscript,customer=false}:Props){
 const {t,locale}=useI18n(),visible=useDocumentVisible(),{request,run,available,busy,error,setError}=useReviewRequest(),base=reviewBase(projectId)
 const mappingDirty=useRef(false),opened=useRef(false)
 const [open,setOpen]=useState(!!expanded),[context,setContext]=useState<ContinuationContext|null>(null),[refresh,setRefresh]=useState(0)
 const [versionId,setVersionId]=useState(''),[sourceRun,setSourceRun]=useState(''),[exportId,setExportId]=useState(''),[parseId,setParseId]=useState(''),[selectedId,setSelectedId]=useState(''),[returned,setReturned]=useState<UserReturn|null>(null),[mappings,setMappings]=useState<ReturnMapping[]>([])
 const [savedChoice,setChoice]=useResearchDraft<Choice>(projectId,`review-return-choice:${round.id}`,noChoice)
 const [changing,setChanging]=useState<{version?:boolean;parse?:boolean}>({})
 const hasNextRound=!!round.next_round_ids?.length
 useEffect(()=>{if(!(expanded||open)||!active||!visible||!available)return;const c=new AbortController();void request(base+'/rounds/'+encodeURIComponent(round.id)+'/continuation-context',(v):v is ContinuationContext=>validContinuation(v,projectId,round.id),undefined,c.signal).then(v=>{
  if(c.signal.aborted)return
  setContext(v)
  // Open the latest return that is not adopted, or adopted without a next round yet; never register again.
  if(customer&&!opened.current){opened.current=true;const latest=v.returns.find(r=>!r.output||!hasNextRound);if(latest)setSelectedId(current=>current||latest.id)}
 }).catch(cause=>{if(!c.signal.aborted)setError(safeError(cause,'回传上下文读取失败。'))});return()=>c.abort()},[expanded,open,active,visible,available,base,round.id,projectId,refresh,request,setError,customer,hasNextRound])
 useEffect(()=>{if(!selectedId||!(expanded||open)||!active||!visible||!available)return;const c=new AbortController();let timer=0;async function load(){try{const v=await request(base+'/returns/'+encodeURIComponent(selectedId),(v):v is UserReturn=>validReturn(v,projectId,round.id)&&v.id===selectedId,undefined,c.signal);if(c.signal.aborted)return;if(!mappingDirty.current){setReturned(v);setMappings(v.mappings)}if(v.output?.status==='pending')timer=window.setTimeout(()=>void load(),2500)}catch(cause){if(!c.signal.aborted)setError(safeError(cause,'回传状态读取失败。'))}}void load();return()=>{c.abort();window.clearTimeout(timer)}},[selectedId,expanded,open,active,visible,available,refresh,base,round.id,projectId,request,setError])
 const wordDocuments=documents.filter(d=>d.kind==='docx_document')
 // A customer chooses a file. Its newest available parse is the only option for that file.
 const returnFiles=customer?wordDocuments.filter(d=>!wordDocuments.some(o=>o.file_id===d.file_id&&o.version>d.version))
  .filter((d,i,all)=>all.findIndex(o=>o.file_id===d.file_id)===i):wordDocuments
 const savedFile=wordDocuments.find(d=>d.document_version_id===savedChoice.parse)
 // A saved choice whose file or version is no longer offered falls back to the carried default.
 const choice:Choice=context?{
  version:savedChoice.version===''||context.eligible_inputs.some(i=>i.version_id===savedChoice.version)?savedChoice.version:undefined,
  run:savedChoice.run===''||context.successful_revisions.some(r=>r.id===savedChoice.run)?savedChoice.run:undefined,
  export:savedChoice.export===''||context.eligible_inputs.some(i=>i.exports.some(e=>e.id===savedChoice.export))?savedChoice.export:undefined,
  parse:savedChoice.parse===''?'':returnFiles.find(d=>d.file_id===savedFile?.file_id)?.document_version_id,
 }:{}
 const autoVersion=customer&&context?.eligible_inputs.some(i=>i.version_id===round.manuscript.version_id)?round.manuscript.version_id:''
 const chosenVersion=customer?choice.version??autoVersion:versionId
 const input=context?.eligible_inputs.find(i=>i.version_id===chosenVersion)
 const runs=context?.successful_revisions.filter(r=>r.output.version_id===chosenVersion)??[]
 const autoRun=customer&&runs.length===1?runs[0].id:''
 const chosenRun=customer?choice.run??autoRun:sourceRun
 // Historical blind exports stay readable elsewhere but are never the default original Word.
 const signedExports=input?.exports.filter(e=>e.status==='succeeded'&&e.review_mode!=='blind')??[]
 const autoExport=customer?signedExports[0]?.id??'':''
 const chosenExport=customer?choice.export??autoExport:exportId
 const recentFile=customer?[...recentFileIds].reverse().find(id=>returnFiles.some(d=>d.file_id===id)):undefined
 const autoParse=returnFiles.find(d=>d.file_id===recentFile)?.document_version_id??''
 const chosenParse=customer?choice.parse??autoParse:parseId
 const doc=returnFiles.find(d=>d.document_version_id===chosenParse)
 const returnFileLabel=(d:Document)=>{
  const same=returnFiles.filter(o=>o.filename===d.filename)
  return same.length>1?`${d.filename} · ${t('第 {number} 次上传',{number:same.indexOf(d)+1})}`:d.filename
 }
 const systemVersions=new Set(context?.successful_revisions.map(r=>r.output.version_id))
 const versionOptions=[...(context?.eligible_inputs.filter(i=>systemVersions.has(i.version_id))??[]),...(context?.eligible_inputs.filter(i=>!systemVersions.has(i.version_id))??[])]
 const valid=(v:unknown):v is UserReturn=>validReturn(v,projectId,round.id)
 const chapterTitle=(chapter:{id:string;title:string})=>customer
  ? reviewSectionTitle(chapter.title,chapter.id,t)||t('稿件章节') : chapter.title
 const checkMessage=(value:string)=>systemCheckText(value,customer?customerReturnChecks:undefined)||t('检查说明不可用，请核对原始记录。')
 function returnIssueLocation(value:unknown) {
  const location=customerReturnLocation(value,returned?.target_chapters??[],t)
  return location?' · '+location:''
 }
 function choose(v:UserReturn){mappingDirty.current=false;setReturned(v);setMappings(v.mappings);setSelectedId(v.id);setContext(old=>old?{...old,returns:[v,...old.returns.filter(r=>r.id!==v.id)]}:old)}
 function mapSection(inputSectionId:string,chapterId:string){mappingDirty.current=true;setMappings(old=>[...old.filter(m=>m.input_section_id!==inputSectionId),...(chapterId?[{input_section_id:inputSectionId,chapter_id:chapterId}]:[])]);setReturned(old=>old?{...old,can_adopt:false,preview_sha256:null,differences:[]}:old)}
 const mapped=!!returned&&mappings.length===returned.input_sections.length&&mappings.length===returned.target_chapters.length&&new Set(mappings.map(m=>m.chapter_id)).size===mappings.length
 const mappingChanged=!!returned&&JSON.stringify(mappings)!==JSON.stringify(returned.mappings)
 const differs=(value:string|undefined,carried:string)=>value!==undefined&&value!==carried
 const customerDirty=!returned&&(differs(choice.version,autoVersion)||differs(choice.parse,autoParse)||differs(choice.run,autoRun)||differs(choice.export,autoExport))
 useReviewDraftGuard(customer?customerDirty||mappingChanged:!!(versionId||parseId||mappingChanged))
 function register(){void run(async()=>{
  if(!input||!doc)return
  const body={manuscript:{id:input.id,revision:input.revision,version_id:input.version_id},revision_id:chosenRun||null,file_id:doc.file_id,document_version_id:doc.document_version_id,base_export_id:chosenExport||null,synthetic:round.synthetic}
  // Customer registration uses a deterministic key so a repeated click returns the same saved return. The key digests
  // the whole selection (at most 128 characters), so another revision run or original Word is a new return (B05 task 8).
  const key=customer?`return:${round.id}:${await wireDigest(canonicalJson({v:input.version_id,d:doc.document_version_id,r:chosenRun||null,e:chosenExport||null}))}`:undefined
  choose(await request(base+'/rounds/'+encodeURIComponent(round.id)+'/returns',valid,body,undefined,key))
  if(customer)setChoice({})
 })}
 const otherReturns=context?.returns.filter(r=>r.id!==selectedId)??[]
 // Customer wording (B04 task 13): thesis returns come from the supervisor, SCI returns stay neutral.
 const returnedWord=projectType==='thesis'?'导师返回的 Word':'返回的 Word'
 const step=returned?.output?3:returned?2:doc?1:0
 if(!available)return <p role="status">{t('会话或项目不可用，请重新打开项目。')}</p>
 return <section className="review-continuation manuscript-panel" aria-label={t(customer?returnedWord:'回传与下一轮')}>
  {customer?<><h3 tabIndex={-1} data-review-return-focus={active?true:undefined}>{t(returnedWord)}</h3>{projectType==='thesis'&&<p className="muted">{t('导师或评阅人返回')}</p>}
   <ol className="review-return-steps" aria-label={t('返回稿步骤')}>{customerSteps.map((label,index)=><li key={label} aria-current={index===step?'step':undefined}>{t(label)}</li>)}</ol></>
   :<button type="button" onClick={()=>setOpen(v=>!v)} aria-expanded={expanded||open}>{t('回传与下一轮')}</button>}
  {(expanded||open)&&<>
  {!customer&&<p>{t('先选定公共父稿，再登记清洁 DOCX；逐章核对差异后另存新稿，公共稿件任务成功后才可开始下一轮。')}</p>}{round.synthetic&&<p className="warning-panel">{t('本轮和回传使用合成材料。')}</p>}{error&&<p role="alert" className="error-panel">{t(error)}</p>}
  {customer?(onOpenRound&&(round.continuation||!!round.next_round_ids?.length))&&<div className="review-inline-actions">
    {round.continuation&&<button type="button" onClick={()=>onOpenRound(round.continuation!.previous_round_id)}>{t('查看上一轮')}</button>}
    {round.next_round_ids?.map(id=><button key={id} type="button" onClick={()=>onOpenRound(id)}>{t('查看下一轮')}</button>)}</div>
   :<><a href={reviewHash(projectId,round.id)}>{t('当前固定意见轮次')}</a>{round.continuation&&<a href={reviewHash(projectId,round.continuation.previous_round_id)}>{t('查看上一轮原稿、系统修改与回复')}</a>}{round.next_round_ids?.map(id=><a key={id} href={reviewHash(projectId,id)}>{t('查看关联下一轮')}</a>)}</>}
  {customer?<fieldset disabled={busy||!context}><legend>{t('送审稿与返回的 Word')}</legend>
   {input&&!changing.version&&choice.version===undefined
    ? <p className="review-carried"><strong>{t('送审稿')}</strong> · <VersionLabel revision={input.revision} savedAt={input.saved_at??''}/>{t('（已带入）')}
     <button type="button" onClick={()=>setChanging(old=>({...old,version:true}))}>{t('换一版')}</button></p>
    : <label>{t(autoVersion?'换一版送审稿':'选择送审稿')}<select value={chosenVersion} onChange={e=>{const version=e.target.value;setChoice(old=>({...old,version,run:undefined,export:undefined}))}}>
     <option value="">{t('请选择送审稿')}</option>
     {versionOptions.map(i=><option key={i.version_id} value={i.version_id}>{i.title} · {versionLabelText(t,locale,i.revision,i.saved_at??'')}{systemVersions.has(i.version_id)?' · '+t('系统修改稿'):''}</option>)}
    </select></label>}
   {runs.length>1&&<label>{t('对应的系统修改（可选）')}<select value={chosenRun} onChange={e=>{const value=e.target.value;setChoice(old=>({...old,run:value}))}}><option value="">{t('不关联')}</option>{runs.map((r,index)=><option key={r.id} value={r.id}>{t('修改批次 {number}',{number:runs.length-index})}</option>)}</select></label>}
   {signedExports.length>1&&<label>{t('对应的 Word（可选）')}<select value={chosenExport} onChange={e=>{const value=e.target.value;setChoice(old=>({...old,export:value}))}}><option value="">{t('不关联')}</option>{signedExports.map((e,i)=><option key={e.id} value={e.id}>{e.created_at?t('Word 文件（生成于 {time}）',{time:new Date(e.created_at).toLocaleString(locale)}):t('Word 文件 {number}',{number:signedExports.length-i})}</option>)}</select></label>}
   {doc&&!changing.parse&&choice.parse===undefined
    ? <p className="review-carried">{doc.filename} · {t('已带入')}<button type="button" onClick={()=>setChanging(old=>({...old,parse:true}))}>{t('换一个文件')}</button></p>
    : <label>{t(returnedWord)}<select value={chosenParse} onChange={e=>{const value=e.target.value;setChoice(old=>({...old,parse:value}))}}><option value="">{t('请选择返回的 Word')}</option>{returnFiles.map(d=><option key={d.document_version_id} value={d.document_version_id}>{returnFileLabel(d)}</option>)}</select></label>}
   <p>{t('图片、表格、域、页眉、注释和修订等内容暂不支持，会阻止采用；请保留原件，处理后重新上传。')}</p>
   <button type="button" className="button-primary" disabled={!input||!doc} onClick={register}>{t('核对差异')}</button>
   <button type="button" disabled={!input} onClick={()=>{if(input)onPrepareNext({previous_round_id:round.id,manuscript:{id:input.id,revision:input.revision,version_id:input.version_id}})}}>{t('开始下一轮（不使用返回稿）')}</button></fieldset>
  :<fieldset disabled={busy||!context}><legend>{t('登记清洁回传')}</legend><label>{t('回传依据的公共稿件版本')}<select value={versionId} onChange={e=>{setVersionId(e.target.value);setSourceRun('');setExportId('')}}><option value="">{t('请明确选择公共版本')}</option>{context?.eligible_inputs.map(i=><option key={i.version_id} value={i.version_id}>{i.title} · {t('版本 {number}',{number:i.revision})}</option>)}</select></label>
  <label>{t('原系统修改批次（可选）')}<select value={sourceRun} onChange={e=>setSourceRun(e.target.value)}><option value="">{t('不关联')}</option>{runs.map((r,index)=><option key={r.id} value={r.id}>{customer?t('修改批次 {number}',{number:runs.length-index}):t('成功修改批次')+' · '+r.id}</option>)}</select></label>{sourceRun&&<a href={revisionHash(projectId,round.id,sourceRun)}>{t('查看对应系统修改与回复')}</a>}
  <label>{t('原 DOCX 导出（可选）')}<select value={exportId} onChange={e=>setExportId(e.target.value)}><option value="">{t('不关联')}</option>{input?.exports.filter(e=>e.status==='succeeded').map((e,i)=><option key={e.id} value={e.id}>{t('固定导出 {number}',{number:i+1})}{!customer&&' · '+e.id}</option>)}</select></label>
  <label>{t('清洁 DOCX 解析版本')}<select value={parseId} onChange={e=>setParseId(e.target.value)}><option value="">{t('请选择解析文件')}</option>{documents.filter(d=>d.kind==='docx_document').map(d=><option key={d.document_version_id} value={d.document_version_id}>{d.filename} · {t('版本 {number}',{number:d.version})}</option>)}</select></label><p>{t('可使用本页上传解析入口补充 DOCX。图片、表格、域、页眉、注释和修订等不支持内容会阻止采用，请保留原件并处理问题。')}</p>
  <button type="button" disabled={!input||!doc} onClick={register}>{t('登记回传原件')}</button>
  <button type="button" disabled={!input} onClick={()=>{if(input)onPrepareNext({previous_round_id:round.id,manuscript:{id:input.id,revision:input.revision,version_id:input.version_id}})}}>{t('用所选公共版本准备下一轮')}</button></fieldset>}
  {customer&&otherReturns.length>0&&<section className="review-other-returns" aria-label={t('其他返回稿')}><h4>{t('其他返回稿')}</h4><ul>{otherReturns.map(r=><li key={r.id}>
   <button type="button" disabled={busy} onClick={()=>{mappingDirty.current=false;setSelectedId(r.id);setReturned(null);setMappings([])}}>{t('返回稿登记于 {time}',{time:new Date(r.created_at).toLocaleString(locale)})}</button></li>)}</ul></section>}
  {!customer&&!!context?.returns.length&&<label>{t('查看固定回传记录')}<select disabled={busy} value={selectedId} onChange={e=>{mappingDirty.current=false;setSelectedId(e.target.value);setReturned(null);setMappings([])}}><option value="">{t('请选择固定回传记录')}</option>{context.returns.map((r,i)=><option key={r.id} value={r.id}>{t('回传记录 {number}',{number:context.returns.length-i})} · {customer?new Date(r.created_at).toLocaleString(locale):r.created_at}</option>)}</select></label>}
  {returned&&<article><h4>{t(customer?'差异与采用':'回传对照与采用')}</h4>{!customer&&<p>{t('回传固定父稿版本 {number}',{number:returned.base_revision})}</p>}
  {customer?<div className="review-inline-actions">{onOpenManuscript&&<button type="button" onClick={()=>onOpenManuscript({id:returned.manuscript_id,revision:returned.base_revision,version_id:returned.base_version_id},{roundNumber:round.round_number})}>{t('查看送审稿')}</button>}</div>
   :<div className="review-inline-actions"><a href={manuscriptHash(projectId,{id:returned.manuscript_id,revision:returned.base_revision,version_id:returned.base_version_id})}>{t('查看回传固定父稿')}</a>{returned.revision_id&&<a href={revisionHash(projectId,returned.previous_round_id,returned.revision_id)}>{t('查看原系统修改与回复')}</a>}</div>}
  <ProjectDownloadLink href={returned.original_download_url} filename={documents.find(d=>d.document_version_id===returned.source.document_version_id)?.filename??'returned.docx'}>{t(customer?'下载返回的 Word':'下载回传原件')}</ProjectDownloadLink>
  <fieldset disabled={busy||!!returned.output}><legend>{t(customer?'章节对照':'回传章节映射')}</legend>
   {returned.input_sections.map(section=><div key={section.id}>
    <label>{t(customer?'返回稿“{title}”对应的章节':'回传章节“{title}”对应稿件章节',{title:chapterTitle(section)})}
     <select value={mappings.find(mapping=>mapping.input_section_id===section.id)?.chapter_id??''}
      onChange={event=>mapSection(section.id,event.target.value)}>
      <option value="">{t(customer?'请选择章节':'请逐章明确选择')}</option>
      {returned.target_chapters.map(chapter=><option key={chapter.id} value={chapter.id}>{chapterTitle(chapter)}</option>)}
     </select>
    </label>
    {customer?<blockquote>{section.paragraphs.map((paragraph,index)=><p key={index}>{paragraph}</p>)}</blockquote>
     :<details><summary>{section.title} · {t('查看回传正文')}</summary>{section.paragraphs.map((paragraph,index)=><p key={index}>{paragraph}</p>)}</details>}
   </div>)}
   {(!customer||mappingChanged)&&<button type="button" disabled={!mapped} onClick={()=>void run(async()=>{
    const preview=await request(base+'/returns/'+encodeURIComponent(returned.id)+'/preview',valid,{mappings})
    mappingDirty.current=false;setReturned(preview);setMappings(preview.mappings)
   })}>{t(customer?'重新核对差异':'预览回传差异与问题')}</button>}
  </fieldset>
  {returned.differences.map((d,i)=><article key={i}><h5>{checkMessage(d.message)}</h5><small>{customer?customerReturnLocation(d.location,returned.target_chapters,t):contentText(d.location)}</small><dl><dt>{t('修改前')}</dt><dd>{d.before}</dd><dt>{t('修改后')}</dt><dd>{d.after}</dd></dl></article>)}{returned.issues.map((issue,i)=><p key={i} className="warning-panel">{protocolLabel(severities,issue.severity)} · {checkMessage(issue.message)}{customer?returnIssueLocation(issue.location):' · '+contentText(issue.location)}</p>)}
  <p>{t(customer?'改动过的段落需要重新核对引用和数值；未改动的段落保持不变。':'已改变正文的引用和数值绑定需重新核验；未改动的段落保留原绑定。')}</p>
  <button type="button" disabled={busy||!!returned.output||!mapped||!returned.can_adopt||!returned.preview_sha256||!context}
   onClick={()=>void run(async()=>{
    if(!context)return
    const saved=await request(base+'/returns/'+encodeURIComponent(returned.id)+'/adopt',valid,{
     mappings,expected_current_revision:context.expected_current_revision,preview_sha256:returned.preview_sha256,
    })
    choose(saved)
    setRefresh(value=>value+1)
   })}>{t(customer?'采用返回稿':'采用回传并另存公共稿')}</button>
  {returned.output&&(customer
   ? <><p role="status">{returned.output.status==='published'?t('返回稿已保存为第 {revision} 版',{revision:returned.output.revision}):t(returned.output.status==='failed'?'保存失败，请查看任务结果':'正在保存返回稿……')}</p>
    {returned.output.status!=='published'&&<button type="button" onClick={()=>onOpenTask(returned.output!.task_id)}>{t('查看任务结果')}</button>}</>
   : <><p role="status">{t(returned.output.status==='published'?'回传公共新稿已完成。':returned.output.status==='failed'?'回传公共稿件任务失败，请查看任务。':'回传已保存，公共稿件任务尚待完成。')}</p><button type="button" onClick={()=>onOpenTask(returned.output!.task_id)}>{t('查看回传公共稿件任务')}</button>{returned.output.status==='published'&&<a href={manuscriptHash(projectId,{id:returned.output.manuscript_id,revision:returned.output.revision,version_id:returned.output.version_id})}>{t('查看固定回传新稿')}</a>}</>)}
  {returned.output&&<button type="button" disabled={returned.output.status!=='published'} onClick={()=>{const out=returned.output!;onPrepareNext({previous_round_id:round.id,user_return_id:returned.id,manuscript:{id:out.manuscript_id,revision:out.revision,version_id:out.version_id}})}}>{t(customer?'用返回稿开始下一轮':'用此回传稿准备下一轮')}</button>}
  </article>}<button type="button" disabled={busy} onClick={()=>setRefresh(v=>v+1)}>{t(customer?'刷新':'刷新回传状态')}</button>
 </>}</section>
}
