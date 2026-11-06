import {useEffect,useState} from 'react'
import {useI18n} from '../../shared/i18n'
import type {BioProcessed,BioRecipeParameters,BioRun} from './contracts'
import {bioRequest,projectBase} from './api'
export type RepeatContext={params:BioRecipeParameters;observation_map_version_id:string|null;design_version_id:string|null;repeat_allowed:boolean}
type Comparison={baseline:Record<string,unknown>;comparison:Record<string,unknown>;parameter_changes:Record<string,unknown>;cells:{baseline:number;comparison:number;common:number|null;jaccard:number|null};clusters:{adjusted_rand_index:number|null;common_labelled_cells:number};markers:{jaccard:number|null};independence:{status:string}}
type Props={projectId:string;result:BioProcessed;onRepeat?:(context:RepeatContext)=>void}
export default function SingleCellRobustness(props:Props){
 return <SingleCellRobustnessContent key={JSON.stringify([props.projectId,props.result.id])} {...props}/>
}
function SingleCellRobustnessContent({projectId,result,onRepeat}:Props){
 const {t}=useI18n()
 const number=(v:number|null)=>v===null?t('不适用'):v.toFixed(4)
 const [context,setContext]=useState<RepeatContext|null>(null)
 const params=context?.params
 const [seed,setSeed]=useState(String((params?.seed??42)+1)),[runs,setRuns]=useState<BioRun[]>([]),[selected,setSelected]=useState(''),[comparison,setComparison]=useState<Comparison|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true)
 useEffect(()=>{const controller=new AbortController()
  void (async()=>{try{const frozen=await bioRequest<RepeatContext>(`${projectBase(projectId)}/bio-processed-datasets/${encodeURIComponent(result.id)}/repeat-context`,{signal:controller.signal});if(!controller.signal.aborted){setContext(frozen);setSeed(String(frozen.params.seed+1))}let page=1,total=Infinity;const all:BioRun[]=[];while(all.length<total){const data=await bioRequest<{items:BioRun[];total:number}>(`${projectBase(projectId)}/bio-analysis-runs?page=${page++}&page_size=100`,{signal:controller.signal});all.push(...data.items);total=data.total;if(!data.items.length)break}if(!controller.signal.aborted)setRuns(all.filter(r=>r.task.status==='succeeded'&&r.result_source&&r.result_source.processed_dataset_version_id!==result.id))}catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:'无法读取已完成任务')}finally{if(!controller.signal.aborted)setLoading(false)}})()
  return()=>controller.abort()
 },[projectId,result.id])
 useEffect(()=>{if(!selected)return;const controller=new AbortController();void bioRequest<Comparison>(`${projectBase(projectId)}/bio-processed-datasets/${encodeURIComponent(result.id)}/robustness?comparison_id=${encodeURIComponent(selected)}`,{signal:controller.signal}).then(v=>{if(!controller.signal.aborted)setComparison(v)}).catch(e=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:'比较失败')});return()=>controller.abort()},[projectId,result.id,selected])
 const valid=seed.trim()!==''&&Number.isSafeInteger(Number(seed))&&Number(seed)>=0&&Number(seed)<=2147483647&&Number(seed)!==params?.seed
 return <section><h3>{t("稳健性与重复计算")}</h3><p>{t("比较已保存的实际结果；同供者拆分不能作为独立队列。不同来源、供者不相交仍需核对队列来源与研究设计。")}</p>
 {context&&!context.repeat_allowed&&<p>{t("亚群结果请返回原亚群流程重跑，不能按原始全量来源重跑。")}</p>}{onRepeat&&context?.repeat_allowed&&params&&<div><label>{t("重复计算随机种子")}<input type="number" value={seed} onChange={e=>setSeed(e.target.value)}/></label><button disabled={!valid} onClick={()=>onRepeat({...context,params:{...params,seed:Number(seed)}})}>{t("用此参数打开分析方案")}</button><p>{t('原种子：{seed}。其余参数沿用本结果；在参数表单启动新任务，保留旧结果。',{seed:params.seed})}</p></div>}
 {loading?<p>{t("正在读取已完成任务…")}</p>:runs.length?<label>{t("对照结果")}<select value={selected} onChange={e=>{setComparison(null);setError('');setSelected(e.target.value)}}><option value="">{t("选择已完成任务")}</option>{runs.map(r=><option key={r.id} value={r.result_source!.processed_dataset_version_id}>{t('任务 {task} · 来源 {source}',{task:r.id,source:r.raw_source.dataset_version_id})}</option>)}</select></label>:<p>{t("尚无其他已完成结果。")}</p>}
 {error&&<p role="alert">{t(error)}</p>}{comparison&&<div><p>{t('基线保留细胞：{baseline}；对照：{comparison}；共同细胞：{common}',{baseline:comparison.cells.baseline,comparison:comparison.cells.comparison,common:comparison.cells.common??t('不同来源不匹配条码')})}</p><p>{t('细胞 Jaccard：{cells}；共同已标记细胞 ARI：{ari}（{count} 个细胞）；导出 top marker 基因并集 Jaccard：{markers}',{cells:number(comparison.cells.jaccard),ari:number(comparison.clusters.adjusted_rand_index),count:comparison.clusters.common_labelled_cells,markers:number(comparison.markers.jaccard)})}</p><p>{t('队列判定：{status}。以上为描述性比较，不代表生物学验证；ARI 仅覆盖共同保留且有标签的细胞，marker 并集未进行簇对应。',{status:t(({same_source:'同一来源（含亚群/参数对照）',overlapping_donors:'供者重叠',unknown_donors:'供者信息不完整',independence_unverified:'独立性尚未验证'} as Record<string,string>)[comparison.independence.status])})}</p><details><summary>{t("参数差异")}</summary><pre>{JSON.stringify(comparison.parameter_changes,null,2)}</pre></details><details><summary>{t("来源、任务与供者身份")}</summary><pre>{JSON.stringify({baseline:comparison.baseline,comparison:comparison.comparison},null,2)}</pre></details></div>}
 <p>{t("GENIE3 两种子稳定性保留在已有调控网络专题结果中。")}</p></section>
}
