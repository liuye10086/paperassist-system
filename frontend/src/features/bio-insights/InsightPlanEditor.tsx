import type {AnalysisEntryIntent} from '../projects/analysisViews'
import {useEffect,useLayoutEffect,useRef,useState} from 'react'
import {savedContent} from '../../shared/savedContent'
import {safeError,useI18n} from '../../shared/i18n'
import {getApiUserId,onApiSessionChanged} from '../../shared/api/client'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {insightRequest,jsonRequest,projectBase} from './api'
import {useInsightDraft,useInsightIntent,useInsightRead} from './hooks'
import {kindLabels,type Config,type Design,type InsightKind,type Plan,type Source,type SourceItem,type Run,type Result} from './contracts'
import {buildPlan,defaultConfig,planIssues} from './state'
import InsightSources from './InsightSources'
import ComparisonSetup from './ComparisonSetup'
import {defaultSingleCellComposition,defaultSingleCellDE} from './singleCellComparison'
import {defaultBulkConfig,defaultQuantitativeConfig} from './quantitative'
import BulkModelReview from './BulkModelReview'
import QpcrSetup,{defaultQpcrConfig} from './QpcrSetup'
import FeatureExtractionSetup from './FeatureExtractionSetup'
import IntegrationSetup from './IntegrationSetup'
import SingleCellTopicSetup,{defaultSingleCellTopic} from './SingleCellTopicSetup'
import EvidenceLinks,{defaultEvidenceMatrix} from './EvidenceLinks'
import MicrobiomeSetup,{defaultMicrobiomeConfig} from './MicrobiomeSetup'
import ResultImportSetup from './ResultImportSetup'
import EnrichmentSetup from './EnrichmentSetup'
import BulkEnrichmentSetup,{BulkEnrichmentBinding,BulkEnrichmentCompatibility,BulkEnrichmentFigureSetup} from './BulkEnrichmentSetup'
import CandidateRecipe from './CandidateRecipe'
import FigureSetup from './FigureSetup'
import BulkPlanSettings from './BulkPlanSettings'
import {BULK_ORA_ELIGIBLE_BACKGROUND,bulkFigureLabels,bulkPanels,bulkPlanScope,fixedBulkEnrichmentIdentity,isBulkFigureType,isBulkPanel,type BulkPlanSeed} from './bulk'
import {Field,ConfigField,DataDetails,IntentState,ReadState,TaskStatus,DesignUnits} from './InsightShared'
type Draft={name:string;config:Config;sources:Source[];savedPlan?:Plan}
export default function InsightPlanEditor({projectId,kind,active,initial,initialProcessedId,initialResultId,bulkSeed,entryIntent,onSaved,onRun,registerLeaveGuard,allowNewAnalysis=true,allowExternalEvidenceRegistration}:{allowExternalEvidenceRegistration?:boolean;allowNewAnalysis?:boolean;projectId:string;kind:InsightKind;active:boolean;initial?:Plan|null;initialProcessedId?:string;initialResultId?:string;bulkSeed?:BulkPlanSeed;entryIntent?:AnalysisEntryIntent;onSaved:(v:Plan)=>void;onRun:(v:Run)=>void;registerLeaveGuard?:RegisterLeaveGuard}){
 const{t}=useI18n(),ordinaryScope=bulkSeed?`${kind}:bulk:${bulkPlanScope(bulkSeed)}`:`${kind}:${initialProcessedId??initialResultId??''}`,specialIntent=!bulkSeed&&(entryIntent==='evidence'&&kind==='candidate'||entryIntent==='qpcr'&&kind==='comparison'||entryIntent==='single_cell_topic'&&kind==='integration')?entryIntent:undefined,specialScope=specialIntent?`${ordinaryScope}:${specialIntent}`:ordinaryScope,[explicitScope,setExplicitScope]=useState('')
 const stored=(type:'draft'|'request',candidate:string,operation='plan')=>{try{return !!sessionStorage.getItem(`paperassist.bio-insight.${type}:${getApiUserId()??'anonymous'}:${projectId}:${operation}:${candidate}`)}catch{return false}}
 const pending=(candidate:string)=>stored('request',candidate)||stored('request',candidate,'run')
 const scope=initial?.id??(!specialIntent?ordinaryScope:pending(ordinaryScope)?ordinaryScope:pending(specialScope)||explicitScope===specialScope||stored('draft',specialScope)?specialScope:stored('draft',ordinaryScope)?ordinaryScope:specialScope),usingExistingOrdinary=!initial&&!!specialIntent&&scope===ordinaryScope,usingSpecial=!initial&&!!specialIntent&&scope===specialScope
 const[draft,setDraft]=useInsightDraft<Draft>(projectId,`plan:${scope}`,()=>({name:initial?.name??'',config:initial?.config??bulkSeed?.config??(usingSpecial&&specialIntent==='single_cell_topic'?defaultSingleCellTopic(initialProcessedId):usingSpecial&&specialIntent==='evidence'?defaultEvidenceMatrix():usingSpecial&&specialIntent==='qpcr'?defaultQpcrConfig():defaultConfig(kind)),sources:initial?.sources??(bulkSeed?[bulkSeed.source]:[])})),[preview,setPreview]=useState<{signature:string;design:Design}|null>(null),[busy,setBusy]=useState(false),[completedRun,setCompletedRun]=useState<{value:Run;generation:number}|null>(null),[error,setError]=useState(''),operation=useInsightIntent<Plan>(projectId,'plan',scope),run=useInsightIntent<Run>(projectId,'run',scope),request=useRef<AbortController|null>(null),alive=useRef(true),seenPlan=useRef(''),seenRun=useRef(''),base=projectBase(projectId)
 const bulkFigure=kind==='figure'&&isBulkFigureType(draft.config.figure_type)?draft.config.figure_type:null
 const bulkCandidate=kind==='candidate'&&draft.config.bulk_selection!=null
 const enrichmentFigure=kind==='figure'&&draft.config.bulk_enrichment_render===true
 const bulkEnrichment=(kind==='ora'||kind==='gsea_prerank')&&draft.config.bulk_enrichment!=null
 const bulkFixed=!!bulkFigure||bulkCandidate||enrichmentFigure
 const fixedEntry=bulkFixed||bulkEnrichment
 const bulkName=bulkFigure?(isBulkPanel(draft.config.bulk_panel)?bulkPanels[draft.config.bulk_panel]:bulkFigureLabels[bulkFigure])
  :bulkCandidate?'冻结 Bulk 候选':enrichmentFigure?(draft.config.figure_type==='gsea'?'固定 GSEA 曲线':'固定富集图')
  :bulkEnrichment?(kind==='ora'?'固定 Bulk ORA':'固定 Bulk GSEA'):null
 const savedPlan=draft.savedPlan??initial,revision=savedPlan?.revision??0,body=buildPlan(draft.name.trim()||t(bulkName??(kind==='integration'&&draft.config.schema_version===2?'单细胞专题':kindLabels[kind])),draft.config,draft.sources,revision,'draft'),signature=savedContent(body),projection=(v:Plan)=>buildPlan(v.name,v.config,v.sources,revision,'draft'),sameSaved=!!savedPlan&&savedContent(body)===savedContent(projection(savedPlan)),locked=busy||operation.busy||operation.unknown||run.busy||run.unknown||!operation.valid||!run.valid
 const launching=useRef(false),context=useRef({active,scope,allowNewAnalysis,generation:0})
 useLayoutEffect(()=>{context.current={active,scope,allowNewAnalysis,generation:context.current.generation+1};if(!active){request.current?.abort()}},[active,scope,allowNewAnalysis])
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;request.current?.abort()}},[])
 useEffect(()=>onApiSessionChanged(()=>{alive.current=false;request.current?.abort();setPreview(null)}),[])
 useEffect(()=>{if(!active){request.current?.abort();queueMicrotask(()=>setBusy(false))}},[active])
 useEffect(()=>{if(operation.value&&operation.value.id!==seenPlan.current){seenPlan.current=operation.value.id;onSaved(operation.value)}},[operation.value,onSaved])
 useEffect(()=>{if(run.value&&run.value.id!==seenRun.current){seenRun.current=run.value.id;onRun(run.value)}},[run.value,onRun])
 // Draft edits are already persisted by project and version; navigation does not discard them.
 useDraftLeaveGuard(registerLeaveGuard,false,locked||operation.unknown||run.unknown)
 // Complete the render that releases this editor's pending guard before host navigation.
 useEffect(()=>{if(!completedRun)return;if(!alive.current||!context.current.active||completedRun.generation!==context.current.generation){setCompletedRun(null);return}if(locked)return;setCompletedRun(null);seenRun.current=completedRun.value.id;onRun(completedRun.value)},[completedRun,locked,onRun])
 const sources=useInsightRead<{items:SourceItem[]}>(initialProcessedId&&!draft.sources.length?`${base}/bio-insights/sources?source_kind=bio_processed_dataset_version&page=1&page_size=100`:'',active&&!!initialProcessedId&&!fixedEntry)
 const resultInput=useInsightRead<Result>(initialResultId?`${base}/bio-insight-results/${initialResultId}`:'',active&&!!initialResultId&&!fixedEntry,true)
 const enrichmentSource=bulkEnrichment?draft.sources.find(source=>source.role==='result'):undefined
 const enrichmentInput=useInsightRead<Result>(enrichmentSource?`${base}/bio-insight-results/${encodeURIComponent(enrichmentSource.source_id)}`:'',active&&!!enrichmentSource,true)
 function change(config:Config){setDraft(d=>({...d,config}));setPreview(null)}
 function selectSources(sources:Source[]){
  setDraft(d=>{
   const initialConfig={...defaultConfig(kind),output_language:d.config.output_language}
   const defaultToBulk=kind==='comparison'&&!initial&&!d.savedPlan&&!d.sources.length&&sources.some(s=>s.assay==='bulk_rna_counts')
    &&savedContent(d.config)===savedContent(initialConfig)
   return {...d,sources,config:defaultToBulk?{...defaultBulkConfig(),output_language:d.config.output_language}:d.config}
  })
  setPreview(null)
 }
 function selectEnrichmentResources(resources:Source[]){
  setDraft(d=>({...d,sources:[...d.sources.filter(source=>source.role==='result'),...resources],config:{...d.config,
   resource_source_ids:resources.filter(source=>source.role==='gene_sets'||source.role==='resource').map(source=>source.source_id),
   mapping_source_ids:resources.filter(source=>source.role==='id_mapping').map(source=>source.source_id)}}))
  setPreview(null)
 }
 async function check(){if(!alive.current||!context.current.active||request.current||locked)return;const c=new AbortController();request.current=c;setBusy(true);setError('');setPreview(null);try{const design=await insightRequest<Design>(`${base}/bio-insight-plans/preview`,{...jsonRequest(body),signal:c.signal},true);if(alive.current&&!c.signal.aborted)setPreview({signature,design})}catch(cause){if(alive.current&&!c.signal.aborted)setError(safeError(cause,'设计预检失败，请核对固定来源。'))}finally{if(request.current===c){request.current=null;if(alive.current)setBusy(false)}}}
 const p={config:draft.config,onChange:change,sources:draft.sources},issues=planIssues(draft.config)
 const taxon=draft.config.bulk_enrichment?.source_taxon_id??0,evidence=draft.config.bulk_enrichment?.taxon_evidence?.trim()??''
 if(bulkEnrichment&&enrichmentInput.data&&fixedBulkEnrichmentIdentity(enrichmentInput.data).species_taxon_id===null
    &&(!Number.isInteger(taxon)||taxon<1||taxon>2147483647||!evidence||evidence.length>1000))issues.push('请填写有效的来源 taxonomy ID 和物种依据。')
 const canSave=(bulkFixed?draft.sources.length===1:!!draft.sources.length)&&(!bulkEnrichment||!!enrichmentInput.data)&&!issues.length
 const currentPreview=preview?.signature===signature?preview.design:null
 const reviewDesign=currentPreview??(bulkEnrichment&&sameSaved?savedPlan?.design:null)
 const validPreview=currentPreview?.executable===true
 const bulk=draft.config.schema_version===2&&draft.config.mode==='bulk_counts'
 const reviewedBulk=bulk&&draft.config.bulk_model==='shared_wald_v1'
 const initialStep=initial?.decision==='confirmed'?'review':fixedEntry?'config':'sources'
 const [step,setStep]=useState<'sources'|'config'|'review'>(initialStep),[configPanel,setConfigPanel]=useState('parameters'),[reviewPanel,setReviewPanel]=useState('summary')
 const runnable=!!savedPlan&&sameSaved&&savedPlan.decision==='confirmed'&&savedPlan.design.executable&&savedPlan.current_revision===savedPlan.revision&&!issues.length
 const eligibleBackground=!(sameSaved&&savedPlan?.decision==='confirmed')||savedPlan.config.bulk_background===BULK_ORA_ELIGIBLE_BACKGROUND
 const canStart=bulk?runnable:currentPreview?validPreview:!bulkEnrichment||runnable
 async function saveOnly(){
  if(!alive.current||!context.current.active||launching.current||locked||!canSave)return
  if(sameSaved&&savedPlan){onSaved(savedPlan);return}
  await operation.submit(savedPlan?`${base}/bio-insight-plans/${savedPlan.plan_id}/versions`:`${base}/bio-insight-plans`,{...body,decision:'draft'})
 }
 async function confirmBulk(){
  if(!alive.current||!context.current.active||!context.current.allowNewAnalysis||locked||!canSave||!validPreview||runnable||pending(scope))return
  if(reviewedBulk&&!currentPreview?.reviewed_design_sha256)return
  const fixed=await operation.submit(savedPlan?`${base}/bio-insight-plans/${savedPlan.plan_id}/versions`:`${base}/bio-insight-plans`,
   {...body,decision:'confirmed',...(reviewedBulk?{reviewed_design_sha256:currentPreview?.reviewed_design_sha256}:{})},{silent:true})
  if(fixed&&alive.current&&context.current.scope===scope){
   setDraft(d=>({...d,name:fixed.name,config:fixed.config,sources:fixed.sources,savedPlan:fixed}))
   setPreview(null)
  }
 }
 async function start(){
  if(!canStart)return
  if(!alive.current||!context.current.active||!context.current.allowNewAnalysis||launching.current||locked||!canSave||pending(scope))return
  launching.current=true;setBusy(true);setError('')
  const generation=context.current.generation,canContinue=()=>alive.current&&context.current.active&&context.current.allowNewAnalysis&&context.current.scope===scope&&context.current.generation===generation
  try{
   let fixed=runnable?savedPlan:null
   if(!fixed){
    let design=preview?.signature===signature?preview.design:null
    if(!design){const c=new AbortController();request.current=c;try{design=await insightRequest<Design>(`${base}/bio-insight-plans/preview`,{...jsonRequest(body),signal:c.signal},true);if(!canContinue()||c.signal.aborted)return;setPreview({signature,design})}finally{if(request.current===c)request.current=null}}
    if(!canContinue()||!design.executable)return
    fixed=await operation.submit(savedPlan?`${base}/bio-insight-plans/${savedPlan.plan_id}/versions`:`${base}/bio-insight-plans`,{...body,decision:'confirmed'},{silent:true})??null
    if(fixed&&alive.current&&context.current.scope===scope)setDraft(d=>({...d,name:fixed!.name,config:fixed!.config,sources:fixed!.sources,savedPlan:fixed!}))
    if(!fixed||!canContinue())return
   }
   if(!canContinue())return
   const result=await run.submit(`${base}/bio-insight-runs`,{plan_version_id:fixed.id,expected_plan_revision:fixed.revision,source_digest:fixed.source_digest},{silent:true})
   if(result&&canContinue())setCompletedRun({value:result,generation})
  }catch(cause){if(canContinue())setError(safeError(cause,'设计预检失败，请核对固定来源。'))}
  finally{launching.current=false;if(alive.current)setBusy(false)}
 }
 const [stepScope,setStepScope]=useState(scope);if(stepScope!==scope){setStepScope(scope);setStep(initialStep)}
 return <section className="insight-editor">
  <nav className="analysis-sequence" aria-label={t('分析配置顺序')}>{([['sources','选择数据'],['config','配置分析'],['review','检查与运行']] as const).map(([key,label],index)=><button type="button" key={key} aria-current={step===key?'step':undefined} disabled={locked||key==='config'&&!draft.sources.length||key==='review'&&!canSave} onClick={()=>setStep(key)}><span aria-hidden="true">{index+1}. </span>{t(label)}</button>)}</nav>
  <div className="insight-editor-body">
   {usingExistingOrdinary&&<div><p>{t('已保留现有草稿，入口配置尚未应用。')}</p><button type="button" disabled={locked||pending(scope)} onClick={()=>{if(locked||pending(scope))return;setPreview(null);setExplicitScope(specialScope)}}>{t(specialIntent==='evidence'?'另建本次证据计划':specialIntent==='single_cell_topic'?'打开本次单细胞专题草稿':'另建本次 qPCR 计划')}</button></div>}{usingSpecial&&<p>{t(specialIntent==='evidence'?'当前为本次证据计划草稿。':specialIntent==='single_cell_topic'?'当前为单细胞专题。':'当前为本次 qPCR 计划草稿。')}</p>}
  <fieldset disabled={locked} className="insight-editor-fields">
   <div hidden={step!=='sources'}>
    <h3>{t('选择本次分析的数据')}</h3><p className="muted">{t('选用已上传或已处理的固定版本，后续配置沿用这些来源。')}</p>
    {fixedEntry?<DataDetails title="本次固定来源" value={draft.sources.map(source=>({source_kind:source.source_kind,source_id:source.source_id,sha256:source.sha256}))}/>:<>
    {initialProcessedId&&!draft.sources.some(s=>s.source_id===initialProcessedId)&&<button type="button" disabled={!sources.data?.items.some(s=>s.source_id===initialProcessedId)} onClick={()=>{const s=sources.data?.items.find(s=>s.source_id===initialProcessedId);if(s?.sha256)selectSources([...draft.sources,{...s,sha256:s.sha256,role:'processed',locator:{kind:'object'}}])}}>{t('采用入口的固定处理版本')}</button>}
 {resultInput.data&&!draft.sources.some(s=>s.source_id===initialResultId)&&<button type="button" onClick={()=>setDraft(d=>({...d,sources:[...d.sources,{source_kind:'bio_insight_result_version',source_id:resultInput.data!.id,sha256:resultInput.data!.manifest_sha256,role:'result',locator:{kind:'object'}}],config:{...d.config,result_source_id:resultInput.data!.id,...(resultInput.data!.summary.topic_method?{figure_type:'topic_'+String(resultInput.data!.summary.topic_method)}:{})}}))}>{t('采用当前固定结果作为绘图来源')}</button>}
<InsightSources projectId={projectId} active={active} value={draft.sources} onChange={selectSources}/>
    </>}
   </div>
   <div hidden={step!=='config'}>
    <nav className="analysis-page-tabs" aria-label={t('分析设置视图')}><button type="button" aria-pressed={configPanel==='parameters'} onClick={()=>setConfigPanel('parameters')}>{t('分析参数')}</button><button type="button" aria-pressed={configPanel==='settings'} onClick={()=>setConfigPanel('settings')}>{t('命名与输出')}</button></nav>
    <div hidden={configPanel!=='settings'}><p>{t('名称留空时按分析类型自动生成。')}</p><div className="insight-grid"><Field label="计划名称" value={draft.name} onChange={name=>{setDraft(d=>({...d,name}));setPreview(null)}}/><ConfigField config={draft.config} onChange={change} name="output_language" label="成果语言" options={{'zh-CN':'中文',en:'English'}}/></div></div>
    <div hidden={configPanel!=='parameters'}> {kind==='candidate'&&!bulkCandidate&&<Field label="候选任务类型" value={draft.config.schema_version===2?'evidence':'recipe'} onChange={v=>change(v==='evidence'?defaultEvidenceMatrix():defaultConfig('candidate'))}><option value="recipe">比较结果筛选配方</option><option value="evidence">固定候选与类型化外部证据</option></Field>}
 {kind==='comparison'&&<><Field label="比较数据类型" value={draft.config.schema_version===5?'single_cell_composition':draft.config.single_cell_selection?'single_cell_de':draft.config.schema_version===4?'microbiome':draft.config.schema_version===3?'qpcr':draft.config.schema_version===2?'sample':'spatial'} onChange={v=>change({...(v==='single_cell_composition'?defaultSingleCellComposition():v==='single_cell_de'?defaultSingleCellDE():v==='microbiome'?defaultMicrobiomeConfig():v==='qpcr'?defaultQpcrConfig():v==='sample'?defaultQuantitativeConfig():defaultConfig('comparison')),output_language:draft.config.output_language})}><option value="single_cell_composition">单细胞供者组成（描述／propeller）</option><option value="single_cell_de">同细胞类型供者差异表达</option><option value="spatial">{t('空间区域／供体比较')}</option><option value="sample">{t('bulk／蛋白／代谢样本比较')}</option><option value="qpcr">qPCR 逐孔长表</option><option value="microbiome">微生物组组成与多样性</option></Field><p>{t('切换数据类型会重置当前比较设计；固定来源保留，已保存版本不变。')}</p></>}{kind==='integration'&&<Field label="分析类型" value={draft.config.schema_version===2?'single_cell_topic':'integration'} onChange={v=>change({...v==='single_cell_topic'?defaultSingleCellTopic(initialProcessedId):defaultConfig('integration'),output_language:draft.config.output_language})}><option value="single_cell_topic">单细胞轨迹／调控／通讯</option><option value="integration">多组学与跨数据整合</option></Field>}
 {enrichmentFigure?<BulkEnrichmentFigureSetup {...p}/>:bulkEnrichment?<><ReadState {...enrichmentInput}/>
  <BulkEnrichmentSetup projectId={projectId} active={active&&step==='config'&&configPanel==='parameters'}
   result={enrichmentInput.data} onResources={selectEnrichmentResources} eligibleBackground={eligibleBackground} {...p}/></>
  :bulkFixed?<BulkPlanSettings projectId={projectId} active={active&&step==='config'&&configPanel==='parameters'} {...p}/>:kind==='integration'&&draft.config.schema_version===2?<SingleCellTopicSetup projectId={projectId} {...p}/>:kind==='integration'?<IntegrationSetup {...p}/>:kind==='feature_extract'?<FeatureExtractionSetup {...p}/>:kind==='comparison'&&draft.config.schema_version===4?<MicrobiomeSetup {...p}/>:kind==='comparison'&&draft.config.schema_version===3?<QpcrSetup {...p}/>:kind==='comparison'?<ComparisonSetup projectId={projectId} {...p}/>:kind==='result_import'?<ResultImportSetup {...p}/>:kind==='ora'||kind==='gsea_prerank'?<EnrichmentSetup {...p}/>:kind==='candidate'&&draft.config.schema_version===2?<EvidenceLinks projectId={projectId} allowRegistration={allowExternalEvidenceRegistration} {...p}/>:kind==='candidate'?<CandidateRecipe projectId={projectId} {...p}/>:<FigureSetup projectId={projectId} {...p}/>}</div>
    {issues.map(issue=><p role="alert" key={issue}>{t(issue)}</p>)}
   </div>
   <div hidden={step!=='review'}>
    <nav className="analysis-page-tabs" aria-label={t('分析检查视图')}><button type="button" aria-pressed={reviewPanel==='summary'} onClick={()=>setReviewPanel('summary')}>{t('检查摘要')}</button><button type="button" aria-pressed={reviewPanel==='technical'} onClick={()=>setReviewPanel('technical')}>{t('检查详情')}</button></nav>
    <div hidden={reviewPanel!=='summary'}><h3>{body.name}</h3><p>{t('已选 {count} 个来源',{count:draft.sources.length})} · {t(draft.config.output_language==='en'?'英文':'中文')}{savedPlan&&<> · {t(sameSaved&&savedPlan.decision==='confirmed'?'已确认':'草稿')}</>}</p>
    {reviewedBulk&&sameSaved&&savedPlan?.decision==='confirmed'&&!draft.config.continuous_transform&&Array.isArray(draft.config.covariates)&&draft.config.covariates.some((c: {kind?:string})=>c.kind==='continuous')&&<div className="warning-panel"><p>{t('此版本的连续协变量采用旧版缩放。重新预检并确认可生成使用新版缩放的方案。')}</p><button type="button" onClick={()=>change({...draft.config,continuous_transform:'centered_range_v2'})}>{t('重新审核新版缩放')}</button></div>}
    {initial&&initial.current_revision!==initial.revision&&<p role="status">{t('当前查看历史版本；保存需要先核对最新版本，不能隐式覆盖。')}</p>}
    <p>{t(runnable?'来源和参数未变，将使用已保存的分析设置。':bulk?'先预检并核对最终设计，再确认模型。确认后可单独启动计算。':bulkEnrichment?'先预检固定来源与资源兼容性，再运行富集。':bulkFixed?'按当前设置生成新版本，只读取已保存的来源。':'开始分析时会先检查并保存本次设置，已有结果保留。')}</p>
    {bulkEnrichment&&<><BulkEnrichmentBinding config={draft.config} source={enrichmentSource} result={enrichmentInput.data} eligibleBackground={eligibleBackground}/><ReadState {...enrichmentInput}/></>}
    <div className="intake-actions">
     <button type="button" disabled={!canSave} onClick={()=>void check()}>{t('预检当前设计')}</button>
     {bulk&&<button type="button" disabled={!allowNewAnalysis||!validPreview||runnable||reviewedBulk&&!currentPreview?.reviewed_design_sha256} onClick={()=>void confirmBulk()}>{t('确认并保存 Bulk 模型')}</button>}
     <button type="button" className="button-primary" disabled={!allowNewAnalysis||!canSave||!canStart} onClick={()=>void start()}>{t(bulkFigure||enrichmentFigure?'生成固定图件':bulkCandidate?'生成固定候选':bulkEnrichment?'运行固定富集':'开始分析')}</button>
    </div>
    {reviewDesign&&<section aria-label={t('设计预检')}><h3>{t(reviewDesign.executable?'设计预检可执行':'设计预检阻断')}</h3>
     <ul>{reviewDesign.blocking_reasons.map((reason,i)=><li key={i}>{t(typeof reason==='string'?reason:reason.message??reason.code??'')}</li>)}</ul>
     <DesignUnits value={reviewDesign.actual_units} cell={draft.config.schema_version===5||!!draft.config.single_cell_selection} singleCondition={draft.config.schema_version===5&&draft.config.mode==='descriptive'&&!!draft.config.numerator&&draft.config.numerator===draft.config.denominator}/>
     {bulkEnrichment&&<BulkEnrichmentCompatibility value={reviewDesign.enrichment_compatibility}/>}
     <BulkModelReview design={reviewDesign} sources={draft.sources}/>
     {reviewDesign.warnings?.map((warning,i)=><p className="warning-panel" key={i}>{warning}</p>)}
    </section>}
    {!currentPreview&&bulk&&sameSaved&&savedPlan?.decision==='confirmed'&&<>
     <DesignUnits value={savedPlan.design.actual_units}/>
     <BulkModelReview design={savedPlan.design} sources={draft.sources}/>
     {savedPlan.design.warnings?.map((warning,i)=><p className="warning-panel" key={i}>{warning}</p>)}
    </>}
    </div><div hidden={reviewPanel!=='technical'}>{preview&&<DataDetails title="当前设计预检详情" value={preview.design}/>} {initial&&<DataDetails title="该版本保存时的设计检查" value={initial.design}/>}<DataDetails title="当前计划固定来源与原配置" value={{sources:draft.sources,config:draft.config}}/></div>
   </div>
  </fieldset>
  {busy&&<p role="status">{t('正在核验固定来源，大文件可能需要数分钟。')} <button type="button" onClick={()=>{context.current={...context.current,generation:context.current.generation+1};request.current?.abort();operation.cancel();run.cancel();setBusy(false)}}>{t('取消等待')}</button></p>}{error&&<p role="alert">{t(error)}</p>}<IntentState operation={operation}/><IntentState operation={run}/>
  </div>
  <footer className="insight-editor-actions"><button type="button" disabled={locked||!canSave} onClick={()=>void saveOnly()}>{t('保存不可变草稿版本')}</button><span className="muted">{t('保存不会启动计算。')}</span><div>{step!=='sources'&&<button type="button" disabled={locked} onClick={()=>setStep(step==='review'?'config':'sources')}>{t('上一步')}</button>}{step!=='review'&&<button type="button" className="button-primary" disabled={locked||(step==='sources'?!draft.sources.length:!canSave)} onClick={()=>setStep(step==='sources'?'config':'review')}>{t(step==='sources'?'下一步：配置分析':'下一步：检查与运行')}</button>}</div></footer>
 </section>
}
export function InsightRun({projectId,runId,active,onResult,onPlan}:{projectId:string;runId:string;active:boolean;onResult:(id:string)=>void;onPlan?:(plan:string,version:string)=>void}){const{t}=useI18n(),read=useInsightRead<Run>(`${projectBase(projectId)}/bio-insight-runs/${encodeURIComponent(runId)}`,active,false,v=>['queued','running'].includes(v.task.status));return <section><h3>{t('固定计划后台运行')}</h3><ReadState {...read}/>{read.data&&<><p>{read.data.kind}</p><TaskStatus projectId={projectId} task={read.data.task}/>{read.data.plan_id&&onPlan&&<button type="button" onClick={()=>onPlan(read.data!.plan_id!,read.data!.plan_version_id)}>{t('打开此运行的固定计划')}</button>}{read.data.result_version_id&&<button type="button" onClick={()=>onResult(read.data!.result_version_id!)}>{t('打开已发布固定结果')}</button>}<p>{t('刷新或重新打开此运行只读取状态，不重新提交计算。')}</p></>}</section>}
