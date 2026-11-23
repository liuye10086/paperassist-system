import SchoolChanges,{SchoolVersionOrigin,SchoolOpinionHandoff} from './SchoolChanges'
import {parsedMaterialLabel} from '../../shared/parsedMaterialLabel'
import ThesisChapterFields,{type TemplateTripChapter} from './ThesisChapterFields'
import {validThesisInput,type ChapterMapping,type SchoolPurpose,type ThesisReadiness} from './thesisTypes'
import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { apiError, safeError, useI18n, type Locale } from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { taskRequest, TaskRequestError } from '../tasks/taskApi'
import { isTask, isWorkspace, sameInputVersion, type TaskView, type TaskWorkspace } from '../tasks/taskTypes'
import { useDocumentVisible } from '../tasks/useDocumentVisible'
import ManuscriptPreview from './ManuscriptPreview'
import ManuscriptExports from './ManuscriptExports'
import FigureLanguagePanel from './FigureLanguagePanel'
import ManuscriptWriting from './ManuscriptWriting'
import WritingLive,{type NeedSource} from './WritingLive'
import {isLegacySciSettings,legacySciResult,type SciSettings} from '../customer/sciProjectSettings'
import WritingMaterialsPreview from './WritingMaterialsPreview'
import ManuscriptReview from './ManuscriptReview'
import { emptyInput, manuscriptBase, methodFields, methodLabels, roleLabels, sourceKey, validCandidates, validInput, validManuscript, validSnapshot, type Candidates, type Manuscript, type ManuscriptInput, type ManuscriptVersion, type MethodField, type Snapshot, type SourceCandidate, type SourceRole } from './manuscriptTypes'
import type {ManuscriptView} from '../projects/manuscriptViews'
import {ManuscriptDraftProvider} from './ManuscriptDraftProvider'
import useDraftLeaveGuard, {type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import useResearchDraft from '../research-results/useResearchDraft'
import './manuscripts.css'
import {useAnalysisWritingTransfer} from './analysisWritingTransfer'
import {mergeAnalysisSelection,type AnalysisSelection} from './manuscriptTypes'
import PaperPlanSummary from './PaperPlanSummary'
import PaperDraftComposer from './PaperDraftComposer'
import {plannedThesisInput,supplementaryInput} from './paperPlan'
import OverwriteConfirm from './OverwriteConfirm'
import VersionLabel from '../../shared/VersionLabel'
import {isAdoptedSnapshot} from './manuscriptTypes'
const mostRecentFirst = (a: Manuscript, b: Manuscript) => Date.parse(b.updated_at) - Date.parse(a.updated_at)
function snapshotFigures(snapshot:Snapshot){return snapshot.results_groups.flatMap(g=>g.figures.map(f=>({id:f.id,label:f.title,parents:f.source_ids})))}
type MaterialDraft={input:ManuscriptInput;cleanInput:string;editing:string|null;editingAsReview:boolean;materialsPage:string|null;conflictField:MethodField;conflictValues:string;conflictNote:string
 /** Thesis chapter titles of the confirmation the chapter mappings were made for, to carry them to a new template by title. */
 chapterTitles?:{confirmation_id:string;titles:Record<string,string>}}
const chapterTitlesOf=(readiness:ThesisReadiness)=>({confirmation_id:readiness.confirmation_id??'',titles:Object.fromEntries(readiness.chapters.map(chapter=>[chapter.id,chapter.title]))})
type Props={onOpenGenerated?:(id:string,revision:number,writingRequest:string)=>void;onFindLiterature?:()=>void;customerSci?:{settings:SciSettings|null;wordOnly:boolean};customerThesis?:{wordOnly:boolean};analysisSelection?:AnalysisSelection;view?:ManuscriptView;onViewChange?:(view:ManuscriptView)=>void;onSelectVersion?:(id:string,revision:number,replace?:boolean)=>void;onAdopted?:(id:string,revision:number)=>void;adoptedNotice?:boolean;openLatest?:boolean;onAutoWordStarted?:()=>void;initialWritingRequest?:string;initialParagraph?:string;onNeedSource?:NeedSource;registerLeaveGuard?:RegisterLeaveGuard;initialManuscript?:string;initialRevision?:number;projectType?:'sci'|'thesis';projectId:string;researchTopic:string;outputLanguage:Locale;active:boolean;onOpenTask?:(id:string)=>void;onOpenLiterature?:()=>void;onOpenSchoolTemplate?:(chapter?:TemplateTripChapter)=>void;onOpenRequirements?:()=>void;onOpenMaterials?:()=>void;onStartReview?:(id:string,revision:number)=>void
 /** Back from the school template page (B04 task 8): the chapter to focus, `id: null` for the chapter panel. */
 initialChapter?:{id:string|null};onChapterFocused?:()=>void
 /** From the template change preview (B04 task 9): the confirmed template the migration page preselects. */
 initialTarget?:string
 /** Word page (B04 task 11): opens the migration of a version refused for its previous template. */
 onOpenMigration?:(manuscriptId:string,revision:number,confirmationId:string)=>void}
export default function ProjectManuscripts(props:Props){
 const [visited,setVisited]=useState(props.active)
 if(props.active&&!visited)setVisited(true)
 return <div hidden={!props.active}>{(visited||props.active)&&<Workbench key={props.projectId} {...props}/>}</div>
}
function Workbench({onOpenGenerated,onFindLiterature,customerSci,customerThesis,analysisSelection,initialManuscript,initialRevision,projectType='sci',projectId,researchTopic,outputLanguage,onOpenTask,onOpenLiterature,onOpenSchoolTemplate,onOpenRequirements,onOpenMaterials,active,view,onViewChange,onSelectVersion,registerLeaveGuard,onStartReview,onAdopted,adoptedNotice=false,openLatest=false,onAutoWordStarted,initialWritingRequest,initialParagraph,onNeedSource,initialChapter,onChapterFocused,initialTarget,onOpenMigration}:Props){
 const {t,locale}=useI18n(),visible=useDocumentVisible()
 const isCustomerSci=customerSci!==undefined
 const customer=!!(customerSci||customerThesis),wordOnly=!!(customerSci??customerThesis)?.wordOnly
 const initialInput=():ManuscriptInput=>{
  const result=customerSci?.settings?.article_type==='research'?legacySciResult(customerSci.settings):''
  return {...emptyInput(researchTopic,outputLanguage),...(result?{reported_result:{text:result,source_ids:[]}}:{})}
 }
 // Material edits are kept in this tab's session draft, keyed by the manuscript version in the address
 // (`new` before one is chosen), so leaving and returning restores them without a discard prompt.
 const draftKey=`manuscript-materials:${initialManuscript??'new'}:${initialRevision??0}`
 const initialDraft=():MaterialDraft=>{const next=initialInput();return {input:next,cleanInput:JSON.stringify(next),editing:null,editingAsReview:false,materialsPage:null,conflictField:'procedures',conflictValues:'',conflictNote:''}}
 const [draft,setDraft]=useResearchDraft<MaterialDraft>(projectId,draftKey,initialDraft)
 const {input,editing,editingAsReview,materialsPage,cleanInput,conflictField,conflictValues,conflictNote}=draft
 function field<K extends keyof MaterialDraft>(key:K){return (next:MaterialDraft[K]|((old:MaterialDraft[K])=>MaterialDraft[K]))=>setDraft(old=>({...old,[key]:typeof next==='function'?(next as (value:MaterialDraft[K])=>MaterialDraft[K])(old[key]):next}))}
 const setInput=field('input'),setEditing=field('editing'),setEditingAsReview=field('editingAsReview'),setMaterialsPage=field('materialsPage'),setCleanInput=field('cleanInput'),setConflictField=field('conflictField'),setConflictValues=field('conflictValues'),setConflictNote=field('conflictNote')
 // The address can move to another version while the draft is open; carry the draft to the new key.
 const storedKey=useRef(draftKey),writeDraft=useRef(setDraft)
 useLayoutEffect(()=>{writeDraft.current=setDraft;if(storedKey.current===draftKey)return;storedKey.current=draftKey;setDraft(current=>current)})
 const [candidates,setCandidates]=useState<Candidates|null>(null),[history,setHistory]=useState<Manuscript[]>([]),[preview,setPreview]=useState<Snapshot|null>(null),[discoveredFigures,setDiscoveredFigures]=useState<{id:string;label:string;parents:string[]}[]>([])
 const [selected,setSelected]=useState<{id:string;revision:number}|null>(()=>initialManuscript&&initialRevision?{id:initialManuscript,revision:initialRevision}:null)
 const [error,setError]=useState(''),[loadError,setLoadError]=useState(''),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[attempt,setAttempt]=useState(0),[sessionValid,setSessionValid]=useState(true)
 const [visitedVersions,setVisitedVersions]=useState<string[]>([]),[visitedTasks,setVisitedTasks]=useState<string[]>([]),[uncertain,setUncertain]=useState(false)
 // Customer saves: the revision just saved (and whether its earlier body must be generated again), and the
 // revision whose overwrite is awaiting confirmation.
 const [saved,setSaved]=useState<{revision:number;rewrite:boolean}|null>(null),[confirming,setConfirming]=useState<number|null>(null)
 const refreshConflictBase=useRef(false)
 const transfer=useAnalysisWritingTransfer(),incomingAnalysis=analysisSelection??transfer?.pending
 const [analysisReceived,setAnalysisReceived]=useState<AnalysisSelection|null>(null)
 const appliedAnalysis=useRef<AnalysisSelection|null>(null)
 const layered=view!==undefined
 const preparationSelection=customer&&(view==='writing'||view==='exports')?selected:undefined
 const materialDirty=JSON.stringify(input)!==cleanInput||!!conflictValues||!!conflictNote
 // Persisted material fields no longer count as unsaved; only a running or unconfirmed save does.
 useDraftLeaveGuard(registerLeaveGuard,uncertain,busy)
 const [receivedSelection,setReceivedSelection]=useState(`${initialManuscript??''}:${initialRevision??''}`)
 const incomingSelection=`${initialManuscript??''}:${initialRevision??''}`
 if(receivedSelection!==incomingSelection){
  setReceivedSelection(incomingSelection)
  if(initialManuscript&&initialRevision)setSelected({id:initialManuscript,revision:initialRevision})
  else if(customer&&onSelectVersion)setSelected(null)
 }
 function openVersion(id:string,revision:number){setSelected({id,revision});onSelectVersion?.(id,revision);onViewChange?.('body')}
 // Adopting a reviewed manuscript (B03): the caller opens the Word page of the version the server just published.
 function adopted(result:Manuscript){if(!onAdopted){refreshHistory(result);return}setUncertain(false);setHistory(old=>[result,...old.filter(m=>m.id!==result.id)]);onAdopted(result.id,result.current_revision)}
 // The adoption notice stays for this visit after the address drops its flag.
 const [showAdopted,setShowAdopted]=useState(adoptedNotice)
 if(adoptedNotice&&!showAdopted)setShowAdopted(true)
 function refreshHistory(result:Manuscript){setUncertain(false);setHistory(old=>[result,...old.filter(m=>m.id!==result.id)]);if(customer)openVersion(result.id,result.current_revision);else if(!layered)setSelected({id:result.id,revision:result.current_revision});setAttempt(a=>a+1)}
 const request=useRef<AbortController|null>(null),read=useRef<AbortController|null>(null),mounted=useRef(true),replay=useRef(new Map<string,string>())
 const lastPlanToken=useRef<string|undefined>(undefined)
 const base=manuscriptBase(projectId),school=projectType==='thesis'
 // Customers keep one manuscript (D2): saving again appends a version to the most recently updated one, and the
 // saved writing requirements stay in use. Internal roles still edit a chosen version outside the requirements.
 const planEditing=!customer&&!!editing
 const ordered=customer?[...history].sort(mostRecentFirst):history
 const overwriteTarget=customer?ordered.find(m=>m.id===editing)??ordered[0]:undefined
 const paperPlan=planEditing?undefined:candidates?.paper_plan
 const paperPlanUnavailable=!planEditing&&!!customerSci?.settings&&!isLegacySciSettings(customerSci.settings)&&!paperPlan
 const reviewArticle=planEditing||customer&&editing&&!paperPlan&&!customerSci?.settings?editingAsReview:(paperPlan?.kind??customerSci?.settings?.article_type)==='narrative_review'
 const plannedFiles=new Set(paperPlan?.materials.map(material=>material.selection.file_id))
 const manualItems=candidates?.items.filter(item=>!plannedFiles.has(item.file_id))??[]
 const readiness=candidates?.thesis??null
 const thesis=paperPlan&&readiness?plannedThesisInput(paperPlan,readiness,input.thesis):input.thesis
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;request.current?.abort();read.current?.abort()}},[])
 useEffect(()=>onApiSessionChanged(()=>{request.current?.abort();read.current?.abort();setSessionValid(false);setCandidates(null);setHistory([]);setPreview(null);setError('');setLoadError('');setBusy(false);setLoading(false)}),[])
 useEffect(()=>{if(!active||!visible||!sessionValid)return;let live=true;const controller=new AbortController();read.current=controller
 async function load(){try{const results=await Promise.allSettled([
 wordOnly?Promise.resolve(null):taskRequest(`${base}/candidates`,controller,(v):v is Candidates=>validCandidates(v,projectId),'稿件资料读取失败，请刷新。'),
 taskRequest(base,controller,(v):v is {items:Manuscript[]}=>!!v&&typeof v==='object'&&'items'in v&&Array.isArray(v.items)&&v.items.every(m=>validManuscript(m,projectId)),'稿件历史读取失败，请刷新。')])
 if(!live)return
 if(controller.signal.aborted){setLoadError('稿件资料读取失败，请刷新。');setLoading(false);return}
 const [sources,manuscripts]=results
 if(sources.status==='fulfilled'&&sources.value){
  const listed=sources.value
  if(lastPlanToken.current!==listed.paper_plan?.token){lastPlanToken.current=listed.paper_plan?.token;setPreview(null);setDiscoveredFigures([])}
  const pdfFiles=new Set(isCustomerSci?listed.items.filter(item=>item.kind==='original'&&/\.pdf$/i.test(item.label)).map(item=>item.file_id):[])
  setCandidates(pdfFiles.size?{...listed,items:listed.items.filter(item=>!pdfFiles.has(item.file_id))}:listed)
 }
 if(manuscripts.status==='fulfilled'){
  const roots=manuscripts.value.items
  setHistory(roots)
  if(refreshConflictBase.current){
   refreshConflictBase.current=false
   writeDraft.current(old=>{
    const updated=roots.find(root=>root.id===old.editing)??[...roots].sort(mostRecentFirst)[0]
    return updated?{...old,editing:updated.id,input:{...old.input,expected_revision:updated.current_revision}}:old
   })
  }
 }
 const failed=results.find(r=>r.status==='rejected');setLoadError(failed&&failed.status==='rejected'?safeError(failed.reason,'稿件资料读取失败，请刷新。'):'')
 }finally{if(live&&!controller.signal.aborted)setLoading(false)}}
 void load();return()=>{live=false;controller.abort()}},[base,projectId,visible,sessionValid,attempt,active,isCustomerSci,wordOnly])
 useEffect(()=>{
  if(!active||!visible||!sessionValid)return
  const preparing=history.some(m=>m.versions.some(v=>v.status==='pending'&&(preparationSelection===undefined||
   m.id===preparationSelection?.id&&m.current_revision===v.revision&&v.revision===preparationSelection.revision)))
  if(!preparing)return
  const timer=window.setTimeout(()=>setAttempt(value=>value+1),3000)
  return()=>window.clearTimeout(timer)
 },[active,visible,sessionValid,history,preparationSelection])
 // A Word page opened without a manuscript shows the current version of the most recently updated one, in place.
 const openedLatest=useRef(false),latest=openLatest&&!loading&&!selected?ordered[0]:undefined
 useEffect(()=>{if(!latest||openedLatest.current)return;openedLatest.current=true;setSelected({id:latest.id,revision:latest.current_revision});onSelectVersion?.(latest.id,latest.current_revision,true)},[latest,onSelectVersion])
 useEffect(()=>{if(!active||busy||!sessionValid||!incomingAnalysis||incomingAnalysis.project_id!==projectId||incomingAnalysis.project_type!==projectType||appliedAnalysis.current===incomingAnalysis)return;appliedAnalysis.current=incomingAnalysis;writeDraft.current(old=>({...old,input:mergeAnalysisSelection(old.input,incomingAnalysis)}));setPreview(null);setAnalysisReceived(incomingAnalysis)},[active,busy,sessionValid,incomingAnalysis,projectId,projectType])
 // A clean tab draft can predate a save in another view. Restore the server version on opening materials.
 const [backfilled,setBackfilled]=useState(false)
 if(customer&&!wordOnly&&!loading&&!backfilled&&overwriteTarget){
  setBackfilled(true)
  const current=overwriteTarget.versions.find(v=>v.revision===overwriteTarget.current_revision)
  if(!materialDirty&&current&&validInput(current.input)){
   const next=structuredClone({...current.input,expected_revision:overwriteTarget.current_revision})
   setDraft(old=>({...old,input:next,cleanInput:JSON.stringify(next),editing:overwriteTarget.id,editingAsReview:current.snapshot.article_type==='narrative_review'}))
   setDiscoveredFigures(snapshotFigures(current.snapshot))
  }
 }
 function edit(update:(previous:ManuscriptInput)=>ManuscriptInput){setInput(update);setPreview(null);setError('');setSaved(null)}
 function startNewManuscript(){
  if(busy||materialDirty&&!window.confirm(t('当前资料有未保存修改。放弃并另建稿件？')))return
  const next=initialInput();setEditing(null);edit(()=>next);setCleanInput(JSON.stringify(next));setConflictValues('');setConflictNote('');setDiscoveredFigures([]);setMaterialsPage(null);onViewChange?.('materials')
 }
 function sourceFigureIds(sourceId:string){return new Set([sourceId,...discoveredFigures.filter(figure=>figure.parents.includes(sourceId)).map(figure=>figure.id)])}
 function candidateLabel(source:SourceCandidate){
  return customer ? parsedMaterialLabel(source) ?? source.label : source.label
 }
 function toggleSource(item:SourceCandidate,checked:boolean){
  const removedFigures=checked?new Set<string>():sourceFigureIds(item.id)
  edit(old=>{const sources=checked?[...old.sources,{kind:item.kind,id:item.id,file_id:item.file_id,role:item.allowed_roles[0]}]:old.sources.filter(s=>sourceKey(s)!==sourceKey(item));return{...old,sources,...(old.reported_result&&!checked?{reported_result:{...old.reported_result,source_ids:old.reported_result.source_ids.filter(id=>id!==item.id)}}:{}),analysis_handoff_run_ids:old.analysis_handoff_run_ids?.filter(id=>sources.some(s=>s.kind==='analysis_run'&&s.id===id)),results_groups:old.results_groups.map(g=>({...g,analysis_run_ids:g.analysis_run_ids.filter(id=>checked||id!==item.id),figure_ids:g.figure_ids.filter(id=>!removedFigures.has(id))})),method_source_ids:Object.fromEntries(Object.entries(old.method_source_ids).map(([k,ids])=>[k,ids?.filter(id=>checked||id!==item.id)])),figure_notes:old.figure_notes.filter(n=>!removedFigures.has(n.figure_id))}})
 }
 function changeRole(item:SourceCandidate,role:SourceRole){
  const removedFigures=role==='image_observation'?new Set<string>():sourceFigureIds(item.id)
  edit(old=>({...old,...(old.reported_result&&role!=='user_results'?{reported_result:{...old.reported_result,source_ids:old.reported_result.source_ids.filter(id=>id!==item.id)}}:{}),sources:old.sources.map(s=>sourceKey(s)===sourceKey(item)?{...s,role}:s),results_groups:old.results_groups.map(g=>({...g,analysis_run_ids:role==='computed_results'?g.analysis_run_ids:g.analysis_run_ids.filter(id=>id!==item.id),figure_ids:g.figure_ids.filter(id=>!removedFigures.has(id))})),figure_notes:old.figure_notes.filter(n=>!removedFigures.has(n.figure_id))}))
 }
 function groupChange(id:string,update:(g:ManuscriptInput['results_groups'][number])=>ManuscriptInput['results_groups'][number]){edit(old=>({...old,results_groups:old.results_groups.map(g=>g.id===id?update(g):g)}))}
 function moveGroup(index:number,direction:number){edit(old=>{const groups=[...old.results_groups];[groups[index],groups[index+direction]]=[groups[index+direction],groups[index]];return{...old,results_groups:groups}})}
 const reportedText=input.reported_result?.text.trim()
 const reportedSources=input.reported_result?.source_ids.filter(id=>input.sources.some(s=>s.id===id&&s.role==='user_results'))??[]
 const legacyResultEntry=!paperPlan&&!paperPlanUnavailable&&!reviewArticle&&(!!customerThesis||!!customerSci?.settings&&isLegacySciSettings(customerSci.settings)||!!editing&&!!input.reported_result)
 const reportedResult=legacyResultEntry&&reportedText&&reportedSources.length?{text:reportedText,source_ids:reportedSources}:null
 // Whether the version about to be overwritten already has a generated body: an adopted snapshot, or any writing
 // request on this revision. An unreadable request list counts as possibly generated.
 async function generatedBefore(manuscript:Manuscript,controller:AbortController){
  const current=manuscript.versions.find(v=>v.revision===manuscript.current_revision)
  if(current&&isAdoptedSnapshot(current.snapshot,current.parent_version_id))return true
  try{
   const requests=await taskRequest(`${base}/${encodeURIComponent(manuscript.id)}/writing-requests`,controller,(v):v is {items:unknown[]}=>!!v&&typeof v==='object'&&'items'in v&&Array.isArray(v.items),'写作记录读取失败，请刷新。')
   return requests.items.some(item=>!!item&&typeof item==='object'&&'schema_version'in item&&item.schema_version===2&&'base_revision'in item&&item.base_revision===manuscript.current_revision)
  }catch{return true}
 }
 async function submit(kind:'preview'|'save',event?:FormEvent,overwriteConfirmed=false){event?.preventDefault();if(request.current||!sessionValid)return
 if(paperPlanUnavailable)return
 if(school&&(!readiness?.ready||!validThesisInput(thesis)||thesis.confirmation_id!==readiness.confirmation_id||thesis.profile_revision!==readiness.profile.revision||JSON.stringify(thesis.chapter_mappings.map(c=>c.chapter_id))!==JSON.stringify(readiness.chapters.map(c=>c.id)))){setMaterialsPage(paperPlan?'chapters':'sources');setError('请逐章明确内容用途并核对当前学校确认版本。');return}
 if(customerThesis&&reportedResult&&!thesis?.chapter_mappings.some(chapter=>chapter.result_group_ids.includes('reported-result'))){
  setMaterialsPage('sources');setError('请将用户提供的结果分配给一个结果章节。');return
 }
 const manual=paperPlan?supplementaryInput(input,plannedFiles,sourceFigureIds):input
 const payload={...manual}
 delete payload.reported_result
 delete payload.paper_plan_token
 payload.title=paperPlan?.title??input.title.trim()
 const target=customer?overwriteTarget:undefined
 if(kind==='save'&&target&&(editing!==target.id||input.expected_revision!==target.current_revision)){
  setDraft(old=>({...old,editing:target.id,input:{...old.input,expected_revision:target.current_revision}}))
  setConfirming(null)
  setError(editing?'这份稿件已有更新。你输入的内容仍在，请核对后再保存。':'这个项目已经有稿件。请覆盖之前的写作材料。')
  return
 }
 payload.expected_revision=editing?input.expected_revision:target?.current_revision??0
 if(paperPlan)payload.paper_plan_token=paperPlan.token
 if(thesis){
  const groupIds=new Set([...manual.results_groups.map(group=>group.id),...(paperPlan?.sections.filter(section=>section.purpose==='results').map(section=>section.id)??[])])
  payload.thesis={...thesis,chapter_mappings:thesis.chapter_mappings.map(chapter=>({...chapter,result_group_ids:chapter.result_group_ids.filter(id=>id==='reported-result'?!!reportedResult:!paperPlan||groupIds.has(id))}))}
 }
 if(reportedResult)payload.reported_result=reportedResult
 if(!validInput(payload)){setError('请填写稿件标题，检查分组与冲突资料。');return}
 const saveTarget=customer?target?.id:editing
 const url=kind==='preview'?`${base}/preview`:saveTarget?`${base}/${encodeURIComponent(saveTarget)}/versions`:base
 const body=JSON.stringify(payload),signature=`${url}:${body}`;if(!replay.current.has(signature))replay.current.set(signature,crypto.randomUUID())
 const controller=new AbortController();request.current=controller;setBusy(true);setError('');setSaved(null)
 const unconfirmed=customer?'写作材料保存结果未确认，请刷新后重试。':'事实稿请求未确认，请刷新后重试。'
 try{const init={method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':replay.current.get(signature)!},body}
 if(kind==='save'&&target&&!overwriteConfirmed&&await generatedBefore(target,controller)){if(mounted.current&&!controller.signal.aborted)setConfirming(target.current_revision);return}
 if(kind==='preview'){const result=await taskRequest(url,controller,(v):v is Snapshot=>validSnapshot(v,projectId),unconfirmed,init);if(mounted.current&&!controller.signal.aborted){setUncertain(false);setPreview(result);setDiscoveredFigures(snapshotFigures(result))}}
 else if(customer){const result=await taskRequest(url,controller,(v):v is Manuscript=>validManuscript(v,projectId),unconfirmed,init);if(mounted.current&&!controller.signal.aborted){
  // Keep showing what was just saved; the next overwrite starts from it.
  setUncertain(false);setHistory(old=>[result,...old.filter(m=>m.id!==result.id)]);openVersion(result.id,result.current_revision)
  const next={...input,expected_revision:result.current_revision};setEditing(result.id);setInput(next);setCleanInput(JSON.stringify(next))
  setPreview(null);setConfirming(null);setSaved({revision:result.current_revision,rewrite:overwriteConfirmed});setAttempt(a=>a+1)}}
 else{const result=await taskRequest(url,controller,(v):v is Manuscript=>validManuscript(v,projectId),'事实稿请求未确认，请刷新后重试。',init);if(mounted.current&&!controller.signal.aborted){setUncertain(false);setHistory(old=>[result,...old.filter(m=>m.id!==result.id)]);if(customer||paperPlan)openVersion(result.id,result.current_revision);else if(!layered)setSelected({id:result.id,revision:result.current_revision});const next=paperPlan?initialInput():{...input,expected_revision:result.current_revision};setEditing(paperPlan?null:result.id);setEditingAsReview(!paperPlan&&reviewArticle);setInput(next);setCleanInput(JSON.stringify(next));if(paperPlan){setMaterialsPage(null);setConflictValues('');setConflictNote('');setDiscoveredFigures([])}setPreview(null);setAttempt(a=>a+1)}}
 }catch(cause){if(mounted.current){setUncertain(!(cause instanceof TaskRequestError&&cause.status>=400&&cause.status<500));setConfirming(null)
  const code=cause instanceof TaskRequestError&&cause.status===409?cause.code:undefined
  // Customers keep their input; re-read the list so the next save overwrites the latest version.
  if(customer&&kind==='save'&&(code==='manuscript_exists'||code==='manuscript_revision_conflict')){refreshConflictBase.current=true;setError(code==='manuscript_exists'?'这个项目已经有稿件。请覆盖之前的写作材料。':'这份稿件已有更新。你输入的内容仍在，请核对后再保存。');setAttempt(a=>a+1);return}
  setError(customer&&!(cause instanceof TaskRequestError&&cause.status===409)?safeError(cause,unconfirmed):cause instanceof TaskRequestError&&cause.status===409?(paperPlan?'项目需求、图表或引用已变化，请刷新稿件资料后重新核对。':'来源、引用或稿件版本已变化，请刷新并核对后另存新版本。'):safeError(cause,'事实稿请求未确认，请刷新后重试。'))}}
 finally{if(request.current===controller)request.current=null;if(mounted.current)setBusy(false)}}
 async function recover(version:ManuscriptVersion){
  if(request.current||!sessionValid)return
  const controller=new AbortController()
  request.current=controller;setBusy(true);setError('')
  const taskUrl=`/api/v1/tasks/${encodeURIComponent(version.task_id)}`
  const fallback=customer?'写作材料保存结果未确认，请刷新后重试。':'事实稿请求未确认，请刷新后重试。'
  try{
   const {task,allowed_actions}=await taskRequest(`${taskUrl}/workspace`,controller,(value):value is TaskWorkspace=>
    isWorkspace(value,projectId,version.task_id)&&value.task.task_type==='manuscript_draft'&&
    value.task.input_version.kind==='manuscript'&&value.task.input_version.manuscript_version_id===version.id,fallback)
   if(task.status==='failed'){
    if(!allowed_actions.includes('retry')){
     setError(apiError({code:task.error_code},customer?'这一版暂时不能重新整理。':'当前事实稿任务不可重试。'))
     return
    }
    const body=JSON.stringify({operation:'retry',wait_id:null,expected_task_revision:task.revision,input_version:task.input_version})
    const signature=`${taskUrl}:${body}`
    if(!replay.current.has(signature))replay.current.set(signature,crypto.randomUUID())
    await taskRequest(`${taskUrl}/resume`,controller,(value):value is TaskView=>
     isTask(value,projectId,task.id)&&value.task_type==='manuscript_draft'&&sameInputVersion(value.input_version,task.input_version),fallback,
     {method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':replay.current.get(signature)!},body})
   }
  }catch(cause){if(mounted.current)setError(safeError(cause,fallback))}
  finally{
   if(request.current===controller)request.current=null
   if(mounted.current){setBusy(false);setAttempt(a=>a+1)}
  }
 }
 const editedManuscript=editing?history.find(m=>m.id===editing):undefined
 const draftOutdated=materialDirty&&!!editedManuscript&&input.expected_revision!==editedManuscript.current_revision
 const chosen=selected?history.find(m=>m.id===selected.id):null,version=chosen?.versions.find(v=>v.revision===selected?.revision)
 const selectedKey=chosen&&version?`${chosen.id}:${version.id}`:null
 if(layered&&selectedKey&&!visitedVersions.includes(selectedKey))setVisitedVersions(old=>[...old,selectedKey])
 const taskKey=selectedKey&&view?`${selectedKey}:${view}`:null
 if(layered&&taskKey&&!visitedTasks.includes(taskKey))setVisitedTasks(old=>[...old,taskKey])
 const taskVisited=(key:string,task:ManuscriptView)=>!layered||visitedTasks.includes(`${key}:${task}`)||selectedKey===key&&view===task
 const views:ManuscriptView[]=wordOnly?['list',...(chosen?['exports'] as const:[])]:['list','materials',...(chosen?['body','evidence',...(!customer?['checks'] as const:[]),'versions','writing','exports',...(school?['school'] as const:[])] as const:[])]
 const supportedArticle=!version?.snapshot.article_type||['research','narrative_review'].includes(version.snapshot.article_type)
 // The adopted current version gets its Word once (B03). A thesis only when its language check sealed the school
 // options, so a migrated, returned or revised version without them is generated by hand (B04 task 7).
 const autoWord=(v:ManuscriptVersion,m:Manuscript)=>(isCustomerSci||!!customerThesis&&!!v.snapshot.writing_provenance?.language_review_id&&!!v.snapshot.writing_provenance.school_export_options)&&v.revision===m.current_revision&&isAdoptedSnapshot(v.snapshot,v.parent_version_id)
 const editReportedResult=(update:(value:NonNullable<ManuscriptInput['reported_result']>)=>NonNullable<ManuscriptInput['reported_result']>)=>edit(old=>({...old,reported_result:update(old.reported_result??{text:'',source_ids:[]})}))
 const selectedCandidates=manualItems.filter(c=>input.sources.some(s=>sourceKey(s)===sourceKey(c)))
 const analyses=selectedCandidates.filter(c=>c.kind==='analysis_run'&&input.sources.some(s=>s.id===c.id&&s.role==='computed_results'))
 const figures=selectedCandidates.filter(c=>(c.kind==='figure'||c.kind==='figure_language_version'||c.kind==='original')&&input.sources.some(s=>sourceKey(s)===sourceKey(c)&&s.role==='image_observation'))
 const plannedFigures=paperPlan?.kind==='research'?paperPlan.materials.filter(m=>m.kind==='figure').map(m=>({id:m.selection.id,label:m.filename,materialCaption:m.result})):[]
 const noteFigures=[...plannedFigures,...figures,...discoveredFigures.filter(f=>!plannedFiles.has(f.id)&&!figures.some(v=>v.id===f.id)&&f.parents.some(id=>input.sources.some(s=>s.id===id&&s.role==='image_observation')))]
 const materialViews:Record<string,string>=paperPlan?{
  plan:'已保存的写作要求',...(school?{chapters:'章节配置'}:{}),sources:'补充来源',
  ...(!reviewArticle?{methods:'补充方法',results:'补充结果',...(noteFigures.length?{figures:'图注与分面'}:{}),conflicts:'冲突'}:{}),
  citations:'引用',preview:'预览',
 }:reviewArticle?{sources:'来源',citations:'引用',preview:'预览'}:{sources:'来源',methods:'方法',results:'结果',figures:'图注',conflicts:'冲突',citations:'引用',preview:'预览'}
 const currentMaterialPage=materialsPage&&Object.hasOwn(materialViews,materialsPage)?materialsPage:paperPlan?'plan':'sources'
 const materialPage=(page:string)=>!layered&&!paperPlan||currentMaterialPage===page
 // Customer thesis back from adopting a school template (B04 task 8). A changed confirmation carries each saved
 // chapter use to the new chapter of the same title; the rest wait as “待选择” and nothing is submitted. Then the
 // chapter the trip started from is focused (by id, then by title), or the chapter panel when it is gone.
 const chapterTarget=useRef(initialChapter),previousTitles=useRef<Record<string,string>>({})
 const [pendingChapters,setPendingChapters]=useState<string[]>([]),[chaptersRebuilt,setChaptersRebuilt]=useState(false),[chapterGone,setChapterGone]=useState(false)
 const chapterPage=paperPlan?'chapters':'sources'
 // Runs after every render until the chapters are read and the focus has landed; each branch settles its condition.
 /* oxlint-disable react/set-state-in-effect, react-hooks/exhaustive-deps */
 useEffect(()=>{
  if(!customerThesis||wordOnly||loading||!candidates||!readiness)return
  const saved=input.thesis
  if(readiness.ready&&readiness.confirmation_id&&saved&&saved.confirmation_id!==readiness.confirmation_id){
   const titles=draft.chapterTitles?.confirmation_id===saved.confirmation_id?draft.chapterTitles.titles:{}
   previousTitles.current={...draft.chapterTitles?.titles}
   const sameTitle=(title:string)=>saved.chapter_mappings.filter(mapping=>titles[mapping.chapter_id]===title)
   const pending:string[]=[]
   const chapter_mappings=readiness.chapters.map((chapter):ChapterMapping=>{
    const [match,...others]=sameTitle(chapter.title)
    if(match&&!others.length&&readiness.chapters.filter(entry=>entry.title===chapter.title).length===1)return {...match,chapter_id:chapter.id}
    pending.push(chapter.id);return {chapter_id:chapter.id,purpose:'' as SchoolPurpose,output_language:'project',result_group_ids:[]}
   })
   setDraft(old=>({...old,input:{...old.input,thesis:{confirmation_id:readiness.confirmation_id!,profile_revision:readiness.profile.revision,chapter_mappings}},chapterTitles:chapterTitlesOf(readiness)}))
   setPreview(null);setPendingChapters(pending);setChaptersRebuilt(true)
   return
  }
  const target=chapterTarget.current
  if(!target)return
  if(currentMaterialPage!==chapterPage){setMaterialsPage(chapterPage);return}
  chapterTarget.current=undefined
  const titles={...previousTitles.current,...draft.chapterTitles?.titles}
  const title=target.id===null?undefined:titles[target.id]
  const originalNames=Object.values(previousTitles.current)
  const sameTitle=readiness.chapters.filter(chapter=>chapter.title===title)
  const uniqueTitle=sameTitle.length===1&&originalNames.filter(name=>name===title).length<=1
  const match=readiness.chapters.find(chapter=>chapter.id===target.id)??(uniqueTitle?sameTitle[0]:undefined)
  const element=match?document.getElementById(`thesis-chapter-${match.id}`):null
  if(target.id!==null&&!element)setChapterGone(true)
  ;(element??document.getElementById('thesis-chapters'))?.focus()
  onChapterFocused?.()
 })
 /* oxlint-enable react/set-state-in-effect, react-hooks/exhaustive-deps */
 // The trip starts with the chapter titles in the draft, so the way back can find the chapter by title.
 const openSchoolTemplate=onOpenSchoolTemplate&&((chapter?:TemplateTripChapter)=>{
  if(customerThesis&&readiness?.confirmation_id)setDraft(old=>({...old,chapterTitles:chapterTitlesOf(readiness)}))
  onOpenSchoolTemplate(chapter)
 })
 function editChapters(update:(previous:ManuscriptInput)=>ManuscriptInput){
  edit(update)
  if(customerThesis&&readiness?.confirmation_id)setDraft(old=>({...old,chapterTitles:chapterTitlesOf(readiness)}))
 }
 const groupLabel=customer?'结果分组 {number}':'Results 分组 {number}'
 function methodField(field:MethodField){return <div className="manuscript-method" key={field}><label>{t(methodLabels[field])}<textarea value={input.methods[field]} maxLength={6000} rows={2} onChange={e=>edit(old=>({...old,methods:{...old.methods,[field]:e.target.value}}))}/></label><label className="manuscript-method-source">{t('方法依据')}<select aria-label={t('{field}的依据',{field:t(methodLabels[field])})} multiple value={input.method_source_ids[field]??[]} onChange={e=>{const ids=Array.from(e.target.selectedOptions,o=>o.value);edit(old=>({...old,method_source_ids:{...old.method_source_ids,[field]:ids}}))}}>{selectedCandidates.filter(c=>input.sources.some(s=>s.id===c.id&&s.role==='methods')).map(c=><option key={sourceKey(c)} value={c.id}>{candidateLabel(c)}</option>)}</select></label><small className="muted">{t('未选择依据时标注为用户提供；空白保留待补充。')}</small></div>}
 // Keep the supplementary editor reachable while the main writing workspace is loading.
 const customerMaterialList=customer&&layered&&view==='list'&&!wordOnly
 const latestInput=ordered[0]?.versions.find(v=>v.revision===ordered[0].current_revision)?.input
 const composerInput=!materialDirty&&validInput(latestInput)?latestInput:input
 const readFeedback=<>{loading&&<p role="status">{t('正在读取稿件资料……')}</p>}{loadError&&<p role="alert" className="error-panel">{t(loadError)}</p>}</>
 const materialButton=!wordOnly&&<button type="button" className={customerMaterialList?"button-quiet":"button-primary"} onClick={()=>onViewChange?.('materials')}>{t(customer?'整理写作材料':'整理事实稿资料')}</button>
 return <section className="manuscript-workspace" aria-label={t(school?'毕业论文写作':'SCI 写作')}>
 {!customerMaterialList&&<div className="workspace-page-heading"><div><span className="workspace-eyebrow">{t(school?'毕业论文':'SCI')}</span><h2>{t(school?'毕业论文写作':'SCI 写作')}</h2><p>{t(school?(customer?'按学校模板的章节整理写作材料，生成正文初稿，核对后采用为新的一版。':'按已确认学校章节组织研究资料，核对候选后显式发布新版本。'):customerSci?'整理写作材料，生成完整文章初稿或重写指定章节，核对后采用为新版本。':'整理来源与事实稿，生成完整七部分候选或重写指定章节，经审核后显式发布新版本。')}</p></div><button type="button" disabled={busy||!sessionValid} onClick={()=>setAttempt(a=>a+1)}>{t('刷新稿件资料')}</button></div>}
 {!customerMaterialList&&<p className="warning-panel">{t(customer?'写作材料由系统整理；生成正文前会请你确认费用。科研内容、来源、数值、引用和待办仍需你核实。':school?'学校事实稿只整理已选研究资料；正式模型写作无授权时保持等待，离线样例不代表真实写作质量。':'事实稿由本地生成；受控模型写作须另行明确授权。科研内容、来源、数值、引用及待办仍须研究人员核实。')}</p>}
 {!customerMaterialList&&readFeedback}{error&&<p role="alert" className="error-panel">{t(error)}</p>}{!sessionValid&&<p role="alert">{t('会话已失效，请重新登录。')}</p>}{draftOutdated&&(!layered||view==='materials')&&<p role="alert" className="warning-panel">{t('这份稿件已有更新。你输入的内容仍在，请核对后再保存。')}</p>}
 {saved&&<div className="manuscript-saved" role="status"><p>{t(saved.rewrite?'已保存为第 {revision} 版。下一步需要重新生成正文，会产生写作费用。':'已保存为第 {revision} 版。',{revision:saved.revision})}</p>{saved.rewrite&&<button type="button" className="button-primary" onClick={()=>{setSaved(null);onViewChange?.('writing')}}>{t('生成正文初稿')}</button>}</div>}
 {confirming!==null&&<OverwriteConfirm revision={confirming} busy={busy} onCancel={()=>setConfirming(null)} onConfirm={()=>void submit('save',undefined,true)}/>}
 {analysisReceived&&<p role="status">{t('已合并固定分析资料')}{!customer&&<> · {analysisReceived.analysis_run_id} · {t('配置修订 {number}',{number:analysisReceived.setup_revision})}</>} · {t(analysisReceived.report_status==='selected'?'含已保存分析报告':'未附带分析报告')}</p>}
 <ManuscriptDraftProvider register={registerLeaveGuard}>
 {onStartReview && chosen && version?.status==='published' && (view==='body'||view==='exports') &&
   <div className="manuscript-actions customer-review-handoff">
     <button type="button" className="button-quiet" onClick={()=>onStartReview(chosen.id,version.revision)}>{t('以此版本处理意见')}</button>
   </div>}
 {layered&&<>{!customerMaterialList&&<nav className="manuscript-view-nav" aria-label={t('稿件任务视图')}>{views.map(item=><button key={item} type="button" aria-pressed={view===item} onClick={()=>onViewChange?.(item)}>{t(({'research-selection':'研究成果写作材料','research-candidates':'核对事实候选',list:'稿件列表',materials:customer?'写作材料':'事实稿资料',body:'正文',evidence:'依据',checks:'检查',versions:'版本',writing:'写作',exports:'导出',school:customerThesis?'模板迁移':'学校修订'})[item])}</button>)}</nav>}{view!=='list'&&view!=='materials'&&chosen&&version&&<div className="manuscript-fixed-context"><strong>{chosen.title}</strong>{customer?<VersionLabel revision={version.revision} savedAt={version.created_at} current={version.revision===chosen.current_revision}/>:<span>{t('固定版本 {number}',{number:version.revision})}</span>}</div>}{view==='list'&&<section className="manuscript-list" aria-label={t('稿件列表')}>
   {customerMaterialList&&<><div className="paper-draft-tools">{materialButton}</div>{readFeedback}
     {loadError&&<button type="button" onClick={()=>setAttempt(a=>a+1)}>{t('刷新稿件资料')}</button>}
     {active&&sessionValid&&candidates&&!loading&&!loadError&&<PaperDraftComposer projectId={projectId} active={active} school={!!customerThesis}
       candidates={candidates} baseInput={composerInput} current={ordered[0]} sciSettings={customerSci?.settings} planUnavailable={paperPlanUnavailable}
       onRefresh={()=>setAttempt(a=>a+1)} onPrepared={root=>setHistory(old=>[root,...old.filter(m=>m.id!==root.id)])}
       onOpenGenerated={(id,revision,requestId)=>{setSelected({id,revision});setAttempt(a=>a+1);if(onOpenGenerated)onOpenGenerated(id,revision,requestId);else{onSelectVersion?.(id,revision);onViewChange?.('writing')}}}
       onFindLiterature={onFindLiterature??onOpenLiterature} onOpenSchoolTemplate={openSchoolTemplate} onOpenRequirements={onOpenRequirements} onOpenMaterials={onOpenMaterials}/>}
     </>}
   {!customerMaterialList&&!history.length&&!loading&&<p>{t(customer?'还没有稿件。':'尚无事实稿。')}</p>}{customer?ordered.map((m,index)=>{const current=m.versions.find(v=>v.revision===m.current_revision);return <article key={m.id}><p className="workspace-eyebrow">{t(index===0?'当前稿件':'之前的稿件')}</p><h3>{m.title}</h3><p>{current?<VersionLabel revision={current.revision} savedAt={current.created_at}/>:t('第 {revision} 版',{revision:m.current_revision})}</p><button type="button" onClick={()=>openVersion(m.id,m.current_revision)}>{t('打开这份稿件')}</button>{wordOnly&&<ul aria-label={t('稿件版本历史')}>{m.versions.filter(v=>v.revision!==m.current_revision).map(v=><li key={v.id}><VersionLabel revision={v.revision} savedAt={v.created_at}/> <button type="button" onClick={()=>openVersion(m.id,v.revision)}>{t('查看这一版')}</button></li>)}</ul>}</article>}):history.map(m=><article key={m.id}><h3>{m.title}</h3><p>{t('当前版本 {number}',{number:m.current_revision})}</p><button type="button" onClick={()=>openVersion(m.id,m.current_revision)}>{t(wordOnly?'打开当前版本':'打开稿件')}</button>{wordOnly&&<ul aria-label={t('稿件版本历史')}>{m.versions.filter(v=>v.revision!==m.current_revision).map(v=><li key={v.id}><button type="button" onClick={()=>openVersion(m.id,v.revision)}>{t('查看版本 {number}',{number:v.revision})}</button></li>)}</ul>}</article>)}{!customerMaterialList&&materialButton}</section>}{view!=='list'&&view!=='materials'&&!version&&!loading&&<p role="status">{t(customer?'请先从稿件列表选择一份稿件。':'请先从稿件列表选择固定版本。')}</p>}</>}
 {!wordOnly&&<div hidden={layered&&view!=='materials'}>
  {(layered||paperPlan)&&<nav className="manuscript-view-nav" aria-label={t('资料编排步骤')}>{Object.entries(materialViews).map(([page,label],index)=><button key={page} type="button" aria-pressed={currentMaterialPage===page} onClick={()=>setMaterialsPage(page)}><span aria-hidden="true">{index+1}. </span>{t(label)}</button>)}</nav>}
  {paperPlan&&<div hidden={!materialPage('plan')}><PaperPlanSummary plan={paperPlan} heading="已保存的写作要求" omittedCount={paperPlan.omitted_count} customerView={customer} onOpenRequirements={onOpenRequirements} onOpenMaterials={onOpenMaterials}/></div>}
  {paperPlanUnavailable&&!loading&&<p className="warning-panel">{t('已保存的写作要求暂不可用，请刷新稿件资料。')}</p>}
  <div hidden={!materialPage(chapterPage)}>
 {chapterGone&&<p role="status" className="warning-panel">{t('原位置已不可用，已回到章节与复核。')}</p>}
 {chaptersRebuilt&&<p role="status" className="warning-panel">{t('已按新采用的模板更新章节，请核对标为待选择的章节。')}</p>}
 {school&&<ThesisChapterFields disabled={busy||!sessionValid||!candidates} projectId={projectId} readiness={candidates?.thesis??null}
   input={thesis?{...input,thesis}:input} onChange={customerThesis?editChapters:edit} onOpenSchoolTemplate={openSchoolTemplate} hasReportedResult={!!reportedResult} paperPlan={paperPlan}
   customerView={!!customerThesis} pendingChapterIds={pendingChapters}/>}
 </div>
  <form className="project-form manuscript-form" aria-label={t(customer?'写作材料':'事实稿资料')} onSubmit={e=>void submit('save',e)}><fieldset disabled={busy||!sessionValid||!candidates||paperPlanUnavailable||school&&!readiness?.ready||customer&&loading}><legend>{t(customer?'写作材料':editing?'编辑新版本资料':'新建事实稿')}</legend>
  {overwriteTarget&&(()=>{const current=overwriteTarget.versions.find(v=>v.revision===overwriteTarget.current_revision);return <p className="manuscript-overwrite-target">{t('将覆盖：')}<strong>{overwriteTarget.title}</strong> {current?<VersionLabel revision={current.revision} savedAt={current.created_at}/>:t('第 {revision} 版',{revision:overwriteTarget.current_revision})}</p>})()}
  {paperPlan&&<p className="muted">{t(customer?'已保存的题目、关键词和已关联的图表会随本次写作材料保存，可按需补充其他来源和引用。':'已保存的题目、关键词和已关联的图表会随本次事实稿保存，可按需补充其他来源和引用。')}</p>}
  <div className="project-fields">{!paperPlan&&<label>{t('稿件标题')}<input required maxLength={200} value={input.title} onChange={e=>edit(old=>({...old,title:e.target.value}))}/></label>}<label>{t('稿件输出语言')}<select value={input.output_language} onChange={e=>edit(old=>({...old,output_language:e.target.value as Locale,citation_draft:null}))}><option value="zh-CN">{t('简体中文')}</option><option value="en">English</option></select></label></div>
 <p className="muted">{t('界面语言与稿件输出语言独立；历史版本按原输出语言保存。')}</p>
  <section hidden={!materialPage('sources')} className="manuscript-panel"><h3>{t(paperPlan?'补充来源':'选择来源')}</h3><p>{t('固定统计结果、用户资料、图像观察与外部文献分别标注。')}</p>{candidates&&!manualItems.length&&<p>{t(paperPlan?'暂无其他可补充的来源。':customer?'暂无可用文件，可上传资料或添加已核验的引用。':'暂无可用来源，请先在项目文件与分析中保存资料。')}</p>}
  <div className="manuscript-sources">{manualItems.map(c=>{const selected=input.sources.find(s=>sourceKey(s)===sourceKey(c));const label=candidateLabel(c);return <fieldset className="manuscript-source" key={sourceKey(c)} aria-label={label}><legend>{label}</legend><label><input type="checkbox" checked={!!selected} onChange={e=>toggleSource(c,e.target.checked)}/>{label}</label>{c.version!==null&&<small>{t('来源版本 {number}',{number:c.version})}</small>}<label>{t('资料用途')}<select disabled={!selected} value={selected?.role??c.allowed_roles[0]} onChange={e=>changeRole(c,e.target.value as SourceRole)}>{c.allowed_roles.map(r=><option key={r} value={r}>{t(roleLabels[r])}</option>)}</select></label>{c.download_url&&<ProjectDownloadLink href={c.download_url} filename={c.label}>{t('查看来源文件')}</ProjectDownloadLink>}</fieldset>})}</div>
 </section>
  <section hidden={!materialPage('methods')} className="manuscript-panel"><h3>{t(paperPlan?'补充方法':'研究与方法')}</h3>{methodFields.slice(0,3).map(methodField)}{customer?methodFields.slice(3).map(methodField):<details><summary>{t('研究设计、样本、步骤与伦理')}</summary>{methodFields.slice(3).map(methodField)}</details>}</section>
 <section hidden={!materialPage('results')} className="manuscript-panel"><h3>{t(customer?'结果分组':'Results 分组')}</h3><p className="muted">{t(customer?'按你打算讨论的顺序排列结果和图表；调整顺序不会丢失已关联的资料。':'按论述顺序组织结果与图表；移动分组保留来源和段落身份。')}</p>
  {legacyResultEntry&&<fieldset className="manuscript-group"><legend>{t('用户提供的结果与出处')}</legend>
 <label>{t('用户提供的主要结果')}<textarea maxLength={20000} value={input.reported_result?.text??''} onChange={e=>editReportedResult(value=>({...value,text:e.target.value}))}/></label>
 <p className="muted">{t(customer?'请勾选支撑这段结果的来源。未绑定出处的陈述不会进入写作材料；已绑定的内容仍标为用户提供。':'请勾选支撑这段结果的来源。未绑定出处的陈述不会进入事实稿；已绑定的内容仍标为用户提供。')}</p>
 {customerThesis&&<p className="muted">{t('关联出处后，在来源页将这段内容分配给一个结果章节。')}</p>}
 {selectedCandidates.filter(c=>input.sources.some(s=>s.id===c.id&&s.role==='user_results')).map(c=><label key={sourceKey(c)}><input type="checkbox" checked={input.reported_result?.source_ids.includes(c.id)??false}
 onChange={e=>editReportedResult(value=>({...value,source_ids:e.target.checked?[...value.source_ids,c.id]:value.source_ids.filter(id=>id!==c.id)}))}/>{t('关联结果来源 {name}',{name:candidateLabel(c)})}</label>)}
 </fieldset>}{input.results_groups.map((g,index)=><fieldset key={g.id} className="manuscript-group" aria-label={t(groupLabel,{number:index+1})}><legend>{t(groupLabel,{number:index+1})}</legend><label>{t('分组标题')}<input value={g.title} maxLength={200} onChange={e=>groupChange(g.id,item=>({...item,title:e.target.value}))}/></label><div className="manuscript-group-options"><div><h4>{t('关联统计结果')}</h4>{analyses.map(a=><label key={a.id}><input type="checkbox" checked={g.analysis_run_ids.includes(a.id)} onChange={e=>groupChange(g.id,item=>({...item,analysis_run_ids:e.target.checked?[...item.analysis_run_ids,a.id]:item.analysis_run_ids.filter(id=>id!==a.id)}))}/>{a.label}</label>)}{!analyses.length&&<p>{t('请先选择固定统计结果来源。')}</p>}</div><div><h4>{t('关联图表')}</h4>{figures.map(f=><label key={f.id}><input type="checkbox" checked={g.figure_ids.includes(f.id)} onChange={e=>groupChange(g.id,item=>({...item,figure_ids:e.target.checked?[...item.figure_ids,f.id]:item.figure_ids.filter(id=>id!==f.id)}))}/>{f.label}</label>)}</div></div><div className="manuscript-actions"><button type="button" disabled={index===0} onClick={()=>moveGroup(index,-1)}>{t('上移分组')}</button><button type="button" disabled={index===input.results_groups.length-1} onClick={()=>moveGroup(index,1)}>{t('下移分组')}</button><button type="button" onClick={()=>edit(old=>({...old,results_groups:old.results_groups.filter(item=>item.id!==g.id),...(old.thesis?{thesis:{...old.thesis,chapter_mappings:old.thesis.chapter_mappings.map(m=>({...m,result_group_ids:m.result_group_ids.filter(id=>id!==g.id)}))}}:{})}))}>{t('移除分组')}</button></div></fieldset>)}<button type="button" disabled={input.results_groups.length>=20} onClick={()=>edit(old=>({...old,results_groups:[...old.results_groups,{id:crypto.randomUUID(),title:'',analysis_run_ids:[],figure_ids:[]}]}))}>{t(customer?'添加结果分组':'添加 Results 分组')}</button></section>
 {noteFigures.length>0&&<section hidden={!materialPage('figures')} className="manuscript-panel"><h3>{t('图注与分面')}</h3><p className="muted">{t('冻结版本按来源绑定图表编号；分面标签使用不重复的大写 A–Z。图注与正文引用问题会列入待办，仍需人工通读核对。')}</p>{noteFigures.map(f=>{const note=input.figure_notes.find(n=>n.figure_id===f.id)??{figure_id:f.id,caption:'',panels:[]};const update=(next:typeof note)=>edit(old=>({...old,figure_notes:[...old.figure_notes.filter(n=>n.figure_id!==f.id),next]}));return <fieldset key={f.id}><legend>{f.label}</legend>{'materialCaption' in f?<p>{f.materialCaption}</p>:<label>{t('用户提供图注')}<textarea value={note.caption} onChange={e=>update({...note,caption:e.target.value})}/></label>}{note.panels.map((p,i)=><div key={i} className="project-fields"><label>{t('分面标签')}<input value={p.label} onChange={e=>update({...note,panels:note.panels.map((v,j)=>j===i?{...v,label:e.target.value}:v)})}/></label><label>{t('分面说明')}<input value={p.description} onChange={e=>update({...note,panels:note.panels.map((v,j)=>j===i?{...v,description:e.target.value}:v)})}/></label><button type="button" onClick={()=>update({...note,panels:note.panels.filter((_,j)=>j!==i)})}>{t('移除分面')}</button></div>)}<button type="button" onClick={()=>update({...note,panels:[...note.panels,{label:'',description:''} ]})}>{t('添加分面')}</button></fieldset>})}</section>}
 <section hidden={!materialPage('conflicts')} className="manuscript-panel"><h3>{t('矛盾资料')}</h3><p className="muted">{t(customer?'不同说法会并列保留；你核实之前，不会写成确定的内容。':'并列保留不同说法；冲突字段不写成已确认事实。')}</p><label>{t('矛盾字段')}<select value={conflictField} onChange={e=>setConflictField(e.target.value as MethodField)}>{methodFields.map(f=><option key={f} value={f}>{t(methodLabels[f])}</option>)}</select></label><label>{t('不同说法（每行一项）')}<textarea value={conflictValues} onChange={e=>setConflictValues(e.target.value)}/></label><label>{t('核实备注')}<input value={conflictNote} onChange={e=>setConflictNote(e.target.value)}/></label><button type="button" disabled={conflictValues.split('\n').filter(v=>v.trim()).length<2} onClick={()=>{edit(old=>({...old,method_conflicts:[...old.method_conflicts.filter(c=>c.field!==conflictField),{field:conflictField,values:conflictValues.split('\n').map(v=>v.trim()).filter(Boolean),note:conflictNote}]}));setConflictValues('');setConflictNote('')}}>{t('记录待核实')}</button>{input.method_conflicts.map(c=><div key={c.field}><strong>{t(methodLabels[c.field])}</strong><p>{c.values.join(' / ')}</p><button type="button" onClick={()=>{setConflictField(c.field);setConflictValues(c.values.join('\n'));setConflictNote(c.note)}}>{t('编辑矛盾')}</button><button type="button" onClick={()=>edit(old=>({...old,method_conflicts:old.method_conflicts.filter(v=>v.field!==c.field)}))}>{t('移除矛盾记录')}</button></div>)}</section>
 <section hidden={!materialPage('citations')} className="manuscript-panel"><h3>{t('引用关联')}</h3><label>{t('已核验引用稿')}<select value={input.citation_draft?.id??''} onChange={e=>{const draft=candidates?.citation_drafts.find(d=>d.id===e.target.value);edit(old=>({...old,citation_draft:draft?{id:draft.id,revision:draft.revision}:null}))}}><option value="">{t('不添加引用')}</option>{candidates?.citation_drafts.map(d=><option key={d.id} value={d.id} disabled={!d.usable}>{d.title}{!d.usable?` · ${t('暂不可用')}`:''}</option>)}</select></label><p>{t(customer?'引用沿用已核验的文献；新写的内容需要另外选择支持的文献。':'引用沿用原核验门禁；新论述不自动继承旧支持性决定。')}</p>{customer&&onOpenLiterature?<button type="button" onClick={onOpenLiterature}>{t('核查引用与证据')}</button>:<a href={`#project=${encodeURIComponent(projectId)}&section=literature`} onClick={e=>{if(onOpenLiterature){e.preventDefault();onOpenLiterature()}}}>{t('核查引用与证据')}</a>}</section>
  <div className="manuscript-actions"><button type="button" onClick={()=>{setMaterialsPage('preview');void submit('preview')}}>{t(busy?'正在提交……':customer?'预览写作材料':'预览事实稿')}</button><button type="submit" className="button-primary">{t(customer?overwriteTarget?'覆盖之前的写作材料':'确认并继续':editing?'保存为新版本':'保存并创建事实稿')}</button>{editing&&!customer&&<button type="button" onClick={startNewManuscript}>{t('另建稿件')}</button>}</div>
 </fieldset></form>
 <div hidden={!materialPage('preview')}>{preview&&<><ManuscriptPreview customerSci={isCustomerSci} customerView={customer} snapshot={preview} label={customer?'写作材料预览':undefined}/><FigureLanguagePanel projectId={projectId} snapshot={preview} onCreated={()=>setAttempt(a=>a+1)} confirmOnly={customer}/></>}</div></div>}
 <section hidden={layered&&view!=='versions'} className="manuscript-panel" aria-label={t('稿件版本历史')}><h3>{t('稿件版本历史')}</h3><p>{t(customer?'已保存的版本只读；再次保存写作材料会新增一版，之前的版本保持原样。':'已保存版本只读；编辑输入会新增版本，保留旧正文与引用。')}</p>{!history.length&&!loading&&<p>{t(customer?'还没有稿件。':'尚无事实稿。')}</p>}{customer?ordered.filter(m=>!layered||m.id===chosen?.id).map(m=><article className="manuscript-history" key={m.id}><h4>{m.title}</h4>{[...m.versions].sort((a,b)=>b.revision-a.revision).map(v=><div key={v.id} className="manuscript-version"><VersionLabel revision={v.revision} savedAt={v.created_at} current={v.revision===m.current_revision}/> <span>{t({pending:'待发布',published:'已发布',failed:'执行失败'}[v.status])}</span><div className="manuscript-actions"><button type="button" onClick={()=>{setPreview(null);openVersion(m.id,v.revision)}}>{t('查看这一版')}</button>{v.status==='failed'&&<button type="button" disabled={busy} onClick={()=>void recover(v)}>{t('重新整理这一版')}</button>}</div></div>)}</article>):history.filter(m=>!layered||m.id===chosen?.id).map(m=><article className="manuscript-history" key={m.id}><h4>{m.title}</h4>{m.versions.map(v=><div key={v.id} className="manuscript-version"><strong>{t('版本 {number}',{number:v.revision})}</strong><SchoolVersionOrigin version={v} versions={m.versions}/> <span>{t({pending:'待发布',published:'已发布',failed:'执行失败'}[v.status])} · {new Date(v.created_at).toLocaleString(locale)}</span><div className="manuscript-actions"><button type="button" onClick={()=>{setPreview(null);openVersion(m.id,v.revision)}}>{t('查看版本 {number}',{number:v.revision})}</button>{v.snapshot.paper_plan?<button type="button" disabled={busy||!sessionValid||!candidates?.paper_plan} onClick={startNewManuscript}>{t('用当前要求另建事实稿')}</button>:<button type="button" disabled={busy||!sessionValid||v.snapshot.writing_provenance?.schema_version===2} onClick={()=>{if(busy||materialDirty&&!window.confirm(t('当前资料有未保存修改。放弃并载入此版本？')))return;setEditing(m.id);setEditingAsReview(v.snapshot.article_type==='narrative_review');const next=structuredClone({...v.input,expected_revision:m.current_revision});setInput(next);setCleanInput(JSON.stringify(next));setMaterialsPage(null);onViewChange?.('materials');setDiscoveredFigures(snapshotFigures(v.snapshot));setPreview(null);setError('')}}>{t('以此版本编辑新稿')}</button>}{v.status==='failed'&&<button type="button" disabled={busy} onClick={()=>void recover(v)}>{t('重试事实稿发布')}</button>}{onOpenTask&&<button type="button" onClick={()=>onOpenTask(v.task_id)}>{t('查看事实稿任务')}</button>}</div></div>)}</article>)}</section>
 {initialManuscript&&!loading&&!version&&<p role="alert">{t(customer?'地址里的这一版稿件已不可用，没有自动换成最新一版。':'指定固定稿件版本不可用；不会自动替换为最新版本。')}</p>}
 {history.flatMap(m=>m.versions.map(v=>({m,v,key:`${m.id}:${v.id}`}))).filter(({key})=>layered?visitedVersions.includes(key)||key===selectedKey:key===selectedKey).map(({m:chosen,v:version,key})=>{
 const current=selectedKey===key,show=(task:ManuscriptView)=>!layered||current&&view===task
 const versionActive=active&&sessionValid&&current
 return <div key={key} hidden={!current||layered&&['list','materials','versions'].includes(view!)}>
 {!layered&&<p className="muted">{t('正在查看版本 {number}',{number:version.revision})}</p>}{customer&&version.revision!==chosen.current_revision&&<p className="muted">{t('这是之前的版本，只能查看。')}</p>}{version.current_changes.length>0&&<p role="alert" className="warning-panel">{t('原始来源已变化；此处仍展示冻结的历史版本，请核对后另存新版本。')}</p>}
 <div hidden={!show('body')} id={`manuscript-original-${chosen.id}-${version.revision}`}>{taskVisited(key,'body')&&<ManuscriptPreview customerSci={isCustomerSci} customerView={customer} snapshot={version.snapshot} presentation={layered?'body':'full'} label={version.snapshot.sections&&(!version.snapshot.paper_plan||version.snapshot.writing_provenance)?'已保存的完整稿':customer?'已保存的写作材料':'已保存的事实稿'}/>}</div>
 <div hidden={!show('evidence')}>{layered&&taskVisited(key,'evidence')&&<ManuscriptPreview customerSci={isCustomerSci} customerView={customer} snapshot={version.snapshot} presentation="evidence" label="固定稿件依据"/>}</div>
 <div hidden={!show('checks')}>{!customer&&taskVisited(key,'checks')&&<ManuscriptReview projectId={projectId} manuscriptId={chosen.id} version={version} currentRevision={chosen.current_revision} active={versionActive&&show('checks')} onPublished={refreshHistory}/>}</div>
 <div hidden={!show('writing')}>
 {customer&&versionActive&&show('writing')&&!initialWritingRequest&&<button type="button" className="button-quiet" onClick={()=>onViewChange?.('list')}>{t('选择文献并生成初稿')}</button>}
 {customer&&versionActive&&show('writing')&&version.revision===chosen.current_revision&&version.status!=='published'&&
  <section className="manuscript-panel">
   {version.status==='pending'?<>
    <p role="status">{t('正在整理第 {number} 版写作材料。整理完成后，这里会自动显示写作选项。',{number:version.revision})}</p>
    <button type="button" disabled={busy} onClick={()=>setAttempt(a=>a+1)}>{t('刷新准备状态')}</button>
   </>:<>
    <p role="alert">{t('第 {number} 版写作材料整理失败。',{number:version.revision})}</p>
    <button type="button" disabled={busy} onClick={()=>void recover(version)}>{t('重新整理这一版')}</button>
   </>}
  </section>}
 {version.status==='published'&&taskVisited(key,'writing')&&(customer||version.snapshot.paper_plan
  ? (supportedArticle&&(!customerThesis||!!version.snapshot.thesis_context)&&version.revision===chosen.current_revision
    ? <WritingLive projectId={projectId} manuscriptId={chosen.id} version={version} active={versionActive&&show('writing')}
      customerSci={customerSci?.settings} customerThesis={!!customerThesis} onPublished={adopted}
      initialWritingRequest={initialWritingRequest} initialParagraph={initialParagraph} onNeedSource={onNeedSource}/>
    : <p>{t(customer?'请使用当前且受支持的稿件版本生成正文。':'请使用当前且受支持的稿件版本发起受控写作。')}</p>)
  : <><WritingMaterialsPreview projectId={projectId} manuscriptId={chosen.id} revision={version.revision} active={versionActive&&show('writing')}/><ManuscriptWriting projectId={projectId} manuscriptId={chosen.id} version={version} active={versionActive&&show('writing')} onShowOriginal={layered?()=>onViewChange?.('body'):undefined} onOpenTask={onOpenTask} onPublished={refreshHistory}/></>)}</div>
 <div hidden={!show('school')}>{school&&version.status==='published'&&taskVisited(key,'school')&&<SchoolChanges projectId={projectId} manuscriptId={chosen.id} version={version} currentRevision={chosen.current_revision} active={versionActive&&show('school')} templateOnly={!!customerThesis} versions={customerThesis?chosen.versions:undefined} initialTarget={customerThesis?initialTarget:undefined} onAdopted={refreshHistory}/>}</div>
 <div hidden={!show('exports')}>{taskVisited(key,'exports')&&<>{!customer&&<><SchoolOpinionHandoff projectId={projectId} manuscriptId={chosen.id} version={version}/><FigureLanguagePanel projectId={projectId} snapshot={version.snapshot} onCreated={()=>setAttempt(a=>a+1)}/></>}{showAdopted&&version.revision===chosen.current_revision&&<p role="status" className="manuscript-saved">{t('已采用这份稿件（{title}，',{title:chosen.title})}<VersionLabel revision={version.revision} savedAt={version.created_at}/>{t('）。')}</p>}<ManuscriptExports projectId={projectId} manuscriptId={chosen.id} version={version} customerSci={!!customerSci} customerThesis={!!customerThesis} autoStart={autoWord(version,chosen)} onAutoStarted={onAutoWordStarted} versions={customer?undefined:history.flatMap(m=>m.versions).filter(v=>!!v.snapshot.thesis_context===!!version.snapshot.thesis_context)} onOpenTask={onOpenTask} active={versionActive&&show('exports')} onOpenMigration={customerThesis?onOpenMigration:undefined}/></>}</div>
 </div>})}
 </ManuscriptDraftProvider>
 </section>
}
