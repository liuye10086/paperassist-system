import {methodLabels,type FrozenSource,type Snapshot} from './manuscriptTypes'
import {record,displayed,type Decision,type Fact,type Metadata} from './reviewTypes'
import type {Params} from '../../shared/i18n'
export const metadataLabels:Record<Metadata['field'],string>={unit:'单位',display_precision:'显示小数位',object:'研究对象',group:'分组',acronym:'术语缩写',statistical_mark:'统计标记',error_bar:'误差条含义'}
export function targetLabel(target:string){return methodLabels[target.split(':').at(-1) as keyof typeof methodLabels]??target}
export function formatValue(v:unknown):string{return v===null||v===undefined?'—':typeof v==='string'?v:JSON.stringify(v)}
type Translate=(source:string,params?:Params)=>string
export function sourceLabel(source:FrozenSource,t:Translate):string{
 const revision=source.content.setup_revision
 const original=record(source.content.source)?source.content.source.version:undefined
 const version=Number.isSafeInteger(revision)&&Number(revision)>0
  ?t('分析配置版本 {number}',{number:Number(revision)})
  :Number.isSafeInteger(original)&&Number(original)>0
   ?t('来源版本 {number}',{number:Number(original)})
   :t('冻结来源版本（以来源标识区分）')
 return `${source.label} · ${version} · ${source.id}`
}
export function factLabel(fact:Fact,snapshot:Snapshot,t:Translate):string{
 const source=snapshot.sources.find(s=>s.id===fact.source_id)
 return `${source?sourceLabel(source,t):fact.source_id} · ${fact.path} = ${fact.value} · ${fact.id}`
}
export function decisionStatus(status:Decision['status']):string{
 return {supplied:'已补充',selected:'已选择',pending:'待核实',not_applicable:'不适用'}[status]
}
export function frozenDecisions(snapshot:Snapshot){
 const latest=new Map<string,NonNullable<Snapshot['review']>['decisions'][number]>()
 for(const decision of snapshot.review?.decisions??[]){
  latest.delete(decision.target_id)
  latest.set(decision.target_id,decision)
 }
 return [...latest.values()]
}
export function studyQuestion(snapshot:Snapshot,fallback:string,t:Translate):string{
 const confirmed=[...frozenDecisions(snapshot)].reverse().find(d=>['missing:research_question','conflict:research_question'].includes(d.target_id))
 if(confirmed)return confirmed.value||t(decisionStatus(confirmed.status))
 if(fallback)return fallback
 // A stable confirmed paragraph identity is evidence; its text is shown verbatim.
 const paragraph=displayed(snapshot).find(p=>p.id.startsWith('confirmed:')&&p.id.endsWith(':research_question')&&p.origin==='user_provided')
 return paragraph?.text??t('待补充')
}
