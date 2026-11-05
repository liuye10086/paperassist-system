import type {AnalysisEntryIntent} from '../projects/analysisViews'
import {useEffect,useRef,useState} from 'react'
import {safeError,useI18n} from '../../shared/i18n'
import {getApiUserId,onApiSessionChanged} from '../../shared/api/client'
import useDraftLeaveGuard,{type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {insightRequest,jsonRequest,projectBase} from './api'
import {useInsightDraft,useInsightIntent,useInsightRead} from './hooks'
import {kindLabels,type Config,type Design,type InsightKind,type Plan,type Source,type Run,type Result} from './contracts'
import {buildPlan,defaultConfig,planIssues} from './state'
import InsightSources from './InsightSources'
import ComparisonSetup from './ComparisonSetup'
import {defaultQuantitativeConfig} from './quantitative'
import QpcrSetup,{defaultQpcrConfig} from './QpcrSetup'
import FeatureExtractionSetup from './FeatureExtractionSetup'
import IntegrationSetup from './IntegrationSetup'
import EvidenceLinks,{defaultEvidenceMatrix} from './EvidenceLinks'
import MicrobiomeSetup,{defaultMicrobiomeConfig} from './MicrobiomeSetup'
import ResultImportSetup from './ResultImportSetup'
import EnrichmentSetup from './EnrichmentSetup'
import CandidateRecipe from './CandidateRecipe'
import FigureSetup from './FigureSetup'
import {Field,ConfigField,DataDetails,IntentState,ReadState,TaskStatus,DesignUnits} from './InsightShared'
type Draft={name:string;config:Config;sources:Source[]}
export default function InsightPlanEditor({projectId,kind,active,initial,initialProcessedId,initialResultId,entryIntent,onSaved,onRun,registerLeaveGuard}:{projectId:string;kind:InsightKind;active:boolean;initial?:Plan|null;initialProcessedId?:string;initialResultId?:string;entryIntent?:AnalysisEntryIntent;onSaved:(v:Plan)=>void;onRun:(v:Run)=>void;registerLeaveGuard?:RegisterLeaveGuard}){
 const{t}=useI18n(),ordinaryScope=`${kind}:${initialProcessedId??initialResultId??''}`,specialIntent=entryIntent==='evidence'&&kind==='candidate'||entryIntent==='qpcr'&&kind==='comparison'?entryIntent:undefined,specialScope=specialIntent?`${ordinaryScope}:${specialIntent}`:ordinaryScope,[explicitScope,setExplicitScope]=useState('')
 const stored=(type:'draft'|'request',candidate:string,operation='plan')=>{try{return !!sessionStorage.getItem(`paperassist.bio-insight.${type}:${getApiUserId()??'anonymous'}:${projectId}:${operation}:${candidate}`)}catch{return false}}
 const pending=(candidate:string)=>stored('request',candidate)||stored('request',candidate,'run')
 const scope=initial?.id??(!specialIntent?ordinaryScope:pending(ordinaryScope)?ordinaryScope:pending(specialScope)||explicitScope===specialScope||stored('draft',specialScope)?specialScope:stored('draft',ordinaryScope)?ordinaryScope:specialScope),usingExistingOrdinary=!initial&&!!specialIntent&&scope===ordinaryScope,usingSpecial=!initial&&!!specialIntent&&scope===specialScope
 const[draft,setDraft]=useInsightDraft<Draft>(projectId,`plan:${scope}`,()=>({name:initial?.name??'',config:initial?.config??(usingSpecial&&specialIntent==='evidence'?defaultEvidenceMatrix():usingSpecial&&specialIntent==='qpcr'?defaultQpcrConfig():defaultConfig(kind)),sources:initial?.sources??[]})),[preview,setPreview]=useState<{signature:string;design:Design}|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),operation=useInsightIntent<Plan>(projectId,'plan',scope),run=useInsightIntent<Run>(projectId,'run',scope),request=useRef<AbortController|null>(null),alive=useRef(true),seenPlan=useRef(''),seenRun=useRef(''),base=projectBase(projectId)
 const revision=initial?.revision??0,body=buildPlan(draft.name.trim()||t(kindLabels[kind]),draft.config,draft.sources,revision,'draft'),signature=JSON.stringify(body),sameSaved=!!initial&&JSON.stringify(body.config)===JSON.stringify(initial.config)&&JSON.stringify(body.sources)===JSON.stringify(initial.sources.map(s=>({source_kind:s.source_kind,source_id:s.source_id,sha256:s.sha256,role:s.role,locator:s.locator})))&&body.name===initial.name,locked=busy||operation.busy||operation.unknown||run.busy||run.unknown||!operation.valid||!run.valid
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;request.current?.abort()}},[])
 useEffect(()=>onApiSessionChanged(()=>{alive.current=false;request.current?.abort();setPreview(null)}),[])
 useEffect(()=>{if(!active){request.current?.abort();queueMicrotask(()=>setBusy(false))}},[active])
 useEffect(()=>{if(operation.value&&operation.value.id!==seenPlan.current){seenPlan.current=operation.value.id;onSaved(operation.value)}},[operation.value,onSaved])
 useEffect(()=>{if(run.value&&run.value.id!==seenRun.current){seenRun.current=run.value.id;onRun(run.value)}},[run.value,onRun])
 // Draft edits are already persisted by project and version; navigation does not discard them.
 useDraftLeaveGuard(registerLeaveGuard,false,locked||operation.unknown||run.unknown)
 const sources=useInsightRead<{items:Source[]}>(initialProcessedId&&!draft.sources.length?`${base}/bio-insights/sources?source_kind=bio_processed_dataset_version&page=1&page_size=100`:'',active&&!!initialProcessedId)
 const resultInput=useInsightRead<Result>(initialResultId?`${base}/bio-insight-results/${initialResultId}`:'',active&&!!initialResultId,true)
 function change(config:Config){setDraft(d=>({...d,config}));setPreview(null)}
 async function check(){if(request.current||locked)return;const c=new AbortController();request.current=c;setBusy(true);setError('');setPreview(null);try{const design=await insightRequest<Design>(`${base}/bio-insight-plans/preview`,{...jsonRequest(body),signal:c.signal},true);if(alive.current&&!c.signal.aborted)setPreview({signature,design})}catch(cause){if(alive.current&&!c.signal.aborted)setError(safeError(cause,'设计预检失败，请核对固定来源。'))}finally{if(request.current===c){request.current=null;if(alive.current)setBusy(false)}}}
 const p={config:draft.config,onChange:change,sources:draft.sources},issues=planIssues(draft.config),validPreview=preview?.signature===signature&&preview.design.executable,canSave=!!draft.sources.length&&!issues.length
 const [step,setStep]=useState<'sources'|'config'|'review'>(initial?.decision==='confirmed'?'review':'sources'),[configPanel,setConfigPanel]=useState('parameters'),[reviewPanel,setReviewPanel]=useState('summary')
 const runnable=!!initial&&sameSaved&&initial.decision==='confirmed'&&initial.design.executable&&initial.current_revision===initial.revision&&!issues.length
 const [stepScope,setStepScope]=useState(scope);if(stepScope!==scope){setStepScope(scope);setStep(initial?.decision==='confirmed'?'review':'sources')}
 return <section className="insight-editor">
  <nav className="analysis-sequence" aria-label={t('分析配置顺序')}>{([['sources','选择数据'],['config','配置分析'],['review','检查与运行']] as const).map(([key,label],index)=><button type="button" key={key} aria-current={step===key?'step':undefined} disabled={locked||key==='config'&&!draft.sources.length||key==='review'&&!canSave} onClick={()=>setStep(key)}><span aria-hidden="true">{index+1}. </span>{t(label)}</button>)}</nav>
  <div className="insight-editor-body">
   {usingExistingOrdinary&&<div><p>{t('已保留现有草稿，入口配置尚未应用。')}</p><button type="button" disabled={locked||pending(scope)} onClick={()=>{if(locked||pending(scope))return;setPreview(null);setExplicitScope(specialScope)}}>{t(specialIntent==='evidence'?'另建本次证据计划':'另建本次 qPCR 计划')}</button></div>}{usingSpecial&&<p>{t(specialIntent==='evidence'?'当前为本次证据计划草稿。':'当前为本次 qPCR 计划草稿。')}</p>}
  <fieldset disabled={locked} className="insight-editor-fields">
   <div hidden={step!=='sources'}>
    <h3>{t('选择本次分析的数据')}</h3><p className="muted">{t('选用已上传或已处理的固定版本，后续配置沿用这些来源。')}</p>
    {initialProcessedId&&!draft.sources.some(s=>s.source_id===initialProcessedId)&&<button type="button" disabled={!sources.data?.items.some(s=>s.source_id===initialProcessedId)} onClick={()=>{const s=sources.data?.items.find(s=>s.source_id===initialProcessedId);if(s)setDraft(d=>({...d,sources:[...d.sources,{...s,role:'processed',locator:{kind:'object'}}]}))}}>{t('采用入口的固定处理版本')}</button>}
 {resultInput.data&&!draft.sources.some(s=>s.source_id===initialResultId)&&<button type="button" onClick={()=>setDraft(d=>({...d,sources:[...d.sources,{source_kind:'bio_insight_result_version',source_id:resultInput.data!.id,sha256:resultInput.data!.manifest_sha256,role:'result',locator:{kind:'object'}}],config:{...d.config,result_source_id:resultInput.data!.id}}))}>{t('采用当前固定结果作为绘图来源')}</button>}
<InsightSources projectId={projectId} active={active} value={draft.sources} onChange={sources=>{setDraft(d=>({...d,sources}));setPreview(null)}}/>
   </div>
   <div hidden={step!=='config'}>
    <nav className="analysis-page-tabs" aria-label={t('分析设置视图')}><button type="button" aria-pressed={configPanel==='parameters'} onClick={()=>setConfigPanel('parameters')}>{t('分析参数')}</button><button type="button" aria-pressed={configPanel==='settings'} onClick={()=>setConfigPanel('settings')}>{t('命名与输出')}</button></nav>
    <div hidden={configPanel!=='settings'}><p>{t('名称留空时按分析类型自动生成。')}</p><div className="insight-grid"><Field label="计划名称" value={draft.name} onChange={name=>{setDraft(d=>({...d,name}));setPreview(null)}}/><ConfigField config={draft.config} onChange={change} name="output_language" label="成果语言" options={{'zh-CN':'中文',en:'English'}}/></div></div>
    <div hidden={configPanel!=='parameters'}> {kind==='candidate'&&<Field label="候选任务类型" value={draft.config.schema_version===2?'evidence':'recipe'} onChange={v=>change(v==='evidence'?defaultEvidenceMatrix():defaultConfig('candidate'))}><option value="recipe">比较结果筛选配方</option><option value="evidence">固定候选与类型化外部证据</option></Field>}
 {kind==='comparison'&&<><Field label="比较数据类型" value={draft.config.schema_version===4?'microbiome':draft.config.schema_version===3?'qpcr':draft.config.schema_version===2?'sample':'spatial'} onChange={v=>change({...(v==='microbiome'?defaultMicrobiomeConfig():v==='qpcr'?defaultQpcrConfig():v==='sample'?defaultQuantitativeConfig():defaultConfig('comparison')),output_language:draft.config.output_language})}><option value="spatial">{t('空间区域／供体比较')}</option><option value="sample">{t('bulk／蛋白／代谢样本比较')}</option><option value="qpcr">qPCR 逐孔长表</option><option value="microbiome">微生物组组成与多样性</option></Field><p>{t('切换数据类型会重置当前比较设计；固定来源保留，已保存版本不变。')}</p></>}{kind==='integration'?<IntegrationSetup {...p}/>:kind==='feature_extract'?<FeatureExtractionSetup {...p}/>:kind==='comparison'&&draft.config.schema_version===4?<MicrobiomeSetup {...p}/>:kind==='comparison'&&draft.config.schema_version===3?<QpcrSetup {...p}/>:kind==='comparison'?<ComparisonSetup projectId={projectId} {...p}/>:kind==='result_import'?<ResultImportSetup {...p}/>:kind==='ora'||kind==='gsea_prerank'?<EnrichmentSetup {...p}/>:kind==='candidate'&&draft.config.schema_version===2?<EvidenceLinks projectId={projectId} {...p}/>:kind==='candidate'?<CandidateRecipe projectId={projectId} {...p}/>:<FigureSetup projectId={projectId} {...p}/>}</div>
    {issues.map(issue=><p role="alert" key={issue}>{t(issue)}</p>)}
   </div>
   <div hidden={step!=='review'}>
    <nav className="analysis-page-tabs" aria-label={t('分析检查视图')}><button type="button" aria-pressed={reviewPanel==='summary'} onClick={()=>setReviewPanel('summary')}>{t('检查摘要')}</button><button type="button" aria-pressed={reviewPanel==='technical'} onClick={()=>setReviewPanel('technical')}>{t('检查详情')}</button></nav>
    <div hidden={reviewPanel!=='summary'}><h3>{body.name}</h3><p>{t('已选 {count} 个来源',{count:draft.sources.length})} · {t(draft.config.output_language==='en'?'英文':'中文')}{initial&&<> · v{initial.revision} · {t(initial.decision==='confirmed'?'已确认':'草稿')}</>}</p>
    {initial&&initial.current_revision!==initial.revision&&<p role="status">{t('当前查看历史版本；保存需要先核对最新版本，不能隐式覆盖。')}</p>}
    {runnable?<p>{t('该版本已通过检查并确认，可以手动启动分析。')}</p>:<p>{t('先检查配置，再确认保存；只有已确认且未修改的版本可以启动。')}</p>}
    <div className="intake-actions"><button type="button" disabled={!canSave} onClick={()=>void check()}>{t('预检当前设计')}</button><button type="button" disabled={!canSave||!validPreview} onClick={()=>void operation.submit(initial?`${base}/bio-insight-plans/${initial.plan_id}/versions`:`${base}/bio-insight-plans`,{...body,decision:'confirmed'})}>{t('确认并保存新版本')}</button><button type="button" className="button-primary" disabled={!runnable} onClick={()=>initial&&void run.submit(`${base}/bio-insight-runs`,{plan_version_id:initial.id,expected_plan_revision:initial.revision,source_digest:initial.source_digest})}>{t('提交已确认版本后台计算')}</button></div>
    {preview&&<section aria-label={t('设计预检')}><h3>{t(preview.design.executable?'设计预检可执行':'设计预检阻断')}</h3><ul>{preview.design.blocking_reasons.map((reason,i)=><li key={i}>{typeof reason==='string'?reason:reason.message??reason.code}</li>)}</ul><DesignUnits value={preview.design.actual_units}/></section>}
    </div><div hidden={reviewPanel!=='technical'}>{preview&&<DataDetails title="当前设计预检详情" value={preview.design}/>} {initial&&<DataDetails title="该版本保存时的设计检查" value={initial.design}/>}<DataDetails title="当前计划固定来源与原配置" value={{sources:draft.sources,config:draft.config}}/></div>
   </div>
  </fieldset>
  {busy&&<p role="status">{t('正在核验固定来源，大文件可能需要数分钟。')} <button type="button" onClick={()=>{request.current?.abort();request.current=null;setBusy(false)}}>{t('取消等待')}</button></p>}{error&&<p role="alert">{t(error)}</p>}<IntentState operation={operation}/><IntentState operation={run}/>
  </div>
  <footer className="insight-editor-actions"><button type="button" disabled={locked||!canSave} onClick={()=>void operation.submit(initial?`${base}/bio-insight-plans/${initial.plan_id}/versions`:`${base}/bio-insight-plans`,body)}>{t('保存不可变草稿版本')}</button><span className="muted">{t('保存不会启动计算。')}</span><div>{step!=='sources'&&<button type="button" disabled={locked} onClick={()=>setStep(step==='review'?'config':'sources')}>{t('上一步')}</button>}{step!=='review'&&<button type="button" className="button-primary" disabled={locked||(step==='sources'?!draft.sources.length:!canSave)} onClick={()=>setStep(step==='sources'?'config':'review')}>{t(step==='sources'?'下一步：配置分析':'下一步：检查与运行')}</button>}</div></footer>
 </section>
}
export function InsightRun({projectId,runId,active,onResult,onPlan}:{projectId:string;runId:string;active:boolean;onResult:(id:string)=>void;onPlan?:(plan:string,version:string)=>void}){const{t}=useI18n(),read=useInsightRead<Run>(`${projectBase(projectId)}/bio-insight-runs/${encodeURIComponent(runId)}`,active,false,v=>['queued','running'].includes(v.task.status));return <section><h3>{t('固定计划后台运行')}</h3><ReadState {...read}/>{read.data&&<><p>{read.data.kind}</p><TaskStatus projectId={projectId} task={read.data.task}/>{read.data.plan_id&&onPlan&&<button type="button" onClick={()=>onPlan(read.data!.plan_id!,read.data!.plan_version_id)}>{t('打开此运行的固定计划')}</button>}{read.data.result_version_id&&<button type="button" onClick={()=>onResult(read.data!.result_version_id!)}>{t('打开已发布固定结果')}</button>}<p>{t('刷新或重新打开此运行只读取状态，不重新提交计算。')}</p></>}</section>}
