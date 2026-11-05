import {useI18n} from '../../shared/i18n'
import type {Content} from './contracts'
const common=['qPCR / RT-qPCR','Western blot','ELISA','免疫荧光 / 免疫组化','流式细胞术']
export default function CommonExperiments({value,onChange,disabled,onAdded}:{value:Content;onChange:(next:Content)=>void;disabled:boolean;onAdded?:()=>void}){
 const {t}=useI18n(),items=(value.experiments??[]) as {id:string;data_type:string}[]
 return <section className="common-experiments"><h3>{t('通用实验')}</h3><p>{t('各研究层级均可使用；添加后补充物种、组织、技术和来源，也可登记自定义实验。')}</p><div className="common-experiment-options">{common.map(name=>{
  const exists=items.some(item=>item.data_type.trim().toLowerCase()===name.toLowerCase())
  return <button type="button" key={name} disabled={disabled||exists||items.length>=50} aria-label={t(exists?'已添加 {name}':'添加 {name}',{name:t(name)})} onClick={()=>{onChange({...value,experiments:[...items,{id:'experiment_'+crypto.randomUUID(),data_type:name,technology:{state:'known',value:name}}]});onAdded?.()}}>{exists?'✓ ':'＋ '}{t(name)}</button>
 })}</div></section>
}
