import {useI18n} from '../../shared/i18n'
import type {PaperPlan} from './manuscriptTypes'

type Props={
  plan:PaperPlan
  heading:string
  omittedCount?:number
  filesOnly?:boolean
  onOpenRequirements?:()=>void
  onOpenMaterials?:()=>void
}

export default function PaperPlanSummary({plan,heading,omittedCount=0,filesOnly=false,onOpenRequirements,onOpenMaterials}:Props){
  const {t}=useI18n()
  return <section className="manuscript-panel paper-plan-summary" aria-label={t(heading)}>
    <h3>{t(heading)}</h3>
    {!filesOnly&&<p><strong>{t('稿件标题')}</strong> · {plan.title}</p>}
    {plan.keywords.length>0&&<p><strong>{t('关键词')}</strong> · {plan.keywords.join(' · ')}</p>}
    {plan.sections.map(section=>{
      const materials=plan.materials.filter(material=>material.section_id===section.id)
      return <article key={section.id} className="paper-plan-section">
        <h4>{section.label}</h4>
        {!filesOnly&&section.text&&<p className="paper-plan-note">{section.text}</p>}
        {materials.length>0&&<ul className="paper-plan-files">{materials.map((material,index)=><li key={`${material.selection.kind}:${material.selection.id}:${index}`}>
          <strong>{t(material.kind==='figure'?'图':'表')} · {material.filename}</strong>
          {!filesOnly&&material.result&&<p className="paper-plan-note">{material.result}</p>}
        </li>)}</ul>}
      </article>
    })}
    {omittedCount>0&&<p className="warning-panel">{t('有 {number} 项材料尚无有效归属，暂不纳入本次事实稿。',{number:omittedCount})}</p>}
    {(onOpenRequirements||onOpenMaterials)&&<div className="manuscript-actions">
      {onOpenRequirements&&<button type="button" onClick={onOpenRequirements}>{t('查看或修改写作要求')}</button>}
      {onOpenMaterials&&<button type="button" onClick={onOpenMaterials}>{t('查看图表归属')}</button>}
    </div>}
  </section>
}
