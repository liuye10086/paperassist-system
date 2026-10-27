import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {provenanceNames,usd,type Provenance,type Summary} from './operationsApi'
import ToolUsageCounts from './ToolUsageCounts'
export function SummaryView({summary}:{summary:Summary}){
 const{t}=useI18n();const money=(value:number|null|undefined)=>t(usd(value));const token=(value:{known:number;unknown_count:number}|undefined)=>value?t('已知 {known}；未知 {count} 次',{known:value.known,count:value.unknown_count}):t('未知')
 return <dl className="operations-facts"><div><dt>{t('调用次数')}</dt><dd>{summary.call_count}</dd></div><div><dt>{t('估算费用（已知部分）')}</dt><dd>{money(summary.estimated_micro_usd)}<small>{t('未知 {count} 次',{count:summary.estimated_unknown_count})}</small></dd></div><div><dt>{t('已核对实际费用')}</dt><dd>{summary.actual_micro_usd==null?t('未知（尚未完整核对）'):money(summary.actual_micro_usd)}</dd></div><div><dt>{t('实际费用已知部分')}</dt><dd>{money(summary.actual_known_micro_usd)}<small>{t('未知 {count} 次',{count:summary.actual_unknown_count})}</small></dd></div><div><dt>{t('核对状态')}</dt><dd>{t('已核对 {reconciled}；部分 {partial}；待核对 {pending}；不适用 {na}',{reconciled:summary.reconciled_count,partial:summary.partial_count,pending:summary.pending_count,na:summary.not_applicable_count})}</dd></div><div><dt>{t('预算预留')}</dt><dd>{money(summary.reserved_micro_usd)}</dd></div><div><dt>{t('预算占用（非供应商账单）')}</dt><dd>{money(summary.accounted_micro_usd)}</dd></div><div><dt>{t('输入 Token')}</dt><dd>{token(summary.input_tokens)}</dd></div><div><dt>{t('输出 Token')}</dt><dd>{token(summary.output_tokens)}</dd></div><div><dt>{t('总 Token')}</dt><dd>{token(summary.total_tokens)}</dd></div><div><dt>{t('工具调用次数')}</dt><dd>{t('已知执行 {known} 次；{count} 次调用的执行次数未知',{known:summary.tool_call_count,count:summary.tool_call_unknown_count??t('未知')})}</dd></div><ToolUsageCounts value={summary}/></dl>
}
export function ProvenanceView({value,layered=false}:{value:Provenance;layered?:boolean}){
 const{t}=useI18n()
 const[selected,setSelected]=useState('openai_live')
 const keys=Object.keys(provenanceNames) as (keyof typeof provenanceNames)[]
 return <div className={`operations-provenance${layered?' usage-provenance-layered':''}`}>
  {layered&&<UsageViewTabs label="调用来源视图" items={keys.map(key=>[key,provenanceNames[key]])} selected={selected} onChange={setSelected}/>}
  {keys.map(key=><section className={`operations-provenance-${key} usage-layer`} hidden={layered&&selected!==key} aria-label={t(provenanceNames[key])} key={key}>
   <h4>{t(provenanceNames[key])}</h4><p>{t(key==='openai_live'?'此栏仅包含有证据的真实供应商调用。':key==='synthetic_fixture'?'此栏为合成样例，不代表真实供应商支出。':'缺少来源证据，不计为已证实真实支出。')}</p>
   {value[key]&&<SummaryView summary={value[key]}/>}
  </section>)}
 </div>
}

// Buttons expose the current view while the mounted panels retain filters and pages.
export function UsageViewTabs({label,items,selected,onChange}:{label:string;items:string[][];selected:string;onChange:(key:string)=>void}){
 const{t}=useI18n()
 return <nav className="usage-view-tabs" aria-label={t(label)}>{items.map(([key,title])=><button type="button" key={key} aria-pressed={selected===key} onClick={()=>onChange(key)}>{t(title)}</button>)}</nav>
}
