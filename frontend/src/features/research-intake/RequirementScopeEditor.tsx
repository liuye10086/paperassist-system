import {useI18n} from '../../shared/i18n'
import type {Content,DeliveryKind} from './contracts'
import {deliveryLabels} from './contracts'
export default function RequirementScopeEditor({value,onChange,disabled,analysisOnly=false}:{value:Content;onChange:(value:Content)=>void;disabled:boolean;analysisOnly?:boolean}){
 const {t}=useI18n();const items=(value.scope_items??[]) as {id:string;title:string;delivery_kind:DeliveryKind;status:string;source:string}[]
 const update=(index:number,key:string,next:string)=>onChange({...value,scope_items:items.map((row,i)=>i===index?{...row,[key]:next}:row)})
 return <section className="questionnaire-section questionnaire-scope"><h3>{t('研究范围')}</h3><p>{t('统一核对已选、自定义及历史范围，状态与来源均保留。')}</p>
  {!items.some(item=>!analysisOnly||item.delivery_kind==='analysis')&&<p className="muted">{t('尚未选择研究范围，可先选择分析模块或添加自定义范围。')}</p>}
  {items.map((item,index)=>(!analysisOnly||item.delivery_kind==='analysis')&&<fieldset disabled={disabled} key={item.id}><label>{t('范围标题')}<input maxLength={500} value={item.title} onChange={e=>update(index,'title',e.target.value)}/></label>{!analysisOnly&&<label>{t('交付类型')}<select value={item.delivery_kind} onChange={e=>update(index,'delivery_kind',e.target.value)}>{Object.entries(deliveryLabels).map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}</select></label>}<label>{t('范围状态')}<select value={item.status} onChange={e=>update(index,'status',e.target.value)}>{[['planned','计划纳入'],['completed','已完成'],['pending_review','待审核'],['not_included','不纳入']].map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}</select></label><label>{t('范围来源')}<textarea value={item.source} onChange={e=>update(index,'source',e.target.value)}/></label><button type="button" onClick={()=>onChange({...value,scope_items:items.filter((_,i)=>i!==index)})}>{t('移除此行')}</button></fieldset>)}
  <button type="button" disabled={disabled||items.length>=100} onClick={()=>onChange({...value,scope_items:[...items,{id:crypto.randomUUID(),title:'',delivery_kind:analysisOnly?'analysis':(value.services as DeliveryKind[]|undefined)?.[0]??'analysis',status:'planned',source:''}]})}>{t('添加研究范围')}</button>
 </section>
}
