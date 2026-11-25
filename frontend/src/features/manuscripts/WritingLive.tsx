import useResearchDraft from '../research-results/useResearchDraft'
import {protocolLabel,sourceKinds,writingModes,taskStatusLabel} from '../../shared/i18n/protocolLabels'
import {useManuscriptDraft} from './useManuscriptDraft'
import {useCallback,useEffect,useRef,useState} from 'react'
import {useI18n,apiError} from '../../shared/i18n'
import TaskPendingAction from '../tasks/TaskPendingAction'
import {isWorkspace,type TaskWorkspace} from '../tasks/taskTypes'
import {manuscriptBase,sectionIds,sectionLabels,type Manuscript,type ManuscriptVersion} from './manuscriptTypes'
import {frozenWritingEvidence,writableSchoolPurpose,object,listOf,canonicalJson,requestUsesGroup,validBundle,validCapabilities,validLiveRequest,type ArticlePreviewInput,type Authorization,type Bundle,type LegacyPreviewInput,type LiveRequest,type PreviewInput,type WritingCapabilities} from './writingLiveTypes'
import {useWritingOperation} from './useWritingOperation'
import useCustomerWritingSubmit,{authorizationsUrl,resultNotFound} from './useCustomerWritingSubmit'
import CustomerWritingConfirm from './CustomerWritingConfirm'
import WritingBundlePreview from './WritingBundlePreview'
import WritingAuthorization from './WritingAuthorization'
import WritingScienceReview,{type ParagraphLocation,type SourceKind} from './WritingScienceReview'
import ArticleWritingFields from './ArticleWritingFields'
import PaperPlanSummary from './PaperPlanSummary'
import {plannedWritingSources} from './paperPlan'
import {purposeLabels} from './thesisTypes'
import type {SciSettings} from '../customer/sciProjectSettings'
/** Where a customer left to add a source, so the trip can come back to the same request and paragraph. */
export type WritingPlace={writingRequest:string;paragraph:string}
export type NeedSource=(kind:SourceKind,place:WritingPlace,location:ParagraphLocation)=>void
type Props={active?:boolean;customerSci?:SciSettings|null;customerThesis?:boolean;projectId:string;manuscriptId:string;version:ManuscriptVersion;onPublished:(v:Manuscript)=>void;initialWritingRequest?:string;initialParagraph?:string;onNeedSource?:NeedSource}
const inProgress=(item:LiveRequest)=>item.task.status==='queued'||item.task.status==='running'
const unadopted=(item:LiveRequest)=>item.task.status==='succeeded'&&!!item.candidate&&item.published_revision===null
const pollMs=3000
function previewKey(request:PreviewInput){
 // ArticlePreviewRequest persists an omitted validation selection as an empty list.
 return canonicalJson(request.schema_version===4?{...request,validation_source_ids:request.validation_source_ids??[]}:request)
}
export default function WritingLive({projectId,manuscriptId,version,onPublished,active=true,customerSci,customerThesis=false,initialWritingRequest,initialParagraph,onNeedSource}:Props){
 const returnConsumed=useRef(false),[placeGone,setPlaceGone]=useState(false)
 const {t}=useI18n(),op=useWritingOperation({projectId,manuscriptId,versionId:version.id,operation:'controlled-writing'}),base=`${manuscriptBase(projectId)}/${encodeURIComponent(manuscriptId)}`
 const school=!!version.snapshot.thesis_context,chapters=version.snapshot.thesis_context?.chapters??[],targets=school?chapters.filter(c=>writableSchoolPurpose(c.purpose)).map(c=>({id:c.id,title:c.title})):sectionIds.filter(id=>id!=='references').map(id=>({id,title:sectionLabels[id]}))
 const paperPlan=version.snapshot.paper_plan,frozenKeywords=version.snapshot.keywords??paperPlan?.keywords??[],selectedSourceIds=plannedWritingSources(version.snapshot)
 const legacyInitial:LegacyPreviewInput={schema_version:school?3:2,base_revision:version.revision,mode:'full_draft',target_section:null,output_language:version.snapshot.output_language,instructions:'',keywords:[],acknowledgements:'',selected_source_ids:selectedSourceIds,selected_evidence_ids:[]}
 const sciCustomer=customerSci!==undefined,customer=sciCustomer||customerThesis
 const focusedRequest=customer&&!initialParagraph?initialWritingRequest:undefined
 // Every customer manuscript, including an old one without a paper plan, hides IDs, hashes and raw codes (B03 task 8).
 const evidence=frozenWritingEvidence(version.snapshot)
 const initialArticleType=version.snapshot.article_type??(paperPlan?.kind!=='thesis'?paperPlan?.kind:undefined)??customerSci?.article_type??'research'
 // A customer review starts with every excerpt of the selected literature; the customer may untick any of them.
 const initialEvidence=customer&&initialArticleType==='narrative_review'?evidence.map(e=>e.id):[]
 const articleInitial:ArticlePreviewInput={schema_version:4,base_revision:version.revision,document_kind:school?'thesis':'sci',article_type:initialArticleType,mode:'full_draft',target_section:null,target_sections:[],target_paragraph_ids:[],paragraph_plan:[],brief_limits:null,output_language:version.snapshot.output_language,instructions:'',keywords:paperPlan?frozenKeywords:customer?(version.snapshot.keywords??customerSci?.keywords??[]):[],acknowledgements:'',selected_source_ids:selectedSourceIds,selected_evidence_ids:initialEvidence}
 const articleOnly=!school&&(!!paperPlan||sciCustomer||!!version.snapshot.article_type&&version.snapshot.article_type!=='research')
 const [draft,setDraft]=useResearchDraft(projectId,`manuscript-writing-live${customerThesis?'-thesis-customer':sciCustomer?'-sci-customer':''}:${manuscriptId}:${version.id}`,()=>({input:(articleOnly?articleInitial:legacyInitial) as PreviewInput,chapterDrafts:{} as Record<string,PreviewInput>,protocolDrafts:{} as Record<string,PreviewInput>}))
 const {input,chapterDrafts,protocolDrafts}=draft
 const field=<K extends keyof typeof draft>(key:K)=>(next:typeof draft[K]|((old:typeof draft[K])=>typeof draft[K]))=>setDraft(old=>({...old,[key]:typeof next==='function'?(next as (value:typeof draft[K])=>typeof draft[K])(old[key]):next}))
 const setInput=field('input'),setChapterDrafts=field('chapterDrafts'),setProtocolDrafts=field('protocolDrafts')
 const [bundle,setBundle]=useState<Bundle|null>(null),[verified,setVerified]=useState(''),[auth,setAuth]=useState<Authorization|null>(null),[logical,setLogical]=useState(''),[items,setItems]=useState<LiveRequest[]>([]),[selected,setSelected]=useState<LiveRequest|null>(null),[saved,setSaved]=useState<Bundle[]>([]),[enabled,setEnabled]=useState(false),[executeConfirmed,setExecuteConfirmed]=useState(false)
 const [visitedCandidates,setVisitedCandidates]=useState<string[]>([]),w1Input=input.schema_version===4?input as ArticlePreviewInput:null
 const [recovery,setRecovery]=useState<TaskWorkspace|null>(null)
 const [capabilities,setCapabilities]=useState<WritingCapabilities|null>(null),[edited,setEdited]=useState(false),autoPreviewed=useRef(false),pollOp=useWritingOperation()
 const previewsUrl=`${base}/writing-previews`,requestsUrl=`${base}/writing-requests`
 const previewList=(v:unknown):v is{items:Bundle[];capabilities:WritingCapabilities}=>object(v)&&validCapabilities(v.capabilities)&&listOf((x):x is Bundle=>validBundle(x,projectId,manuscriptId))(v)
 const requestList=(v:unknown):v is{items:LiveRequest[]}=>object(v)&&Array.isArray(v.items)&&v.items.every(x=>object(x)&&(x.schema_version===2?validLiveRequest(x,projectId,manuscriptId):x.schema_version===undefined||x.schema_version===1))
 const visibleRequests=(list:LiveRequest[])=>list.filter(x=>x.schema_version===2&&!x.input.draft_advice&&(!customer||x.base_revision===version.revision)&&(!customerThesis||x.input.schema_version===3))
 const liveKey=(value:PreviewInput)=>[value.schema_version,value.schema_version===4?value.article_type:'legacy',value.mode,value.target_section??''].join(':')
 const hasDraft=(value:PreviewInput)=>!!value.instructions||JSON.stringify(value.keywords)!==JSON.stringify(value.schema_version===4?articleInitial.keywords:[])||!!value.acknowledgements||JSON.stringify(value.selected_source_ids)!==JSON.stringify(selectedSourceIds)||JSON.stringify(value.selected_evidence_ids)!==JSON.stringify(value.schema_version===4?articleInitial.selected_evidence_ids:[])||(value.schema_version===4&&(value.article_type!==articleInitial.article_type||!!value.brief_limits||(value.target_sections?.length??0)>0||(value.target_paragraph_ids?.length??0)>0||(value.paragraph_plan?.length??0)>0))
 // A customer's writing draft is kept in this tab, so leaving never asks; a running or unknown submission still
 // guards through useWritingOperation. Internal roles keep the unsaved-draft prompt.
 useManuscriptDraft(!customer&&(hasDraft(input)||Object.values(chapterDrafts).some(hasDraft)))
 const chooseCandidate=(value:LiveRequest)=>{setSelected(value);setVisitedCandidates(old=>old.includes(value.id)?old:[...old,value.id])}
 const verify=useCallback((hash:string)=>setVerified(hash),[])
 function invalidate(){setBundle(null);setVerified('');setLogical('');setExecuteConfirmed(false);if(customer)setEdited(true)}
 function change(patch:Partial<PreviewInput>){const next={...input,...patch};if(next.schema_version===4&&patch.selected_source_ids)next.validation_source_ids=next.validation_source_ids?.filter(id=>patch.selected_source_ids!.includes(id));if(liveKey(next)!==liveKey(input)){setChapterDrafts(drafts=>({...drafts,[liveKey(input)]:input}));setInput(chapterDrafts[liveKey(next)]??next)}else setInput(next);invalidate()}
 function enableArticle(next:boolean){
  setProtocolDrafts(saved=>({...saved,[input.schema_version]:input}));setChapterDrafts(saved=>({...saved,[liveKey(input)]:input}))

  setInput(protocolDrafts[next?4:school?3:2]??(next?articleInitial:legacyInitial));invalidate()
 }
 // Returns true when it found the writing request whose submission result was unknown.
 const exactRequest=(v:unknown):v is LiveRequest=>validLiveRequest(v,projectId,manuscriptId)&&!v.input.draft_advice&&v.id===focusedRequest&&v.base_revision===version.revision
 async function refresh(prepare=false){
  if(focusedRequest){
   const item=await op.run(requestsUrl+'/'+encodeURIComponent(focusedRequest),exactRequest)
   if(item){setItems([item]);chooseCandidate(item)}
   return !!item
  }
  const previews=await op.run(previewsUrl,previewList);if(!previews)return false
  const writingPreviews=previews.items.filter(item=>!item.request_json.draft_advice)
  setSaved(writingPreviews);setEnabled(previews.capabilities.real_calls_enabled);setCapabilities(previews.capabilities)
  const requests=await op.run(requestsUrl,requestList);if(!requests)return false
  const visible=visibleRequests(requests.items);setItems(visible)
  let found:LiveRequest|undefined
  if(op.pending?.url===requestsUrl){try{const body=JSON.parse(op.pending.body) as {bundle_id?:string;authorization_id?:string;logical_task_id?:string};found=requests.items.find(item=>item.schema_version===2&&validLiveRequest(item,projectId,manuscriptId)&&item.base_revision===version.revision&&requestUsesGroup(item,{bundle_id:body.bundle_id??'',authorization_id:body.authorization_id??'',logical_task_id:body.logical_task_id??''}));if(found)op.resolvePending()}catch{}}
  if(customer){
   // Coming back to a paragraph (B03 task 7) reopens the request named in the address, once.
   let returnTo:LiveRequest|undefined
   if(initialWritingRequest&&!returnConsumed.current){returnConsumed.current=true;returnTo=visible.find(x=>x.id===initialWritingRequest);if(!returnTo)setPlaceGone(true)}
   // Follow the found or still running request so its result opens by itself; otherwise reopen the newest finished
   // draft of this version that is not adopted yet, so coming back continues the check instead of offering a new fee.
   const follow=found?visible.find(x=>x.id===found.id):returnTo??(!selected?visible.find(inProgress)??visible.find(unadopted):undefined)
   if(follow)chooseCandidate(follow)
   if(prepare)await prepareCustomerPreview(writingPreviews,previews.capabilities.real_calls_enabled)
  }
  return !!found
 }
 const previewRequest=()=>paperPlan?{...input,keywords:school?[]:frozenKeywords}:input
 // Entering the customer writing view prepares the preview once (no model call, no cost); an identical one is reused.
 async function prepareCustomerPreview(list:Bundle[],callsEnabled:boolean){
  const wanted=previewKey(previewRequest())
  const same=list.find(b=>b.base_version_id===version.id&&previewKey(b.request_json)===wanted)
  if(same){setBundle(same);setVerified('');setEdited(false);return}
  if(!callsEnabled||op.pending||autoPreviewed.current)return
  autoPreviewed.current=true
  await preview()
 }
 // This read belongs to the parent project/manuscript/version key.
 // oxlint-disable-next-line react/set-state-in-effect, react-hooks/exhaustive-deps
 useEffect(()=>{if(active)void refresh(true)},[active,focusedRequest])
 async function poll(id:string){
  if(focusedRequest){
   const item=await pollOp.run(requestsUrl+'/'+encodeURIComponent(focusedRequest),exactRequest)
   if(item){setItems([item]);setSelected(item)}
   return
  }
  const requests=await pollOp.run(requestsUrl,requestList);if(!requests)return;const visible=visibleRequests(requests.items);setItems(visible);const next=visible.find(x=>x.id===id);if(next)setSelected(next)}
 const pollingId=customer&&active&&op.valid&&selected&&inProgress(selected)?selected.id:''
 // Customers wait on the page: the selected queued or running request is read every 3 seconds until it ends.
 // oxlint-disable-next-line react-hooks/exhaustive-deps
 useEffect(()=>{if(!pollingId)return;const timer=window.setInterval(()=>{void poll(pollingId)},pollMs);return()=>window.clearInterval(timer)},[pollingId])
 async function loadRecovery(item:LiveRequest){
  const workspace=await op.run(`/api/v1/tasks/${encodeURIComponent(item.task.id)}/workspace`,(value):value is TaskWorkspace=>isWorkspace(value,projectId,item.task.id)&&value.task.task_type==='manuscript_writing')
  if(!workspace)return
  if(workspace.task.revision!==item.task.revision)await refresh()
  setRecovery(workspace)
 }
 async function preview(){const request=previewRequest();const result=await op.run(previewsUrl,(v):v is Bundle=>validBundle(v,projectId,manuscriptId),request);if(result){setBundle(result);setVerified('');setEdited(false);setSaved(old=>[result,...old.filter(b=>b.id!==result.id)]);setLogical('');setExecuteConfirmed(false)}}
 const customerSubmit=useCustomerWritingSubmit({op,projectId,manuscriptId,items,onRequest:result=>{setItems(old=>[result,...old.filter(x=>x.id!==result.id)]);chooseCandidate(result)},onRefresh:()=>refresh()})
 const unknownSubmit=customer&&!!op.pending&&!op.busy&&(op.pending.url===authorizationsUrl(projectId)||op.pending.url===requestsUrl)
 const previewUnknown=customer&&!!op.pending&&!op.busy&&op.pending.url===previewsUrl
 const generated=items.some(item=>!!item.candidate||item.task.status==='succeeded')
 function checkResult(){if(previewUnknown)void preview();else void customerSubmit.checkResult()}
 // A request of this version is still being generated: a second one would be charged again, so the button waits.
 const generating=items.some(inProgress)
 const alreadyRequested=!!bundle&&!!auth&&!!logical&&items.some(item=>requestUsesGroup(item,{bundle_id:bundle.id,authorization_id:auth.id,logical_task_id:logical}))
 const matching=auth?.status==='active'&&bundle&&verified===bundle.bundle_sha256?auth.manifest.tasks.filter(g=>g.bundles.some(b=>b.bundle_id===bundle.id&&b.bundle_sha256===bundle.bundle_sha256)):[],ready=!!bundle&&!!auth&&!!matching&&matching.some(g=>g.logical_task_id===logical)&&executeConfirmed&&enabled&&!alreadyRequested&&!op.pending
 async function execute(recover=false){
  const url=`${base}/writing-requests`
  let body
  if(recover){
   if(!op.valid||op.pending?.url!==url)return
   try{body=JSON.parse(op.pending.body) as unknown}catch{op.setError('提交结果待核对，原请求与当前输入不一致。');return}
  }else{
   if(!ready||!bundle||!auth)return
   body={schema_version:2,bundle_id:bundle.id,bundle_sha256:bundle.bundle_sha256,authorization_id:auth.id,logical_task_id:logical}
  }
  const result=await op.run(url,(v):v is LiveRequest=>validLiveRequest(v,projectId,manuscriptId),body)
  setExecuteConfirmed(false)
  if(result){setItems(old=>[result,...old.filter(x=>x.id!==result.id)]);chooseCandidate(result)}
 }
 const writingSources=paperPlan?.kind==='narrative_review'?version.snapshot.sources.filter(source=>selectedSourceIds.includes(source.id)||source.kind!=='analysis_run'&&['methods','literature'].includes(source.role)):version.snapshot.sources
 const recordText=(item:LiveRequest)=><p>{item.task.error_code&&t(apiError({code:item.task.error_code},'写作任务失败，请查看任务详情。'))} {item.task.reason_code&&t(apiError({code:item.task.reason_code},'任务状态已更新，请查看任务详情。'))}</p>
 return <section className="manuscript-panel manuscript-review writing-live" aria-label={t(customer?'写作工作区':'受控写作工作区')}><h3>{t(focusedRequest?'正文初稿与复核':customer?'生成正文':'受控写作与人工审核')}</h3>{!focusedRequest&&<>{!customer&&<><p>{t(enabled?'服务端真实调用门禁已配置；账户可用性尚未验证。':'真实调用默认关闭；预览不执行模型调用。')}</p><p>{t(auth?'已明确选择授权':'尚未授权')}</p></>}
   {paperPlan&&<PaperPlanSummary plan={paperPlan} heading="本版写作要求和图表材料"/>}
  {!customer&&op.pending&&<p role="status">{t('提交结果待核对，请刷新受控写作记录；模型提交未知时不得自动重发。')}</p>}<fieldset disabled={op.busy||!op.valid||!!op.pending}><legend>{t(customer?'本次写作材料':'仅外发明确选择的材料')}</legend>{!customer&&!paperPlan&&<label><input type="checkbox" checked={!!w1Input} disabled={articleOnly} onChange={e=>enableArticle(e.target.checked)}/>{t('文章类型与范围编辑')}</label>}
  {w1Input&&<ArticleWritingFields input={w1Input} snapshot={version.snapshot} onChange={change} customerSci={sciCustomer}/>}
  {!w1Input&&<><label>{t(customer?'写作方式':'受控写作方式')}<select value={input.mode} onChange={e=>change({mode:e.target.value as PreviewInput['mode'],target_section:e.target.value==='full_draft'?null:school?targets[0]?.id??null:'discussion',keywords:!school&&e.target.value==='rewrite_section'?version.snapshot.keywords??[]:[],acknowledgements:!school&&e.target.value==='rewrite_section'?version.snapshot.acknowledgements??'':''})}><option value="full_draft">{t(school?'学校章节初稿':'完整七部分初稿')}</option>{version.snapshot.sections&&<option value="rewrite_section">{t('指定章节重写')}</option>}</select></label>{input.mode==='rewrite_section'&&<label>{t('重写目标章节')}<select value={input.target_section??''} onChange={e=>change({target_section:e.target.value as PreviewInput['target_section']})}>{targets.map(c=><option key={c.id} value={c.id}>{school?c.title:t(c.title)}</option>)}</select></label>}</>}
  {school&&<section aria-label={t(customer?'本次可生成的章节':'冻结学校章节')}><p>{t(customer?'题名沿用你保存的论文题目；致谢等章节不会改写。':'题名由用户冻结；仅科学正文用途可生成，其他章节保持保护。')}</p>{chapters.map(c=><p key={c.id}>{!customer&&<>{c.id} · </>}{c.title} · {customer?t(c.output_language==='zh-CN'?'中文':'英文'):c.output_language} · {customer?t(purposeLabels[c.purpose]):c.purpose} · {t(writableSchoolPurpose(c.purpose)?'可生成':customer?'保持原文':'受保护')}</p>)}</section>}<p>{t('稿件输出语言')} {customer?t(input.output_language==='zh-CN'?'中文':'英文'):input.output_language}</p><label>{t(customer?'本次写作要求':'本次受控写作要求')}<textarea value={input.instructions} maxLength={6000} onChange={e=>change({instructions:e.target.value})}/></label>{input.mode==='full_draft'&&!school&&<>{!paperPlan&&<label>{t(customer?'写作关键词（每行一项）':'受控写作关键词（每行一项）')}<textarea value={input.keywords.join('\n')} onChange={e=>change({keywords:e.target.value.split('\n')})}/></label>}<label>{t(customer?'致谢':'受控写作致谢')}<textarea value={input.acknowledgements} onChange={e=>change({acknowledgements:e.target.value})}/></label></>}
  {customer&&<p className="muted">{t(w1Input?.article_type==='narrative_review'?'请从已核验的引用中明确选择证据摘录。':'请选择支撑结果的固定计算输出或已绑定到用户结果的来源，并核对所选图表与方法。')}</p>}{writingSources.map(s=><label key={s.id}><input type="checkbox" checked={input.selected_source_ids.includes(s.id)} onChange={e=>change({selected_source_ids:e.target.checked?[...input.selected_source_ids,s.id]:input.selected_source_ids.filter(id=>id!==s.id)})}/>{s.label} · {protocolLabel(sourceKinds,s.kind,'未知类型')}{!customer&&' · '+s.sha256}</label>)}{evidence.map(e=><label key={e.id}><input type="checkbox" checked={input.selected_evidence_ids.includes(e.id)} onChange={ev=>change({selected_evidence_ids:ev.target.checked?[...input.selected_evidence_ids,e.id]:input.selected_evidence_ids.filter(id=>id!==e.id)})}/>{e.quote}</label>)}{!customer&&<><button type="button" onClick={()=>void preview()}>{t('冻结完整外发预览')}</button><button type="button" onClick={()=>void refresh()}>{t('刷新受控写作记录')}</button><label>{t('选择已冻结预览')}<select value={bundle?.id??''} onChange={e=>{const selectedBundle=saved.find(b=>b.id===e.target.value)??null;setBundle(selectedBundle);setVerified('');setLogical('');setExecuteConfirmed(false);if(selectedBundle){setChapterDrafts(drafts=>({...drafts,[liveKey(input)]:input}));setInput(selectedBundle.request_json)}}}><option value="">{t('尚未选择')}</option>{saved.filter(b=>b.request_json.base_revision===version.revision&&(!articleOnly||b.request_json.schema_version===4)).map(b=><option key={b.id} value={b.id}>{b.id} · {b.request_json.schema_version===4&&b.request_json.mode==='full_draft'?t('完整文章初稿'):protocolLabel(writingModes,b.request_json.mode)} · {b.bundle_sha256}</option>)}</select></label></>}</fieldset>
  {customer?<CustomerWritingConfirm key={bundle?.id??'none'} bundle={op.valid?bundle:null} version={version} capabilities={capabilities} customerThesis={customerThesis} generated={generated} generating={generating} edited={edited} unknown={unknownSubmit} previewUnknown={previewUnknown} busy={op.busy||!op.valid} onPreview={()=>void preview()} onSubmit={customerSubmit.submit} onCheckResult={checkResult}/>:<>{op.pending?.url.endsWith('/writing-previews')&&<button type="button" disabled={op.busy||!op.valid} onClick={()=>void preview()}>{t('使用原预览请求重试')}</button>}{op.pending?.url===`${base}/writing-requests`&&<button type="button" disabled={op.busy||!op.valid||!enabled} onClick={()=>void execute(true)}>{t('使用原写作请求重试')}</button>}<button type="button" disabled={op.busy||!op.valid} onClick={()=>void refresh()}>{t('核对受控写作记录')}</button>
  {bundle&&op.valid&&<WritingBundlePreview key={bundle.id} bundle={bundle} onVerified={verify}/>} {op.valid&&<WritingAuthorization projectId={projectId} onSelect={value=>{setAuth(value);setLogical('');setExecuteConfirmed(false)}}/>}<fieldset disabled={op.busy||!op.valid}><legend>{t('明确执行一个已授权任务')}</legend><label>{t('授权逻辑任务')}<select value={logical} onChange={e=>{setLogical(e.target.value);setExecuteConfirmed(false)}}><option value="">{t('尚未选择')}</option>{matching&&matching.map(g=><option key={g.logical_task_id} value={g.logical_task_id}>{g.logical_task_id}</option>)}</select></label><label><input type="checkbox" checked={executeConfirmed} disabled={!logical||!enabled} onChange={e=>setExecuteConfirmed(e.target.checked)}/>{t('我确认执行当前精确 SHA；失败或未知不会自动重发。')}</label><button type="button" disabled={!ready} onClick={()=>void execute()}>{t('提交已授权写作')}</button></fieldset></>}</>}{op.error&&(!unknownSubmit||op.error===resultNotFound)&&<p role="alert">{t(op.error)}{focusedRequest&&<button type="button" disabled={op.busy} onClick={()=>void refresh()}>{t('重新读取任务')}</button>}</p>}{focusedRequest&&pollOp.error&&<p role="status">{t(pollOp.error)}</p>}{placeGone&&<p role="status" className="warning-panel">{t('原位置已不可用，已回到逐段核对。')}</p>}{op.valid&&items.map((item,index)=><article key={item.id}><h4>{customer?t('写作记录 {number}',{number:index+1}):item.id} · {taskStatusLabel(item.task.status)}</h4>{recordText(item)}{customer?!focusedRequest&&item.candidate&&<button type="button" onClick={()=>chooseCandidate(item)}>{t('继续核对这份正文')}</button>:<button type="button" onClick={()=>chooseCandidate(item)}>{t('审核此原始候选')}</button>} {customer&&['failed','waiting_confirmation'].includes(item.task.status)&&(recovery?.task.id===item.task.id&&recovery.task.revision===item.task.revision?<TaskPendingAction workspace={recovery} active={active} blocked={op.busy||!!op.pending} onChanged={()=>{setRecovery(null);void refresh()}}/>:<button type="button" disabled={op.busy||!!op.pending} onClick={()=>void loadRecovery(item)}>{t('核对原写作任务')}</button>)} {!customer&&<a href={`#project=${encodeURIComponent(projectId)}&section=tasks&task=${encodeURIComponent(item.task.id)}`}>{t('查看写作任务')}</a>}</article>)}{op.valid&&items.filter(item=>visitedCandidates.includes(item.id)).map(item=><div key={item.id} hidden={selected?.id!==item.id}>{customer&&!item.candidate?(inProgress(item)&&<p role="status">{t('正在生成正文，完成后会自动打开核对。')}</p>):<WritingScienceReview key={`${item.id}:${item.candidate?.writing_provenance?.raw_output_sha256??''}`} projectId={projectId} manuscriptId={manuscriptId} request={item} customerSci={customer} customerThesis={customerThesis} autoLoad={customer} baseSavedAt={version.created_at} onPublished={onPublished}
   initialParagraph={customer&&item.id===initialWritingRequest?initialParagraph:undefined}
   onNeedSource={customer&&onNeedSource?(kind,paragraph,location)=>onNeedSource(kind,{writingRequest:item.id,paragraph},location):undefined}/>}</div>)}
 </section>
}
