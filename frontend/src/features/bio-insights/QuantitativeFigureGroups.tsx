import {useEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError,useI18n} from '../../shared/i18n'
import {ConfigField,DataDetails,Field,SourceChoice,Toggle,type ConfigProps} from './InsightShared'
import {strings,text} from './state'
import {readQuantitativeSamples,type SampleGroup,type SampleRow} from './quantitative'
export default function QuantitativeFigureGroups({projectId,config,onChange,sources}:ConfigProps&{projectId:string}){
 const{t}=useI18n(),[rows,setRows]=useState<SampleRow[]>([]),[field,setField]=useState('condition'),[value,setValue]=useState(''),[label,setLabel]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),controller=useRef<AbortController|null>(null),valid=useRef(true),pid=text(config.processed_source_id),groups=(config.sample_groups??[]) as SampleGroup[],distribution=config.figure_type==='distribution',signature=JSON.stringify(sources)
 useEffect(()=>{controller.current?.abort();controller.current=null;queueMicrotask(()=>{setRows([]);setBusy(false);setValue('')});return()=>controller.current?.abort()},[pid,signature])
 useEffect(()=>onApiSessionChanged(()=>{valid.current=false;controller.current?.abort();setRows([])}),[])
 async function load(){if(controller.current||!valid.current)return;const c=new AbortController();controller.current=c;setBusy(true);setError('');try{const all=await readQuantitativeSamples(projectId,sources.filter(s=>s.source_id===pid&&s.source_kind==='bio_processed_dataset_version'),c.signal);if(!c.signal.aborted&&valid.current)setRows(all)}catch(e){if(!c.signal.aborted)setError(safeError(e,'读取固定样本失败。'))}finally{if(controller.current===c){controller.current=null;setBusy(false)}}}
 const fields=[...new Set(['condition','group','donor','pair_id','batch','sample_role',...rows.flatMap(r=>Object.keys(r).filter(k=>!['sample_id','processed_version_id','retained','canonical_dataset_id'].includes(k)&&typeof r[k]!=='object'))])],chosen=rows.filter(r=>r.retained!==false&&String(r[field]??'')===value)
 return <fieldset><legend>{t('真实样本数值与固定图件组')}</legend><SourceChoice config={config} onChange={next=>onChange({...next,sample_groups:[],expression_groups:[]})} sources={sources} name="processed_source_id" label="真实定量处理版本" role="processed"/>
  <ConfigField config={config} onChange={onChange} name="analysis_layer" label="图件数值层" options={{analysis:'analysis（实际分析尺度）',display:'display（实际显示尺度）'}}/>
  <Field label="固定特征 ID（分布图须恰好一个，每行一个）" value={strings(config.feature_ids).join('\n')} type="textarea" onChange={v=>onChange({...config,feature_ids:v.split(/\r?\n/).map(x=>x.trim()).filter(Boolean)})}/>
  {!distribution&&<Toggle label="显式按特征 z-score（仅改变热图显示）" value={config.z_score===true} onChange={v=>onChange({...config,z_score:v})}/>}
  <p>{t(distribution?'箱线与全部实测点来自一个固定特征；保留缺失、各组实际 n 和原尺度。':'热图按单个样本显示实际数值；不自动平均或取对数，缺失保留。留空特征列表时采用固定结果排名与 Top N。')}</p>
  <button type="button" disabled={!pid||busy} onClick={()=>void load()}>{t('读取热图／分布图固定样本')}</button>{busy&&<p role="status">{t('正在读取固定样本……')}<button type="button" onClick={()=>{controller.current?.abort();controller.current=null;setBusy(false)}}>{t('取消等待')}</button></p>}{error&&<p role="alert">{t(error)}</p>}
  <Field label="图件样本分组字段" value={field} onChange={v=>{setField(v);setValue('')}}>{fields.map(f=><option key={f}>{f}</option>)}</Field><Field label="图件样本分组值" value={value} onChange={setValue}><option value="">{t('请选择')}</option>{[...new Set(rows.filter(r=>r.retained!==false).map(r=>String(r[field]??'')))].filter(Boolean).map(v=><option key={v}>{v}</option>)}</Field><Field label="图件样本组名称" value={label} onChange={setLabel}/>
  <button type="button" disabled={!value||!chosen.length||groups.length>=30} onClick={()=>onChange({...config,sample_groups:[...groups,{label:label||value,sample_keys:chosen.map(({sample_id,processed_version_id})=>({sample_id,processed_version_id}))}],expression_groups:[],analysis_layer:config.analysis_layer??'analysis',z_score:config.z_score??false})}>{t('加入图件样本组')}</button>
  {groups.map((g,i)=><section key={i}><p>{g.label} · {g.sample_keys.length} {t('样本')} <button type="button" onClick={()=>onChange({...config,sample_groups:groups.filter((_,j)=>i!==j)})}>{t('移除')}</button></p><DataDetails title="固定样本键" value={g.sample_keys}/></section>)}
 </fieldset>
}
