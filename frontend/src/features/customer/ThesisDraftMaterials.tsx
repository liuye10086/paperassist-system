import {useI18n} from '../../shared/i18n'
import {parsedMaterialLabel} from '../../shared/parsedMaterialLabel'
import type {Candidates} from '../manuscripts/manuscriptTypes'
import {purposeLabels, schoolPurposes, type SchoolPurpose} from '../manuscripts/thesisTypes'
import type {thesisDraftMaterials} from './thesisGenerationInput'
import type {ThesisRequirements} from './thesisProjectRequirements'

type Props = {candidates:Candidates; requirements:ThesisRequirements | null; material:ReturnType<typeof thesisDraftMaterials>;
  onChange:(key:string,purpose:SchoolPurpose)=>void; resultChapter:string; onResultChapter:(id:string)=>void; locked:boolean}

export default function ThesisDraftMaterials({candidates,requirements,material,onChange,resultChapter,onResultChapter,locked}:Props) {
  const {t} = useI18n()
  const school = candidates.thesis, plan = candidates.paper_plan
  const directory = school?.template_source_filenames?.length ? school.template_source_filenames :
    requirements?.template?.name ? [requirements.template.name] : []
  const files = [...new Set([...material.sources.map(s => parsedMaterialLabel(s) ?? s.label), ...(plan?.materials.map(m => m.filename) ?? [])])]
  const notes = new Map(plan?.sections.map(s => [s.chapter_id,s.text]))
  const chapters = school?.ready ? material.input.thesis?.chapter_mappings : undefined
  return <section className="thesis-generation-materials" aria-label={t('本次写作材料')}>
    {directory.map((name,i) => <p key={i}>{name}</p>)}
    {school && chapters && <details><summary>{t('学校目录（{count} 个章节）',{count:chapters.length})}</summary>
      <ol className="thesis-generation-chapters">{school.chapters.map(row => {
        return <li key={row.id} style={{paddingInlineStart:(row.level - 1) * .8 + 'rem'}}>
          {row.title}{notes.get(row.id) && <p>{notes.get(row.id)}</p>}
        </li>
      })}</ol>
    </details>}
    {school && chapters?.map((chapter,index) => material.chapterQuestions.has(chapter.chapter_id) && <label className="thesis-purpose"
      key={chapter.chapter_id}>{school.chapters[index].title}<select disabled={locked} value={chapter.purpose}
        onChange={event => onChange(school.confirmation_id + '/' + chapter.chapter_id,event.target.value as SchoolPurpose)}>
        <option value="">{t('选择章节用途')}</option>
        {schoolPurposes.map(p => <option key={p} value={p}>{t(purposeLabels[p])}</option>)}
      </select></label>)}
    {!!files.length && <details open={files.length <= 3}><summary>{t('本次写作材料（{count} 份）',{count:files.length})}</summary>
      <ul>{files.map(name => <li key={name}>{name}</li>)}</ul></details>}
    {material.input.reported_result && <p>{material.input.reported_result.text}</p>}
    {material.resultChoices && <label className="thesis-purpose">{t('已有结果属于哪个章节？')}
      <select disabled={locked} value={resultChapter} onChange={e => onResultChapter(e.target.value)}>
        <option value="">{t('请选择章节')}</option>
        {school?.chapters.filter(c => material.resultChoices?.has(c.id)).map(c => <option key={c.id} value={c.id}>{c.title}</option>)}
      </select></label>}
  </section>
}
