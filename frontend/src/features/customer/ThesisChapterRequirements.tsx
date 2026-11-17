import { Fragment, useState } from 'react'
import { useI18n } from '../../shared/i18n'
import type { Chapter } from '../school-templates/contracts'
import { thesisSectionLabels, type BoundThesisTemplate, type ThesisSection, type ThesisSectionPurpose } from './thesisProjectRequirements'

const purposes: ThesisSectionPurpose[] = ['materials_and_methods', 'results']

function chapterOptions(chapters: Chapter[], duplicateLabel: (title: string, number: number) => string) {
  const counts = new Map<string, number>()
  for (const chapter of chapters) counts.set(chapter.title, (counts.get(chapter.title) ?? 0) + 1)
  return chapters.map((chapter, index) => ({
    ...chapter, label: (counts.get(chapter.title) ?? 0) > 1 ? duplicateLabel(chapter.title, index + 1) : chapter.title,
  }))
}

export default function ThesisChapterRequirements({ template, sections, onChange, disabled }: {
  template: BoundThesisTemplate; sections: ThesisSection[]; onChange?: (sections: ThesisSection[]) => void; disabled?: boolean
}) {
  const { t } = useI18n()
  const chapters = chapterOptions(template.chapters, (title, number) => t('{title}（模板第 {number} 项）', { title, number }))
  const selected = new Map(sections.map(section => [section.chapter_id, section]))
  const available = chapters.filter(chapter => !selected.has(chapter.id))
  return <div className="thesis-chapter-groups">
    {purposes.map(purpose => {
      const items = chapters.flatMap(chapter => {
        const section = selected.get(chapter.id)
        return section?.purpose === purpose ? [{ ...chapter, content: section.content }] : []
      })
      const title = t(thesisSectionLabels[purpose])
      if (!onChange) return <section key={purpose} className="thesis-section-summary">
        <h4>{title}</h4>
        {items.length ? <dl className="sci-settings-summary">{items.map(item =>
          <Fragment key={item.id}><dt>{item.label}</dt><dd>{item.content}</dd></Fragment>)}</dl> : <p className="muted">{t('待填写')}</p>}
      </section>
      return <fieldset key={purpose} className="thesis-chapter-group" disabled={disabled}>
        <legend>{title}</legend>
        {items.map(item => <div key={item.id} className="thesis-section-row">
          <label>{item.label}<textarea rows={3} required maxLength={20000} value={item.content}
            onChange={event => onChange(sections.map(section => section.chapter_id === item.id ? { ...section, content: event.target.value } : section))} /></label>
          <button type="button" className="button-quiet" aria-label={t('移除章节 {title}', { title: item.label })}
            onClick={() => onChange(sections.filter(section => section.chapter_id !== item.id))}>{t('移除')}</button>
        </div>)}
        <AddChapter choices={available} onAdd={chapter_id => onChange([...sections, { chapter_id, purpose, content: '' }])} />
      </fieldset>
    })}
  </div>
}

function AddChapter({ choices, onAdd }: { choices: { id: string; label: string }[]; onAdd: (id: string) => void }) {
  const { t } = useI18n()
  const [selected, setSelected] = useState('')
  const value = choices.some(choice => choice.id === selected) ? selected : ''
  if (!choices.length) return null
  return <div className="sci-inline-controls thesis-chapter-controls">
    <label>{t('模板章节')}<select value={value} onChange={event => setSelected(event.target.value)}>
      <option value="">{t('请选择模板章节')}</option>
      {choices.map(chapter => <option key={chapter.id} value={chapter.id}>{chapter.label}</option>)}
    </select></label>
    <button type="button" disabled={!value} onClick={() => { onAdd(value); setSelected('') }}>{t('添加章节')}</button>
  </div>
}
