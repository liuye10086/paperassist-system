import { useI18n } from '../../shared/i18n'
export type MaterialItem={purpose:string;availability:'provided'|'pending'|'none';note?:string}
const materialKinds=['protocol','sample_sheet','raw_data','existing_results','figures','other']
const labels:Record<string,string>={protocol:'实验方案',raw_data:'原始数据',sample_sheet:'样本信息表',existing_results:'已有结果',figures:'已有图表',other:'其他材料'}
export default function MaterialChecklist({value,onChange,disabled}:{value:MaterialItem[];onChange:(v:MaterialItem[])=>void;disabled?:boolean}){
 const {t}=useI18n();return <fieldset disabled={disabled}><legend>{t('材料清单')}</legend>{materialKinds.map(kind=>{const item=value.find(i=>i.purpose===kind)??{purpose:kind,availability:'pending' as const};return <div className="intake-material" key={kind}><label>{t(labels[kind])}<select value={item.availability} onChange={e=>onChange([...value.filter(i=>i.purpose!==kind),{...item,availability:e.target.value as MaterialItem['availability']}])}><option value="provided">{t('已提供')}</option><option value="pending">{t('待补充')}</option><option value="none">{t('无')}</option></select></label><label>{t('材料说明')}<input value={item.note??''} maxLength={4000} onChange={e=>onChange([...value.filter(i=>i.purpose!==kind),{...item,note:e.target.value}])}/></label></div>})}</fieldset>
}
