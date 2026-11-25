import {useEffect, useRef, useState, type ComponentProps, type Ref} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError, useI18n, type Locale} from '../../shared/i18n'
import {headingLevels, isCustomSciSection, maxSciSections, validSciTemplate, type SciSection, type SciTemplate} from '../manuscripts/articleStructure'
import {WorkspaceIcon} from '../projects/WorkspaceShell'
import useDraftLeaveGuard, {type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import {IntakeError, intakeRequest, projectBase} from '../research-intake/api'
import {useResearchRead} from '../research-results/api'
import {useSciSectionDrag} from './useSciSectionDrag'

const maxEditableHeadingLevel = 5
const editableHeadingLevels = headingLevels.filter(level => level <= maxEditableHeadingLevel)

type TemplateSettings = {
  revision: number
  article_type: SciTemplate['article_type'] | null
  selected_template_id: string | null
  selected_sections: SciSection[] | null
  templates: SciTemplate[]
  combine_review_topics?: boolean
  figure_workflow?: boolean
}

function defaultSectionLevel(id: string) {
  return id === 'title' ? 0 : 1
}

function sameSections(left: SciSection[], right: SciSection[]) {
  return left.length === right.length && left.every((section, index) => {
    const other = right[index]
    return section.id === other.id && section.en === other.en && section.zh === other.zh &&
      (section.level ?? defaultSectionLevel(section.id)) === (other.level ?? defaultSectionLevel(other.id))
  })
}

function DragHandle({heading, fixed, ...handle}: ComponentProps<'button'> & {
  heading: string; fixed: boolean
}) {
  const {t} = useI18n()
  const label = t(fixed ? '{heading}（固定位置）' : '拖动 {heading}', {heading})
  return <button type="button" className="button-quiet sci-template-grip" aria-label={label} {...handle}
    title={handle.disabled ? label : t('拖动排序，或按方向键 ↑/↓')} aria-keyshortcuts={handle.disabled ? undefined : 'ArrowUp ArrowDown'}>
    <WorkspaceIcon name="menu" />
  </button>
}

function HeadingLevel({label, value, disabled, title, onChange}: {
  label: string; value: number; disabled: boolean; title?: boolean; onChange: (level: number) => void
}) {
  const {t} = useI18n()
  return <select className="sci-template-level" aria-label={label} value={value} disabled={disabled}
    onChange={event => onChange(Number(event.target.value))}>
    {title && <option value={0}>{t('论文标题样式')}</option>}
    {editableHeadingLevels.map(level => <option key={level} value={level}>{t('{level} 级标题', {level})}</option>)}
    {value > maxEditableHeadingLevel && <option value={value} hidden>{t('{level} 级标题', {level:value})}</option>}
  </select>
}

export default function CustomerSciTemplate({projectId, language, headingRef, registerLeaveGuard, onDetails, onContinue}: {
  projectId: string
  language: Locale
  headingRef: Ref<HTMLHeadingElement>
  registerLeaveGuard: RegisterLeaveGuard
  onDetails: () => void
  onContinue: () => void
}) {
  const {t} = useI18n()
  const url = projectBase(projectId) + '/sci-template'
  const read = useResearchRead<TemplateSettings>(url, true)
  const [choice, setChoice] = useState<string | null>(null)
  const [editedSections, setEditedSections] = useState<{templateId: string; sections: SciSection[]} | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  const focusNewSection = useRef<string | null>(null)
  const addChapterButton = useRef<HTMLButtonElement | null>(null)
  useEffect(() => {
    const abort = () => request.current?.abort()
    const unsubscribe = onApiSessionChanged(abort)
    return () => {abort(); unsubscribe()}
  }, [])

  const settings = read.data
  const options = Array.isArray(settings?.templates)
    ? settings.templates.filter(template => validSciTemplate(template) && template.article_type === settings.article_type)
    : []
  const template = options.find(option => option.id === (choice ?? settings?.selected_template_id)) ?? options[0]
  const selected = !!template && template.id === settings?.selected_template_id
  const savedSections = (selected && settings?.selected_sections ? settings.selected_sections : template?.sections) ?? []
  const sections = editedSections && editedSections.templateId === template?.id ? editedSections.sections : savedSections
  const review = template?.article_type === 'narrative_review'
  const applied = selected && settings?.figure_workflow === true && (!review || settings.combine_review_topics === true)
  const dirty = !sameSections(sections, savedSections)
  const locked = saving || read.loading || !read.valid
  useDraftLeaveGuard(registerLeaveGuard, dirty, saving)

  const outline = sections.map(({id, en, zh, level}) => ({id, en: en.trim(), zh: zh.trim(),
    ...(level !== undefined && level !== defaultSectionLevel(id) ? {level} : {})}))
  const complete = outline.every(section => section.en && section.zh)
  const unique = new Set(outline.map(row => row.en)).size === outline.length && new Set(outline.map(row => row.zh)).size === outline.length
  const canSave = !!template && complete && unique && !locked && !read.error
  const updateSections = (value: SciSection[]) => {
    if (template) setEditedSections({templateId: template.id, sections: value})
    setError('')
  }
  const sectionDrag = useSciSectionDrag(sections, locked, updateSections)

  function addChapter() {
    const id = 'sci-section-' + crypto.randomUUID().replaceAll('-', '')
    focusNewSection.current = id
    updateSections([...sections.slice(0, -1), {id, en: '', zh: ''}, sections[sections.length - 1]])
  }

  async function applyTemplate() {
    if (!settings || !template || !canSave || request.current) return
    const controller = new AbortController()
    request.current = controller
    setSaving(true)
    setError('')
    try {
      const response = await intakeRequest<TemplateSettings>(url, {
        method: 'PUT', headers: {'Content-Type': 'application/json'}, signal: controller.signal,
        body: JSON.stringify({expected_revision: settings.revision, template_id: template.id, sections: outline,
          combine_review_topics: review || undefined, figure_workflow:true}),
      })
      if (controller.signal.aborted) return
      if (response?.selected_template_id !== template.id || response.article_type !== template.article_type ||
          ![settings.revision, settings.revision + 1].includes(response.revision) ||
          !sameSections(response.selected_sections ?? [], outline) || response.figure_workflow === false ||
          review && response.combine_review_topics !== true) {
        throw new Error('模板保存结果待确认，请重试。')
      }
      onContinue()
    } catch (cause) {
      if (controller.signal.aborted) return
      setError(safeError(cause, 'SCI 模板保存失败，请重试。'))
      if (cause instanceof IntakeError && cause.status === 409) read.refresh()
    } finally {
      request.current = null
      if (!controller.signal.aborted) setSaving(false)
    }
  }

  const english = language === 'en'
  const fields = english ? (['en', 'zh'] as const) : (['zh', 'en'] as const)
  return <section className="customer-section sci-template-step">
    <h1 ref={headingRef} tabIndex={-1} className="visually-hidden">{t('模板设定和资源配置')}</h1>
    <div className="sci-template-panel">
      {read.error ? <p role="alert" className="error-panel">{t(read.error)}{' '}
        <button type="button" onClick={read.refresh}>{t('重试')}</button></p>
        : !settings ? <p role="status">{t('正在读取 SCI 模板……')}</p>
        : !settings.article_type ? <div>
          <p>{t('请先在项目资料中选择论文类型。')}</p>
          <button type="button" onClick={onDetails}>{t('补充 SCI 建项资料')}</button>
        </div> : !template ? <p role="alert">{t('当前论文类型没有可用模板。')}</p> : <>
          <label>{t('SCI 模板')}
            <select value={template.id} disabled={locked} onChange={event => {
              setChoice(event.target.value)
              setEditedSections(null)
              setError('')
            }}>
              {options.map(option => <option key={option.id} value={option.id}>{t(option.name)}</option>)}
            </select>
          </label>
          <div className="sci-template-outline">
            <div className="sci-template-outline-heading">
              <h2>{t('初稿章节')}</h2>
              <button ref={addChapterButton} type="button" className="button-quiet sci-template-add"
                onClick={addChapter} disabled={locked || sections.length >= maxSciSections}>
                <WorkspaceIcon name="plus" />{t('添加章节')}
              </button>
            </div>
            <ol aria-label={t('初稿章节')} ref={sectionDrag.listRef} data-sorting={sectionDrag.sorting || undefined}>
              {sections.map((section, index) => <li key={section.id} {...sectionDrag.row(index)}>
                <div className="sci-template-section-row">
                  {fields.map(field => <textarea key={field} className="sci-template-title" rows={1} maxLength={200} disabled={locked}
                    ref={field === fields[0] && focusNewSection.current === section.id ? input => {
                      if (input) {
                        input.focus()
                        focusNewSection.current = null
                      }
                    } : undefined}
                    aria-label={t(field === 'zh' ? '第 {number} 项中文标题' : '第 {number} 项英文标题', {number: index + 1})}
                    lang={field === 'zh' ? 'zh-CN' : 'en'} value={section[field]} title={section[field]}
                    onChange={event => {
                      const heading = event.target.value.replace(/[\r\n]/g, '')
                      updateSections(sections.map(row => row.id === section.id ? {...row, [field]: heading} : row))
                    }} />)}
                  <HeadingLevel label={t('第 {number} 项标题级别', {number: index + 1})} title={section.id === 'title'}
                    value={section.level ?? defaultSectionLevel(section.id)} disabled={locked}
                    onChange={level => updateSections(sections.map(row => row.id === section.id ? {...row, level} : row))} />
                  <DragHandle {...sectionDrag.handle(index)} fixed={section.id === 'title' || section.id === 'references'}
                    heading={section[fields[0]] || section[fields[1]] || t('第 {number} 章', {number: index + 1})} />
                  {isCustomSciSection(section.id) && <button type="button" className="button-quiet sci-template-remove" disabled={locked}
                    aria-label={t('删除第 {number} 章', {number: index + 1})} onClick={() => {
                      updateSections(sections.filter(row => row.id !== section.id))
                      addChapterButton.current?.focus()
                    }}>×</button>}
                </div>
              </li>)}
            </ol>
          </div>
          {(!complete || !unique) && <p role="alert" className="error-panel">{t('章节标题不能为空，主章节标题不得重复。')}</p>}
        </>}
      {error && <p role="alert" className="error-panel">{t(error)}</p>}
    </div>
    {template && <footer className="customer-step-actions">
      <button type="button" className="button-primary" disabled={!canSave} onClick={() => void applyTemplate()}>
        {t(saving ? '正在保存……' : applied && !dirty ? '继续资源配置' : '使用模板并继续')}
      </button>
    </footer>}
  </section>
}
