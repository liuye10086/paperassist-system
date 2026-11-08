import {useEffect,useLayoutEffect,useRef,useState} from 'react'
import {apiError,useI18n} from '../../shared/i18n'
import {statusNames,type TaskView} from '../tasks/taskTypes'
import {projectBase} from './api'
import type {AnnotationDraft} from './BioAnnotationEditor'
import {BioJson,BioSpatialMembers,BioWriteStatus} from './BioSpatialShared'
import {sameProcessedBioSource,type BioAnnotation,type BioProcessed,type ProcessedBioSource} from './spatialContracts'
import {useBioRead} from './spatialHooks'
import useBioWrite from './useBioWrite'

type Reference={reference_id:string;species:string;gene_id_type:string;label_level?:string;label_levels?:string[];license?:string;available:boolean;reason?:string|null;source?:unknown;version?:string}
type AnnotationRun={id:string;name:string;parent_processed_source:ProcessedBioSource;reference_id:string;task:TaskView;result:{set_id:string;version_id:string}|null}
const pending=(run:AnnotationRun)=>['queued','running'].includes(run.task.status)
export function SingleCellCandidateTask({projectId,result,onPublished,allowNewAnalysis=true}:{projectId:string;result:BioProcessed;onPublished:()=>void;allowNewAnalysis?:boolean}){
 const {t}=useI18n(),base=projectBase(projectId),[reference,setReference]=useState(''),[newRun,setNewRun]=useState<AnnotationRun|null>(null)
 const refs=useBioRead<{items:Reference[]}>(`${base}/bio-single-cell-references`)
 const runs=useBioRead<{items:AnnotationRun[]}>(`${base}/bio-processed-datasets/${encodeURIComponent(result.id)}/annotation-runs`,v=>v.items.some(pending))
 const [recoveredId,setRecoveredId]=useState('')
 const writer=useBioWrite<AnnotationRun>(projectId,'annotation_run',v=>{setNewRun(v);runs.reload()},v=>setRecoveredId(v.id))
 const selected=refs.value?.items.find(v=>v.reference_id===reference)
 const listed=[...(runs.value?.items??[]),...(newRun&&!runs.value?.items.some(v=>v.id===newRun.id)?[newRun]:[])]
 const blocked=writer.busy||writer.unknown||!writer.valid||!refs.valid
 return <section><h4>{t('SingleR 参考候选注释')}</h4><p>{t('使用已安装的本地参考独立运行；保存分数、pruned 标签、参考来源与日志。候选不等于人工确认。')}</p>
  {refs.error&&<p role="alert">{t(refs.error)}</p>}{runs.error&&<p role="alert">{t(runs.error)}</p>}
  <fieldset disabled={blocked}><legend>{t('选择参考')}</legend><label>{t('本地参考')}<select value={reference} onChange={e=>setReference(e.target.value)}><option value="">{t('请选择可用参考')}</option>{refs.value?.items.map(v=><option key={v.reference_id} value={v.reference_id} disabled={!v.available}>{v.reference_id} · {v.species} · {v.available?t('可用'):t('不可用')}</option>)}</select></label>
   {selected&&<><p>{selected.species} · {selected.gene_id_type} · {selected.label_level??(selected.label_levels?.includes('main')?'main':'—')} · {selected.version}</p><BioJson value={selected.source}/>{selected.license&&<p>{selected.license}</p>}{selected.reason&&<p>{selected.reason}</p>}</>}
   {refs.value&&!refs.value.items.some(v=>v.available)&&<p>{t('暂无可用本地参考，请核对参考安装与物种/基因标识；不会联网获取或自动替代。')}</p>}
   <button type="button" disabled={!allowNewAnalysis||!selected?.available} onClick={()=>allowNewAnalysis&&void writer.submit(`${base}/bio-single-cell-annotation-runs`,{name:'SingleR candidate annotation',parent_processed_source:result.source,reference_id:reference,seed:0})}>{t('运行 SingleR 候选注释')}</button>
  </fieldset><BioWriteStatus writer={writer}/>
  <button type="button" onClick={()=>{refs.reload();runs.reload()}}>{t('刷新参考与候选任务')}</button>
  {listed.map(run=><CandidateRun key={run.id} projectId={projectId} result={result} runId={run.id} initial={run} onPublished={onPublished}/>)}
  {recoveredId&&!listed.some(v=>v.id===recoveredId)&&<CandidateRun key={recoveredId} projectId={projectId} result={result} runId={recoveredId} onPublished={onPublished}/>}
 </section>
}
function CandidateRun({projectId,result,runId,initial,onPublished}:{projectId:string;result:BioProcessed;runId:string;initial?:AnnotationRun;onPublished:()=>void}){
 const {t}=useI18n(),read=useBioRead<AnnotationRun>(`${projectBase(projectId)}/bio-single-cell-annotation-runs/${encodeURIComponent(runId)}`,pending),run=read.value??initial
 const published=useRef(''),callback=useRef(onPublished)
 useLayoutEffect(()=>{callback.current=onPublished},[onPublished])
 const matches=!!run&&run.id===runId&&sameProcessedBioSource(run.parent_processed_source,result.source)&&run.task.project_id===projectId
 useEffect(()=>{if(matches&&run?.result?.version_id&&published.current!==run.result.version_id){published.current=run.result.version_id;callback.current()}},[matches,run?.result?.version_id])
 if(run&&!matches)return <p role="alert">{t('固定来源身份不匹配，请重新打开。')}</p>
 return <section>{read.error&&<p role="alert">{t(read.error)}</p>}{run&&<><p>{run.name||'SingleR'} · {run.id} · {t(statusNames[run.task.status])} · {run.task.phase}</p>{run.task.reason_code&&<p>{run.task.reason_code}</p>}{run.task.error_code&&<p role="alert">{t(apiError({code:run.task.error_code},'任务暂未完成，请查看处理说明。'))}</p>}
  <a href={`#project=${encodeURIComponent(projectId)}&section=tasks&task=${encodeURIComponent(run.task.id)}`}>{t('查看候选任务进度与操作')}</a>
  {run.result&&<p>{t('候选已保存，请在下方核对并选择采纳。')}</p>}</>}
  <button type="button" onClick={read.reload}>{t('刷新候选任务')}</button>
 </section>
}
export function SingleCellCandidateReview({projectId,candidate,onAdopt,canAdopt=true}:{projectId:string;candidate:BioAnnotation;onAdopt:(draft:AnnotationDraft)=>void;canAdopt?:boolean}){
 const {t}=useI18n(),[selected,setSelected]=useState<string[]>([]),[page,setPage]=useState(0)
 const assignments=candidate.assignments,labels=candidate.labels.filter(label=>assignments.some(a=>a.label_id===label.id))
 function adopt(){
  const labels:AnnotationDraft['labels']=[],evidence:AnnotationDraft['evidence']=[]
  for(const label of candidate.labels.filter(v=>selected.includes(v.id))){
   for(const status of ['proposed','uncertain','unknown'] as const){
    const cells=assignments.filter(a=>a.label_id===label.id&&(a.status==='unknown'?'unknown':a.status==='uncertain'||!a.pruned_label?'uncertain':'proposed')===status).map(a=>a.barcode)
    if(!cells.length)continue
    const id=crypto.randomUUID();labels.push({id,name:label.name,status,note:'SingleR candidate; researcher review pending',cluster_ids:[],cell_ids:cells})
    evidence.push({label_id:id,kind:'reference',analysis_artifact_id:null,file_id:null,note:`SingleR candidate version ${candidate.id}; ${JSON.stringify(candidate.algorithm??{})}`})
   }
  }
  if(labels.length)onAdopt({name:`${candidate.name||'SingleR'} · manual review`,labels,evidence,regions:[],overlap_policy:'ambiguity'})
 }
 return <section><h4>{candidate.name||t('SingleR 候选结果')} · v{candidate.version}</h4><BioJson value={candidate.algorithm}/>
  <p>{t('显示逐 cell 候选、pruned 结果与分数差；完整 score 矩阵、参考元信息和工具日志见下载。')}</p>
  <div className="table-scroll"><table><thead><tr>{['cell ID','candidate','pruned','delta.next','delta.median','状态'].map(v=><th key={v}>{t(v)}</th>)}</tr></thead><tbody>{assignments.slice(page*50,(page+1)*50).map(a=><tr key={a.barcode}><td>{a.barcode}</td><td>{a.candidate_label??'—'}</td><td>{a.pruned_label??t('未知 / pruned')}</td><td>{a.delta_next??'—'}</td><td>{a.delta_median??'—'}</td><td>{t(a.status==='uncertain'?'不确定':a.status==='unknown'?'未知':'候选')}</td></tr>)}</tbody></table></div>
  <p>{assignments.length} cells · {page+1}/{Math.max(1,Math.ceil(assignments.length/50))}</p><button type="button" disabled={page===0} onClick={()=>setPage(v=>v-1)}>{t('上一页')}</button><button type="button" disabled={(page+1)*50>=assignments.length} onClick={()=>setPage(v=>v+1)}>{t('下一页')}</button>
  <BioSpatialMembers projectId={projectId} members={candidate.members??[]}/>
  <fieldset><legend>{t('选择要加入人工草稿的候选')}</legend>{labels.map(label=><label key={label.id}><input type="checkbox" checked={selected.includes(label.id)} onChange={e=>setSelected(v=>e.target.checked?[...v,label.id]:v.filter(id=>id!==label.id))}/>{t('采纳候选 {name}',{name:label.name})}</label>)}</fieldset>
  <button type="button" disabled={!selected.length||!canAdopt} onClick={adopt}>{t('将所选候选加入人工草稿')}</button>{!canAdopt&&<p>{t('请先保存当前人工草稿后再采纳其他候选。')}</p>}<p>{t('草稿保留 proposed / uncertain / unknown 状态；需人工保存，未默认确认为细胞身份。')}</p>
 </section>
}
