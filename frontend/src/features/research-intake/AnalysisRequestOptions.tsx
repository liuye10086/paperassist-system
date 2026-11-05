import {useState} from 'react'
import type {Content} from './contracts'
import {useI18n} from '../../shared/i18n'
type ScopeItem={id:string;title:string;delivery_kind:string;status:string;source:string}
const levels=[
 {key:'basic',title:'基础分析',help:'比较组间差异，了解主要变化和功能通路。'},
 {key:'deep',title:'深入研究',help:'聚焦候选对象，结合外部证据梳理研究线索。'},
 {key:'integrated',title:'综合研究',help:'结合多类数据，研究不同层面之间的联系。'},
 {key:'common',title:'通用需求',help:'验证复核、可视化和报告可与任一研究层级组合。'},
]
const options=[
 ['differential','差异分析','比较不同分组的基因或指标变化','basic'],
 ['enrichment','GO / KEGG / GSEA 功能分析','了解差异结果涉及的功能与通路','basic'],
 ['candidates','候选对象筛选','筛选值得进一步研究的基因或指标','deep'],
 ['evidence','外部证据整合','结合公开数据与文献评估结果','deep'],
 ['multiomics','多组学整合','结合多类数据寻找共同线索','integrated'],
 ['validation','qPCR / 统计复核','整理验证实验或复核统计结果','common'],
 ['visualization','结果可视化','生成便于理解和展示的图表','common'],
 ['delivery','分析报告与可复现材料','整理分析说明、结果表与复现材料','common'],
]
export default function AnalysisRequestOptions({value,onChange,disabled}:{value:Content;onChange:(v:Content)=>void;disabled:boolean}){
 const {t}=useI18n(),[level,setLevel]=useState('basic');const items=(value.scope_items??[]) as ScopeItem[]
 const selected=options.filter(([key])=>items.some(row=>row.id==='questionnaire.analysis.'+key&&row.status!=='not_included'))
 return <section className="research-levels" aria-label={t('分析需求')}>
  <header><h3>{t('按研究深度浏览')}</h3><p>{t('按需组合不同层级；切换视图不会改变已选内容。')}</p></header>
  <nav className="research-level-nav" aria-label={t('研究深度')}>{levels.map(item=><button key={item.key} type="button" aria-pressed={level===item.key} onClick={()=>setLevel(item.key)}>{t(item.title)}</button>)}</nav>
  <p className="research-level-description">{t(levels.find(item=>item.key===level)!.help)}</p>
  <fieldset disabled={disabled} className="research-option-fieldset"><legend>{t('选择需要的分析模块')}</legend><div className="questionnaire-options">{options.filter(option=>option[3]===level).map(([key,title,help])=>{
   const id='questionnaire.analysis.'+key,item=items.find(row=>row.id===id)
   return <label className="questionnaire-option" key={id}><input aria-label={t(title)} type="checkbox" checked={!!item&&item.status!=='not_included'} disabled={disabled||(!item&&items.length>=100)} onChange={e=>onChange({...value,scope_items:item?items.map(row=>row.id===id?{...row,status:e.target.checked?'planned':'not_included'}:row):[...items,{id,title,delivery_kind:'analysis',status:'planned',source:'客户需求分步选择'}]})}/><span><strong>{t(title)}</strong><small>{t(help)}</small></span></label>
  })}</div></fieldset>
  <div className="research-selected"><span>{t('已选分析模块：{count}',{count:selected.length})}</span>{selected.map(([key,title,,category])=><button type="button" key={key} onClick={()=>setLevel(category)}>{t(title)}</button>)}</div>
  <p className="muted">{t('通用实验在“实验设计”中独立登记，质量控制位于第 2 步。')}</p>
  {items.length>=100&&<p>{t('研究范围已达 100 项，请先移除不需要的范围后再添加。')}</p>}
 </section>
}
