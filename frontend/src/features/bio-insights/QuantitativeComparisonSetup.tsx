import {useEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError,useI18n} from '../../shared/i18n'
import {ConfigField,DataDetails,Field,Toggle,type ConfigProps} from './InsightShared'
import {text} from './state'
import {bulkModelDefaults,newSampleContrast,readQuantitativeSamples,sampleKey,type SampleContrast,type SampleCovariate,type SampleKey,type SampleRow} from './quantitative'

export default function QuantitativeComparisonSetup({projectId,config,onChange,sources}:ConfigProps&{projectId:string}){
 const{t}=useI18n(),[rows,setRows]=useState<SampleRow[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[field,setField]=useState('condition'),[value,setValue]=useState(''),[index,setIndex]=useState(0),[groupIndex,setGroupIndex]=useState(0),[manual,setManual]=useState(''),[processed,setProcessed]=useState(''),controller=useRef<AbortController|null>(null),valid=useRef(true)
 const signature=JSON.stringify(sources),contrasts=config.contrasts as SampleContrast[]
 const current=contrasts[index]??contrasts[0],group=current.groups[groupIndex]??current.groups[0]
 const counts=config.mode==='bulk_counts',reviewed=counts&&config.bulk_model==='shared_wald_v1'
 const multiple=config.design==='multiple',paired=config.design==='paired',p={config,onChange}
 const picks=sources.filter(s=>s.source_kind==='bio_processed_dataset_version')
 const covariates=(Array.isArray(config.covariates)?config.covariates:[]) as SampleCovariate[]
 const [scale,setScale]=useState<{namespace?:string;reference_version?:string;species_taxon_id?:number|null}|null>(null)
 useEffect(()=>{controller.current?.abort();controller.current=null;queueMicrotask(()=>{setRows([]);setScale(null);setBusy(false)});return()=>controller.current?.abort()},[projectId,signature])
 useEffect(()=>onApiSessionChanged(()=>{valid.current=false;controller.current?.abort();setRows([])}),[])
 function updateContrast(next:SampleContrast){onChange({...config,contrasts:contrasts.map((c,i)=>i===index?next:c)})}
 function updateGroup(next:typeof group){updateContrast({...current,groups:current.groups.map((g,i)=>i===groupIndex?next:g)})}
 function setDesign(design:string,mode=config.mode){
  const bulk=mode==='bulk_counts',omnibus=!bulk&&design==='multiple'
  const next:typeof config={...config,mode,design,method:bulk?'deseq2_wald':({independent:'welch_t',paired:'paired_t',multiple:'welch_anova'}[design]??'welch_t'),
   analysis_layer:bulk?'raw_counts':config.analysis_layer==='raw_counts'?'analysis':config.analysis_layer,
   inference_unit:bulk?'biological':config.inference_unit,batch_adjustment:bulk&&config.batch_adjustment===true&&(reviewed||design!=='paired'),
   posthoc:'none',contrasts:contrasts.map(c=>({...c,groups:omnibus&&c.groups.length<3?[...c.groups,{label:'C',sample_keys:[]}]:c.groups.slice(0,omnibus?6:2)}))}
  if(bulk&&!counts)Object.assign(next,bulkModelDefaults)
  if(!bulk)for(const key of Object.keys(bulkModelDefaults))delete next[key]
  onChange(next)
  setGroupIndex(0)
 }
 function updateCovariate(index:number,change:Partial<SampleCovariate>){
  onChange({...config,covariates:covariates.map((item,i)=>i===index?{...item,...change}:item)})
 }
 async function load(){if(controller.current||!valid.current)return;const c=new AbortController();controller.current=c;setBusy(true);setError('');try{const all=await readQuantitativeSamples(projectId,sources,c.signal,value=>{if(valid.current&&!c.signal.aborted)setScale(value)});if(valid.current&&!c.signal.aborted)setRows(all)}catch(e){if(!c.signal.aborted)setError(safeError(e,'读取固定样本失败。'))}finally{if(controller.current===c){controller.current=null;setBusy(false)}}}
 function add(keys:SampleKey[]){updateGroup({...group,sample_keys:[...new Map([...group.sample_keys,...keys].map(s=>[sampleKey(s),s])).values()]})}
 const fields=[...new Set(['condition','group','donor','pair_id','biological_unit_id','batch','sample_role',...rows.flatMap(r=>Object.keys(r).filter(k=>!['sample_id','processed_version_id','retained','canonical_dataset_id'].includes(k)&&typeof r[k]!=='object'))])],values=[...new Set(rows.filter(r=>r.retained!==false).map(r=>String(r[field]??'')))].filter(Boolean).sort(),chosen=rows.filter(r=>r.retained!==false&&String(r[field]??'')===value).map(({processed_version_id,sample_id})=>({processed_version_id,sample_id}))
 return <section><h3>{t('样本定量比较与统计设计')}</h3>
  <Field label="定量统计路径" value={text(config.mode)} onChange={v=>setDesign(text(config.design),v)}><option value="continuous">{t('连续定量值（标准化表达／蛋白／代谢）')}</option><option value="bulk_counts">{t('bulk 原始整数 counts · DESeq2')}</option></Field>
  <Field label="样本比较设计" value={text(config.design)} onChange={v=>setDesign(v)}>
   <option value="independent">{t('独立两组')}</option><option value="paired">{t(reviewed?'配对或重复测量':'配对两组')}</option>
   {(!counts||reviewed)&&<option value="multiple">{t(counts?'多组指定两两比较（统一拟合）':'多组整体比较')}</option>}
  </Field>
  <ConfigField {...p} name="method" label="统计方法" options={counts?{deseq2_wald:'DESeq2 Wald'}:paired?{paired_t:'配对 t',wilcoxon:'Wilcoxon 配对秩检验'}:multiple?{welch_anova:'Welch ANOVA',kruskal_wallis:'Kruskal–Wallis'}:{welch_t:'Welch t',mann_whitney_u:'Mann–Whitney U'}}/>
  <ConfigField {...p} name="analysis_layer" label="比较数值层" options={counts?{raw_counts:'冻结原始整数 counts'}:{analysis:'analysis（实际分析尺度）',display:'display（实际显示尺度）'}}/>
  <p>{t('连续路径保留实际单位与上游变换，不冒充 count 模型；缺失逐特征处理，不自动补零或插补。')}</p>
  <ConfigField {...p} name="inference_unit" label="重复单位" options={counts?{biological:'生物学重复'}:{biological:'生物学重复',technical:'技术重复（仅探索）'}}/>
  <ConfigField {...p} name="inference_goal" label="推断目标" options={{exploratory:'探索性分析',inference:'独立样本推断（需设计支持）'}}/>
  {config.inference_unit==='technical'?<><p className="warning-panel">{t('技术测量不能增加生物学重复数；此路径仅作样本技术层探索。')}</p><Toggle label="已确认技术重复仅作探索" value={config.technical_exploration_confirmed===true} onChange={v=>onChange({...config,technical_exploration_confirmed:v})}/></>:<><Toggle label="独立生物学单位及重复依据已确认" value={config.independence_confirmed===true} onChange={v=>onChange({...config,independence_confirmed:v})}/><ConfigField {...p} name="independence_basis" label="独立性确认依据" type="textarea"/></>}
  <ConfigField {...p} name="design_basis" label="样本设计与比较依据" type="textarea"/><Toggle label="本次分组来自同一数值矩阵的数据探索" value={config.data_driven_grouping===true} onChange={v=>onChange({...config,data_driven_grouping:v})}/>
  {paired&&<ConfigField {...p} name="pairing_field" label="固定配对字段" options={{pair_id:'pair_id',donor:'donor',biological_unit_id:'biological_unit_id'}}/>}
  {paired&&reviewed&&<p>{t('可添加多项两组比较。纳入同一模型的各条件须包含同一组配对单位。')}</p>}
  {counts&&<>
   <ConfigField {...p} name="size_factor_method" label="DESeq2 size factor 方法" options={{ratio:'ratio',poscounts:'poscounts'}}/>
   <ConfigField {...p} name="minimum_total_counts" label="总 counts 预过滤门槛" type="number" min={1} max={1000000}/>
   {(!paired||reviewed)&&<Toggle label="加入已记录 batch 调整" value={config.batch_adjustment===true} onChange={v=>onChange({...config,batch_adjustment:v})}/>}
   {!reviewed&&<button type="button" onClick={()=>onChange({...config,...bulkModelDefaults})}>{t('启用新版 Bulk 模型')}</button>}
  </>}
  {reviewed&&<>
   <ConfigField {...p} name="minimum_sample_counts" label="单样本最低 counts" type="number" min={1} max={1000000}/>
   <p>{t('至少在最小纳入组的样本数中达到单样本门槛，并满足总 counts 门槛。')}</p>
   <Field label="模型参考组" value={text(config.condition_reference)} onChange={v=>onChange({...config,condition_reference:v||null})}>
    <option value="">{t('使用第一个比较的分母组')}</option>
    {[...new Set(contrasts.flatMap(c=>c.groups.map(g=>g.label)).filter(Boolean))].map(label=><option key={label}>{label}</option>)}
   </Field>
   <section className="analysis-detail">
    <h3>{t('结构化协变量')}</h3><p>{t('填写固定样本表的列名。分类协变量可以指定参考水平，连续协变量须为数值。')}</p>
    <datalist id="bulk-covariate-fields">{fields.filter(f=>!['condition','donor','pair_id','biological_unit_id','batch','sample_role'].includes(f)).map(f=><option key={f} value={f}/>)}</datalist>
    {covariates.map((covariate,i)=><fieldset className="insight-grid" key={i}>
     <legend>{t('协变量 {index}',{index:i+1})}</legend>
     <label>{t('协变量字段')}<input list="bulk-covariate-fields" value={covariate.field} onChange={e=>updateCovariate(i,{field:e.target.value})}/></label>
     <Field label="协变量类型" value={covariate.kind} onChange={v=>updateCovariate(i,{kind:v as SampleCovariate['kind'],reference_level:null})}>
      <option value="categorical">{t('分类')}</option><option value="continuous">{t('连续')}</option>
     </Field>
     <Field label="协变量名称" value={covariate.name} onChange={v=>updateCovariate(i,{name:v})}/>
     {covariate.kind==='categorical'&&<Field label="分类参考水平（可留空）" value={covariate.reference_level??''} onChange={v=>updateCovariate(i,{reference_level:v||null})}/>}
     <button type="button" onClick={()=>onChange({...config,covariates:covariates.filter((_,j)=>j!==i)})}>{t('移除协变量')}</button>
    </fieldset>)}
    <button type="button" disabled={covariates.length>=16} onClick={()=>onChange({...config,covariates:[...covariates,{field:'',kind:'categorical',name:'',reference_level:null}]})}>{t('添加协变量')}</button>
   </section>
  </>}
  {multiple&&!counts&&<ConfigField {...p} name="posthoc" label="多组后续比较" options={{none:'不请求',all_pairs_holm:'全部两两比较与 Holm 校正'}}/>}
  <div className="insight-grid"><Field label="物种 taxonomy ID（未知或混合可留空）" value={typeof config.species_taxon_id==='number'?config.species_taxon_id:''} type="number" min={1} onChange={v=>onChange({...config,species_taxon_id:v===''?null:Number(v)})}/><ConfigField {...p} name="namespace" label="特征 ID 命名空间"/><ConfigField {...p} name="reference_version" label="参考／特征 ID 版本"/></div>
  {reviewed&&scale?.namespace&&scale.reference_version&&<button type="button" onClick={()=>onChange({...config,namespace:scale.namespace,reference_version:scale.reference_version,species_taxon_id:scale.species_taxon_id??null})}>{t('采用固定来源的物种与参考版本')}</button>}
  <p>{t('无适用 gene ID 映射时仍可比较和筛选候选，富集另行核对资源兼容性。')}</p>
  <h3>{t('冻结比较族与样本组')}</h3>
  <p>{t(multiple&&!counts?'多组整体检验没有自然分子／分母，整体效应按不可适用记录。':'第一组为分子、第二组为分母；正效应表示第一组更高。未选样本不自动进入对照。')}</p>
  {reviewed&&<p>{t('同一条件在每个比较中使用相同样本。所有指定比较共享同一次拟合。')}</p>}
  <Field label="当前样本比较" value={index} onChange={v=>{setIndex(Number(v));setGroupIndex(0)}}>{contrasts.map((c,i)=><option key={i} value={i}>{c.contrast_id} · {c.name}</option>)}</Field>
  <button type="button" disabled={contrasts.length>=10} onClick={()=>{let n=contrasts.length+1;while(contrasts.some(c=>c.contrast_id===`contrast_${n}`))n++;onChange({...config,contrasts:[...contrasts,newSampleContrast(`contrast_${n}`,multiple&&!counts?3:2)]});setIndex(contrasts.length);setGroupIndex(0)}}>{t('添加比较（最多 10 个）')}</button>
  {contrasts.length>1&&<button type="button" onClick={()=>{onChange({...config,contrasts:contrasts.filter((_,i)=>i!==index)});setIndex(0);setGroupIndex(0)}}>{t('移除当前比较')}</button>}
  <Field label="比较稳定 ID" value={current.contrast_id} onChange={v=>updateContrast({...current,contrast_id:v})}/><Field label="比较显示名" value={current.name} onChange={v=>updateContrast({...current,name:v})}/>
  {counts&&<p><strong>{current.groups[0].label} vs {current.groups[1].label}</strong> · {t('参考（分母）')} {current.groups[1].label}</p>}
  <Field label="当前样本组" value={groupIndex} onChange={v=>setGroupIndex(Number(v))}>{current.groups.map((g,i)=><option key={i} value={i}>{i+1} · {g.label}</option>)}</Field><Field label="样本组名称" value={group.label} onChange={v=>updateGroup({...group,label:v})}/>
  {multiple&&!counts?<><button type="button" disabled={current.groups.length>=6} onClick={()=>{updateContrast({...current,groups:[...current.groups,{label:`Group ${current.groups.length+1}`,sample_keys:[]}]});setGroupIndex(current.groups.length)}}>{t('添加组（最多 6 组）')}</button><button type="button" disabled={current.groups.length<=3} onClick={()=>{updateContrast({...current,groups:current.groups.filter((_,i)=>i!==groupIndex)});setGroupIndex(0)}}>{t('移除当前组')}</button></>:<button type="button" onClick={()=>updateContrast({...current,groups:[...current.groups].reverse()})}>{t('交换比较方向（保存后产生新版）')}</button>}
  <button type="button" disabled={busy||!picks.length} onClick={()=>void load()}>{t('读取完整固定样本')}</button>{busy&&<p role="status">{t('正在读取固定样本……')}<button type="button" onClick={()=>{controller.current?.abort();controller.current=null;setBusy(false)}}>{t('取消等待')}</button></p>}{error&&<p role="alert">{t(error)}</p>}{rows.length>0&&<p>{t('已读取 {count} 个固定样本。',{count:rows.length})}</p>}
  <Field label="样本分组字段" value={field} onChange={v=>{setField(v);setValue('')}}>{fields.map(f=><option key={f}>{f}</option>)}</Field><Field label="样本分组值" value={value} onChange={setValue}><option value="">{t('请选择')}</option>{values.map(v=><option key={v}>{v}</option>)}</Field><button type="button" disabled={!value||!chosen.length} onClick={()=>add(chosen)}>{t('加入当前组')}</button>
  <section className="analysis-detail"><h3>{t('精确样本 ID 选择')}</h3><Field label="样本所属处理版本" value={processed||picks[0]?.source_id||''} onChange={setProcessed}>{picks.map(s=><option key={s.source_id} value={s.source_id}>{s.title??s.source_id}</option>)}</Field><Field label="精确样本 ID（逐行）" value={manual} onChange={setManual} type="textarea"/><button type="button" disabled={!rows.length||!manual.trim()} onClick={()=>{const ids=manual.split(/\r?\n/).map(v=>v.trim()).filter(Boolean),pid=processed||picks[0]?.source_id,picked=rows.filter(r=>r.processed_version_id===pid&&ids.includes(r.sample_id)&&r.retained!==false);if(new Set(ids).size!==ids.length||picked.length!==ids.length){setError('存在未知、重复或已排除样本，请核对完整样本表。');return}add(picked.map(({sample_id,processed_version_id})=>({sample_id,processed_version_id})))}}>{t('精确加入当前组')}</button></section>
  {current.groups.map((g,i)=><section key={i}><p>{g.label} · {g.sample_keys.length} {t('样本；有效数、配对与独立性以预检为准')}</p><button type="button" onClick={()=>updateContrast({...current,groups:current.groups.map((x,j)=>i===j?{...x,sample_keys:[]}:x)})}>{t('清空样本组')} {g.label}</button><DataDetails title="固定样本键" value={g.sample_keys}/></section>)}
  <section className="analysis-detail"><h3>{t('逐样本显式排除与原因')}</h3><Field label="每行 处理版本|样本 ID|原因" type="textarea" value={(config.excluded_samples as (SampleKey&{reason:string})[]).map(s=>`${s.processed_version_id}|${s.sample_id}|${s.reason}`).join('\n')} onChange={v=>onChange({...config,excluded_samples:v.split('\n').filter(Boolean).map(line=>{const[processed_version_id,sample_id,...reason]=line.split('|');return{processed_version_id,sample_id,reason:reason.join('|')}})})}/></section>
  <p>{t('比较族固定包含当前全部比较；新增比较需保存新版本并重新计算该族，不会改写旧 q。')} {contrasts.map(c=>c.contrast_id).join(', ')}</p>
 </section>
}
