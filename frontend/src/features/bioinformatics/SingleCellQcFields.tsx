import {useI18n} from '../../shared/i18n'
import type {BioRecipeParameters,LibraryQcOverride,SingleCellLibrary} from './spatialContracts'

type Threshold=Exclude<keyof LibraryQcOverride,'library_id'>
const thresholds:[Threshold,string,number,number][]=[
 ['min_counts','最低 counts',0,2147483647],['min_genes','最低检测基因数',0,100000],
 ['max_counts','最高 counts',1,2147483647],['max_mt_fraction','最高线粒体比例',0,1],
]

export default function SingleCellQcFields({params,libraries,onChange}:{params:BioRecipeParameters;libraries:SingleCellLibrary[];onChange:(value:BioRecipeParameters)=>void}){
 const {t}=useI18n()
 const doublet=params.doublet??{enabled:false,exclude_predicted:false,expected_rate:null}
 const changeThreshold=(library:string,key:Threshold,text:string)=>{
  const overrides=[...(params.library_qc_overrides??[])]
  const previous=overrides.find(v=>v.library_id===library)
  const entry:LibraryQcOverride={...previous,library_id:library}
  if(text==='')delete entry[key];else entry[key]=Number(text)
  const next=overrides.filter(v=>v.library_id!==library)
  if(Object.keys(entry).length>1)next.push(entry)
  onChange({...params,library_qc_overrides:next})
 }
 return <section aria-label={t('单细胞质量控制')}>
  <h4>{t('分文库 QC')}</h4>
  <p>{t('每个捕获文库可以使用自己的阈值；留空沿用上方全局值。文库身份来自原始导入信息。')}</p>
  {libraries.length===0?<p>{t('当前数据未提供原始捕获文库清单，使用全局阈值。')}</p>:libraries.map(library=>{
   const values=params.library_qc_overrides?.find(v=>v.library_id===library.library_id)
   return <fieldset key={library.library_id}><legend>{library.library_id} · {library.sample_id}</legend>
    <div className="intake-rows">{thresholds.map(([key,label,min,max])=><label key={key}>{t(label)}
     <input aria-label={`${library.library_id} ${t(label)}`} type="number" min={key==='max_counts'?(values?.min_counts??params.min_counts):min} max={max} step={key==='max_mt_fraction'?'any':1}
      disabled={key==='max_mt_fraction'&&!params.mt_rule.confirmed} placeholder={`${t('沿用全局')} ${params[key]??t('不设限')}`}
      value={values?.[key]??''} onChange={e=>changeThreshold(library.library_id,key,e.target.value)}/>
    </label>)}</div>
   </fieldset>
  })}
  <h4>{t('双细胞与环境 RNA')}</h4>
  <label className="intake-check"><input type="checkbox" checked={doublet.enabled} onChange={e=>onChange({...params,doublet:{...doublet,enabled:e.target.checked,exclude_predicted:e.target.checked&&doublet.exclude_predicted}})}/>{t('运行 scDblFinder 双细胞检测')}</label>
  <p>{t('按捕获文库分别计算。评分和预测会保存，预测不等于已证实的双细胞。')}</p>
  {doublet.enabled&&<>
   <label className="intake-check"><input type="checkbox" checked={doublet.exclude_predicted} onChange={e=>onChange({...params,doublet:{...doublet,exclude_predicted:e.target.checked}})}/>{t('排除预测双细胞')}</label>
   <label>{t('预期双细胞比例（留空使用工具估计）')}<input type="number" min={0.000001} max={0.999999} step="any" value={doublet.expected_rate??''} onChange={e=>onChange({...params,doublet:{...doublet,expected_rate:e.target.value===''?null:Number(e.target.value)}})}/></label>
   <p>{t('留空时采用工具的文库细胞数估计；不同建库平台可填写已知比例，例如 0.04 表示 4%。')}</p>
  </>}
  <label className="intake-check"><input type="checkbox" checked={params.decontx?.enabled??false} onChange={e=>onChange({...params,decontx:{enabled:e.target.checked}})}/>{t('运行 decontX 环境 RNA 校正')}</label>
  <p>{t('保存模型估计的污染比例和独立校正表达层。原始 counts、当前降维和统计分析的输入保持不变；不满足条件时会说明原因。')}</p>
 </section>
}
