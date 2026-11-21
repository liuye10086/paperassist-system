import { useEffect, useRef, useState, type FormEvent } from 'react'
import type { Locale } from '../../shared/i18n'
import { safeError, useI18n } from '../../shared/i18n'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { IntakeError, intakeRequest, projectBase } from '../research-intake/api'
import { useResearchRead } from '../research-results/api'
import useResearchDraft from '../research-results/useResearchDraft'
import ThesisBasicsFields from './ThesisBasicsFields'
import ThesisChapterRequirements from './ThesisChapterRequirements'
import { prepareThesisBasics, thesisBasicsDraft, thesisLanguages, type ThesisBasicsDraft, type ThesisRequirements, type ThesisSection } from './thesisProjectRequirements'

type Props = {
  projectId: string
  onOpenTemplate: () => void
  /** After a confirmed save, go on: to the school template, or to the writing materials once one is adopted (wireframe 23). */
  onContinue?: (templateAdopted: boolean) => void
  onLanguageChanged: () => void
  registerLeaveGuard: RegisterLeaveGuard
}
type Edit = {
  revision: number
  expectedLanguage: Locale
  confirmationId: string | null
  basics: ThesisBasicsDraft
  sections: ThesisSection[]
}

function editRequirements(state: ThesisRequirements): Edit {
  return {
    revision: state.revision, expectedLanguage: state.language, confirmationId: state.template?.confirmation_id ?? null,
    basics: thesisBasicsDraft(state), sections: state.sections,
  }
}

export default function CustomerThesisRequirements(props: Props) {
  const { t } = useI18n()
  const url = projectBase(props.projectId) + '/thesis-requirements'
  const read = useResearchRead<ThesisRequirements>(url, true)
  return <section className="customer-thesis-requirements" aria-label={t('毕业论文需求')}>
    <h2>{t('毕业论文需求')}</h2>
    {read.error && <div role="alert" className="error-panel">{t(read.error)}{' '}
      <button type="button" onClick={read.refresh}>{t('重试')}</button>
    </div>}
    {read.data ? <RequirementsEditor {...props} url={url} receipt={read.data} refresh={read.refresh} /> :
      !read.error && <p role="status">{t('正在读取毕业论文需求……')}</p>}
  </section>
}

function RequirementsEditor({ projectId, onOpenTemplate, onContinue, onLanguageChanged, registerLeaveGuard, url, receipt, refresh }: Props & {
  url: string; receipt: ThesisRequirements; refresh: () => void
}) {
  const { t } = useI18n()
  const [edit, setEdit] = useResearchDraft<Edit | null>(projectId, 'customer-thesis-requirements', () => null)
  const [saved, setSaved] = useState<ThesisRequirements | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])
  const current = saved && saved.revision > receipt.revision ? saved : receipt
  const baseline = editRequirements(current)
  const template = current.template
  const stale = !!edit && (edit.revision !== baseline.revision || edit.expectedLanguage !== baseline.expectedLanguage ||
    edit.confirmationId !== baseline.confirmationId)
  useDraftLeaveGuard(registerLeaveGuard, !!edit && JSON.stringify(edit) !== JSON.stringify(baseline), busy)

  function change(next: Edit | null) {
    setEdit(next)
    setError('')
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!edit || stale || request.current) return
    const fields = prepareThesisBasics(edit.basics)
    if ('error' in fields) { setError(fields.error); return }
    const sections = edit.sections.map(item => ({ ...item, content: item.content.trim() }))
    if (sections.some(item => !item.content)) { setError('请填写已添加章节所需涵盖的内容。'); return }
    const chapterPlan = template && JSON.stringify(sections) !== JSON.stringify(current.sections)
      ? { confirmation_id: template.confirmation_id, sections } : undefined
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    setError('')
    try {
      const value = await intakeRequest<ThesisRequirements>(url, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
        body: JSON.stringify({ ...fields, expected_revision: edit.revision, expected_language: edit.expectedLanguage,
          ...(chapterPlan ? { chapter_plan: chapterPlan } : {}) }),
      })
      if (controller.signal.aborted) return
      if (!value?.title || ![edit.revision, edit.revision + 1].includes(value.revision)) {
        throw new Error('毕业论文需求保存结果待确认，请重试原请求。')
      }
      setSaved(value)
      change(null)
      refresh()
      if (value.language !== current.language) onLanguageChanged()
      onContinue?.(!!value.template)
    } catch (cause) {
      if (controller.signal.aborted) return
      setError(safeError(cause, '毕业论文需求保存失败，请重试。'))
      if (cause instanceof IntakeError && cause.status === 409) refresh()
    } finally {
      request.current = null
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  const templateLink = <div className="sci-inline-controls thesis-template-link">
    <span>{template ? t('已采用学校模板 · {name}', { name: template.name }) : t('请上传学校 Word 模板，确认规则并采用后填写章节内容。')}</span>
    <button type="button" className="button-quiet" disabled={busy} onClick={onOpenTemplate}>{t('前往学校模板')}</button>
  </div>
  return <>
    {(!edit || stale) && <>
      <dl className="sci-settings-summary">
        <dt>{t('学位层次')}</dt><dd>{current.education_level ? t(current.education_level) : t('未填写')}</dd>
        <dt>{t('论文语种')}</dt><dd>{t(thesisLanguages[current.language])}</dd>
        <dt>{t('学校名称')}</dt><dd>{current.school || t('未填写')}</dd>
        <dt>{t('论文题目')}</dt><dd>{current.title || t('未填写')}</dd>
        <dt>{t('关键词')}</dt><dd>{current.keywords.join(' · ') || t('未填写')}</dd>
      </dl>
      {templateLink}
      {template && <ThesisChapterRequirements template={template} sections={current.sections} />}
    </>}
    {!edit && <button type="button" onClick={() => change(baseline)}>{t(current.title ? '编辑毕业论文需求' : '填写毕业论文需求')}</button>}
    {edit && <form className="thesis-requirements-edit" aria-busy={busy} noValidate onSubmit={event => void save(event)}>
      {stale ? <div className="warning-panel" role="status">
        {t('毕业论文需求或学校资料已更新，请核对后继续。')}{' '}
        <button type="button" onClick={() => change(baseline)}>{t('使用最新毕业论文需求')}</button>
      </div> : <>
        <ThesisBasicsFields draft={edit.basics} disabled={busy} onChange={basics => change({ ...edit, basics })} onError={setError} />
        {templateLink}
        {template && <ThesisChapterRequirements key={template.confirmation_id} template={template} sections={edit.sections}
          disabled={busy} onChange={sections => change({ ...edit, sections })} />}
      </>}
      {error && <p role="alert" className="error-panel">{t(error)}</p>}
      <div className="sci-inline-controls">
        <button type="submit" className="button-primary" disabled={busy || stale}>{t(busy ? '正在保存……' : !onContinue ? '保存毕业论文需求'
          : template ? '保存并继续 写作资料与引用' : '保存并继续 学校模板')}</button>
        <button type="button" disabled={busy} onClick={() => change(null)}>{t('取消')}</button>
      </div>
    </form>}
  </>
}
