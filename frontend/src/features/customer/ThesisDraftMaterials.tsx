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
  const outlineLabel = chapters ? t('学校目录（{count} 个章节）', {count: chapters.length}) : t('学校模板')
  const filesLabel = t('本次写作材料（{count} 份）', {count: files.length})
  return <section className="thesis-generation-materials" aria-label={t('本次写作材料')}>
    <div className="thesis-generation-grid">
      {(directory.length > 0 || chapters) && <section className="thesis-generation-card">
        <h3>{outlineLabel}</h3>
        {directory.map((name, i) => <p key={i} className="muted">{name}</p>)}
        {school && chapters && <ol className="thesis-generation-chapters" role="list" aria-label={outlineLabel} tabIndex={0}>
          {school.chapters.map(row => <li key={row.id} style={{paddingInlineStart:(row.level - 1) * .8 + 'rem'}}>
            {row.title}{notes.get(row.id) && <p>{notes.get(row.id)}</p>}
          </li>)}
        </ol>}
      </section>}
      {files.length > 0 && <section className="thesis-generation-card">
        <h3>{filesLabel}</h3>
        <ul role="list" aria-label={filesLabel} tabIndex={0}>{files.map(name => <li key={name}>{name}</li>)}</ul>
      </section>}
    </div>
    {school && chapters?.map((chapter,index) => material.chapterQuestions.has(chapter.chapter_id) && <label className="thesis-purpose"
      key={chapter.chapter_id}>{school.chapters[index].title}<select disabled={locked} value={chapter.purpose}
        onChange={event => onChange(school.confirmation_id + '/' + chapter.chapter_id,event.target.value as SchoolPurpose)}>
        <option value="">{t('选择章节用途')}</option>
        {schoolPurposes.map(p => <option key={p} value={p}>{t(purposeLabels[p])}</option>)}
      </select></label>)}
    {material.input.reported_result && <p>{material.input.reported_result.text}</p>}
    {material.resultChoices && <label className="thesis-purpose">{t('已有结果属于哪个章节？')}
      <select disabled={locked} value={resultChapter} onChange={e => onResultChapter(e.target.value)}>
        <option value="">{t('请选择章节')}</option>
        {school?.chapters.filter(c => material.resultChoices?.has(c.id)).map(c => <option key={c.id} value={c.id}>{c.title}</option>)}
      </select></label>}
  </section>
}
