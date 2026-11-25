import { useEffect, useId, useRef, useState } from 'react'
import { useI18n } from '../../shared/i18n'
import { inferSchoolChapterPurposes } from '../manuscripts/paperDraftMaterials'
import { isSchoolWritingPurpose, purposeLabels, schoolWritingPurposes } from '../manuscripts/thesisTypes'
import type { Chapter } from '../school-templates/contracts'
import type { BoundThesisTemplate, ThesisSection, ThesisSectionPurpose } from './thesisProjectRequirements'
import './thesisChapterRequirements.css'

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
  const [purposeChoices, setPurposeChoices] = useState<Record<string, ThesisSectionPurpose>>({})
  const saved = new Map(sections.map(section => [section.chapter_id, section]))
  const purposes = inferSchoolChapterPurposes(template.chapters, {
    saved:new Map([...Object.entries(purposeChoices), ...sections.map(section => [section.chapter_id, section.purpose] as const)]),
    protectedPurposes:template.protected_chapter_purposes,
    protectOutline:true,
  })
  const chapters = chapterOptions(template.chapters, (title, number) => t('{title}（模板第 {number} 项）', { title, number }))
    .map((chapter, index) => ({...chapter, ...purposes[index], content:saved.get(chapter.id)?.content ?? ''}))
  const defaultChapter = chapters.find(chapter => !chapter.protected && chapter.content.trim()) ??
    chapters.find(chapter => !chapter.protected) ?? chapters[0]
  const [selectedId, setSelectedId] = useState(defaultChapter?.id)
  const selected = chapters.find(chapter => chapter.id === selectedId) ?? defaultChapter
  const outline = useRef<HTMLElement>(null)
  const selectedButton = useRef<HTMLButtonElement>(null)
  const headingId = useId()
  useEffect(() => {
    const nav = outline.current, button = selectedButton.current
    if (!nav || !button) return
    const viewport = nav.getBoundingClientRect(), item = button.getBoundingClientRect()
    if (item.top < viewport.top) nav.scrollTop += item.top - viewport.top
    else if (item.bottom > viewport.bottom) nav.scrollTop += item.bottom - viewport.bottom
  }, [selected?.id])
  if (!selected) return null

  const {id, title, content, protected:protectedChapter} = selected
  const purpose = isSchoolWritingPurpose(selected.purpose) ? selected.purpose : undefined
  const writable = !!onChange && !protectedChapter

  function update(content: string, purpose: ThesisSectionPurpose) {
    if (!onChange || protectedChapter || disabled) return
    if (!content) {
      setPurposeChoices(choices => ({...choices, [id]:purpose}))
      if (saved.has(id)) onChange(sections.filter(section => section.chapter_id !== id))
      return
    }
    const section = {chapter_id:id, purpose, content}
    onChange(saved.has(id) ? sections.map(item => item.chapter_id === id ? section : item) : [...sections, section])
  }

  return <div className="thesis-chapter-editor">
    <nav className="thesis-chapter-outline" aria-label={t('模板目录')} ref={outline}>
      <ol>{chapters.map(chapter => <li key={chapter.id}>
        <button type="button" className="button-quiet" aria-current={chapter.id === id ? 'true' : undefined}
          ref={chapter.id === id ? selectedButton : undefined}
          style={{paddingInlineStart:`${.65 + (chapter.level - 1) * .55}rem`}}
          onClick={() => setSelectedId(chapter.id)}>{chapter.label}</button>
      </li>)}</ol>
    </nav>
    <section className="thesis-chapter-content" aria-labelledby={headingId}>
      <h3 id={headingId}>{title}</h3>
      {writable && <label>{t('章节用途')}
        <select value={purpose ?? ''} disabled={disabled} onChange={event => {
          const next = event.target.value
          if (!isSchoolWritingPurpose(next)) return
          if (content) update(content, next)
          else setPurposeChoices(choices => ({...choices, [id]:next}))
        }}>
          <option value="" disabled>{t('选择章节用途')}</option>
          {schoolWritingPurposes.map(value => <option key={value} value={value}>{t(purposeLabels[value])}</option>)}
        </select>
      </label>}
      <label>{t('章节内容')}
        <textarea rows={9} maxLength={20000} value={content} readOnly={!writable}
          disabled={writable && (disabled || !purpose)} onChange={event => { if (purpose) update(event.target.value, purpose) }}/>
      </label>
      {protectedChapter && <p className="muted">{t('学校模板已固定此章用途，原需求仍可查看。')}</p>}
    </section>
  </div>
}
