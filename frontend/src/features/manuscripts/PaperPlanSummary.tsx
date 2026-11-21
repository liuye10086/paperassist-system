import {useI18n} from '../../shared/i18n'
import type {PaperPlan} from './manuscriptTypes'
import type {SchoolChapter} from './thesisTypes'

type Props={
  plan:PaperPlan
  heading:string
  omittedCount?:number
  filesOnly?:boolean
  migration?:{chapters:SchoolChapter[];mappings:unknown}
  onOpenRequirements?:()=>void
  onOpenMaterials?:()=>void
  /** Customer pages say “写作材料” instead of the internal “事实稿”. */
  customerView?:boolean
}

export default function PaperPlanSummary({plan,heading,omittedCount=0,filesOnly=false,migration,onOpenRequirements,onOpenMaterials,customerView=false}:Props){
  const {t}=useI18n()
  const methods=new Set(plan.sections.filter(section=>section.purpose==='materials_and_methods').map(section=>section.chapter_id))
  const mappedMethods=new Set(Array.isArray(migration?.mappings)?migration.mappings
    .filter(mapping=>mapping&&typeof mapping.input_section_id==='string'&&methods.has(mapping.input_section_id))
    .map(mapping=>mapping.chapter_id):[])
  const sections=migration
    ?migration.chapters.filter(chapter=>chapter.purpose==='materials_and_methods'&&mappedMethods.has(chapter.id)||
      plan.sections.some(section=>chapter.result_group_ids.includes(section.id))).map(chapter=>({
      id:chapter.id,label:chapter.title,text:'',materials:plan.materials.filter(material=>chapter.result_group_ids.includes(material.section_id)),
    }))
    :plan.sections.map(section=>({...section,materials:plan.materials.filter(material=>material.section_id===section.id)}))
  return <section className="manuscript-panel paper-plan-summary" aria-label={t(heading)}>
    <h3>{t(heading)}</h3>
    {!filesOnly&&<p><strong>{t('稿件标题')}</strong> · {plan.title}</p>}
    {plan.keywords.length>0&&<p><strong>{t('关键词')}</strong> · {plan.keywords.join(' · ')}</p>}
    {migration&&!sections.length&&<p>{t('本版没有已确认归属的计划章节或图表。')}</p>}
    {sections.map(section=>{
      const materials=section.materials
      return <article key={section.id} className="paper-plan-section">
        <h4>{section.label}</h4>
        {!filesOnly&&section.text&&<p className="paper-plan-note">{section.text}</p>}
        {materials.length>0&&<ul className="paper-plan-files">{materials.map((material,index)=><li key={`${material.selection.kind}:${material.selection.id}:${index}`}>
          <strong>{t(material.kind==='figure'?'图':'表')} · {material.filename}</strong>
          {!!material.worksheet_names?.length&&<p className="muted">{t('入稿工作表')} · {material.worksheet_names.join(' · ')}</p>}
          {!filesOnly&&material.result&&<p className="paper-plan-note">{material.result}</p>}
        </li>)}</ul>}
      </article>
    })}
    {omittedCount>0&&<p className="warning-panel">{t(customerView?'有 {number} 项材料尚无有效归属，暂不纳入本次写作材料。':'有 {number} 项材料尚无有效归属，暂不纳入本次事实稿。',{number:omittedCount})}</p>}
    {(onOpenRequirements||onOpenMaterials)&&<div className="manuscript-actions">
      {onOpenRequirements&&<button type="button" onClick={onOpenRequirements}>{t('查看或修改写作要求')}</button>}
      {onOpenMaterials&&<button type="button" onClick={onOpenMaterials}>{t('查看图表归属')}</button>}
    </div>}
  </section>
}
