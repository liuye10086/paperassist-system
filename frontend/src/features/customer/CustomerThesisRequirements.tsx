import { useEffect, useRef, useState, type FormEvent } from 'react'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import type { Locale } from '../../shared/i18n'
import { safeError, useI18n } from '../../shared/i18n'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { IntakeError, intakeRequest, projectBase } from '../research-intake/api'
import { useResearchRead } from '../research-results/api'
import useResearchDraft from '../research-results/useResearchDraft'
import ThesisBasicsFields from './ThesisBasicsFields'
import ThesisChapterRequirements from './ThesisChapterRequirements'
import { prepareThesisBasics, thesisBasicsDraft, thesisLanguages, type ThesisBasicsDraft, type ThesisRequirements, type ThesisSection } from './thesisProjectRequirements'

type CommonProps = {
  projectId: string
  registerLeaveGuard: RegisterLeaveGuard
}
type BasicsProps = CommonProps & {onLanguageChanged:() => void; onContinue?:() => void}
type OrganizerProps = CommonProps & {onOpenTemplate:(hasTemplate:boolean) => void; onOpenProject?:() => void;
  onSectionsSaved?:() => void; figureConfigRevision?: number}
type Props = BasicsProps | OrganizerProps
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

function sameBaseline(edit:Edit, baseline:Edit) {
  return edit.revision === baseline.revision && edit.expectedLanguage === baseline.expectedLanguage &&
    edit.confirmationId === baseline.confirmationId
}

export default function CustomerThesisRequirements(props: BasicsProps) {
  return <RequirementsPage {...props}/>
}

export function ThesisTemplateOrganizer(props: OrganizerProps) {
  return <RequirementsPage {...props}/>
}

function RequirementsPage(props: Props) {
  const { t } = useI18n()
  const url = projectBase(props.projectId) + '/thesis-requirements'
  const read = useResearchRead<ThesisRequirements>(url, true)
  const organizer = 'onOpenTemplate' in props
  const content = <>
    {read.error && <div role="alert" className="error-panel">{t(read.error)}{' '}
      <button type="button" onClick={read.refresh}>{t('重试')}</button>
    </div>}
    {read.data ? <RequirementsEditor {...props} url={url} receipt={read.data} loading={read.loading} refresh={read.refresh} /> :
      !read.error && <p role="status">{t('正在读取毕业论文需求……')}</p>}
  </>
  return organizer ? <div className="thesis-template-page">{content}</div>
    : <section className="customer-thesis-requirements" aria-label={t('毕业论文需求')}>
      <h2>{t('毕业论文需求')}</h2>{content}
    </section>
}

function RequirementsEditor(props: Props & {
  url: string; receipt: ThesisRequirements; loading: boolean; refresh: () => void
}) {
  const { t } = useI18n()
  const {projectId, registerLeaveGuard, url, receipt, refresh} = props
  const organizer = 'onOpenTemplate' in props
  const figureConfigRevision = organizer ? props.figureConfigRevision : undefined
  const lastFigureConfigRevision = useRef(figureConfigRevision)
  const [basicEdit, setBasicEdit] = useResearchDraft<Edit | null>(projectId, 'customer-thesis-requirements', () => null)
  const [chapterEdit, setChapterEdit] = useResearchDraft<Edit | null>(projectId, 'customer-thesis-chapter-requirements', () => null)
  const [saved, setSaved] = useState<ThesisRequirements | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])
  const current = saved && saved.revision > receipt.revision ? saved : receipt
  const baseline = editRequirements(current)
  const template = current.template
  // Before the editing steps were split, both parts could be present in a single unsaved draft.
  const legacyChapters = basicEdit && sameBaseline(basicEdit,baseline) && template &&
    JSON.stringify(basicEdit.sections) !== JSON.stringify(current.sections)
    ? basicEdit.sections : null
  const edit = organizer ? chapterEdit ?? (legacyChapters ? {...baseline,sections:legacyChapters} : null) : basicEdit
  const stale = !!edit && !sameBaseline(edit,baseline)
  const dirty = !!edit && JSON.stringify(edit) !== JSON.stringify(baseline)
  const syncingFigures = figureConfigRevision !== undefined && props.loading
  useDraftLeaveGuard(registerLeaveGuard, dirty, busy)
  useEffect(() => {
    if (dirty || busy || figureConfigRevision === lastFigureConfigRevision.current) return
    lastFigureConfigRevision.current = figureConfigRevision
    refresh()
  }, [busy, dirty, figureConfigRevision, refresh])

  function change(next: Edit | null) {
    if (organizer) {
      setChapterEdit(next)
      if (legacyChapters && basicEdit) setBasicEdit({...basicEdit,sections:current.sections})
    } else {
      if (!next && legacyChapters && !chapterEdit) setChapterEdit({...baseline,sections:legacyChapters})
      setBasicEdit(next)
    }
    setError('')
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!edit || stale || request.current) return
    const fields = prepareThesisBasics(organizer ? baseline.basics : edit.basics)
    if ('error' in fields) { setError(fields.error); return }
    const sections = edit.sections.map(item => ({ ...item, content: item.content.trim() })).filter(item => item.content)
    const chapterPlan = organizer && template && JSON.stringify(sections) !== JSON.stringify(current.sections)
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
      if (organizer) {
        setChapterEdit(null)
        if (basicEdit && sameBaseline(basicEdit,baseline)) {
          setBasicEdit({...editRequirements(value),basics:basicEdit.basics})
        }
      } else {
        const pending = chapterEdit ? sameBaseline(chapterEdit,baseline) && chapterEdit.sections : legacyChapters
        if (pending && value.template?.confirmation_id === current.template?.confirmation_id &&
          JSON.stringify(current.sections) === JSON.stringify(value.sections)) {
          setChapterEdit({...editRequirements(value),sections:pending})
        }
        setBasicEdit(null)
      }
      setError('')
      refresh()
      if (organizer) {
        if (chapterPlan) props.onSectionsSaved?.()
      } else {
        if (value.language !== current.language) props.onLanguageChanged()
        props.onContinue?.()
      }
    } catch (cause) {
      if (controller.signal.aborted) return
      setError(safeError(cause, '毕业论文需求保存失败，请重试。'))
      if (cause instanceof IntakeError && cause.status === 409) refresh()
    } finally {
      request.current = null
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  const changed = edit && JSON.stringify(edit.sections) !== JSON.stringify(current.sections)
  const staleNotice = <div className="warning-panel" role="status">
    {t('毕业论文需求或学校资料已更新，请核对后继续。')}{' '}
    <button type="button" onClick={() => change(baseline)}>{t('使用最新毕业论文需求')}</button>
  </div>
  const errorNotice = error && <p role="alert" className="error-panel">{t(error)}</p>
  if (organizer) return <>
    {template ? <>
      <header className="thesis-template-heading">
        <div>
          <h2>{t('已采用学校模板 · {name}', {name:template.name})}</h2>
          {template.source_file && template.source_file.filename !== template.name &&
            <p className="muted">{template.source_file.filename}</p>}
        </div>
        <div className="sci-inline-controls thesis-template-actions">
          {template.source_file && <ProjectDownloadLink
            href={`${projectBase(projectId)}/files/${encodeURIComponent(template.source_file.file_id)}/download`}
            filename={template.source_file.filename}>{t('下载模板原件')}</ProjectDownloadLink>}
          <button type="button" className="button-quiet" disabled={busy} onClick={() => props.onOpenTemplate(true)}>{t('更换模板')}</button>
        </div>
      </header>
      <form className="thesis-requirements-edit" aria-busy={busy} noValidate onSubmit={event => void save(event)}>
        {stale ? staleNotice : <ThesisChapterRequirements key={template.confirmation_id} template={template}
          sections={edit?.sections ?? current.sections} disabled={busy || syncingFigures}
          onChange={sections => change({...baseline,sections})}/>}
        {errorNotice}
        {props.onOpenProject && 'error' in prepareThesisBasics(baseline.basics) &&
          <button type="button" onClick={props.onOpenProject}>{t('填写毕业论文需求')}</button>}
        <div className="thesis-chapter-save">
          {saved && !edit && <span role="status">{t('章节内容已保存。')}</span>}
          <button type="submit" className="button-primary" disabled={busy || syncingFigures || stale || !changed}>
            {t(busy ? '正在保存……' : '保存章节内容')}</button>
        </div>
      </form>
    </> : <div className="sci-inline-controls">
      <p>{t('请上传学校 Word 模板，确认规则并采用后填写章节内容。')}</p>
      <button type="button" className="button-primary" onClick={() => props.onOpenTemplate(false)}>{t('上传学校模板')}</button>
    </div>}
  </>
  return <>
    {(!edit || stale) && <>
      <dl className="sci-settings-summary">
        <dt>{t('学位层次')}</dt><dd>{current.education_level ? t(current.education_level) : t('未填写')}</dd>
        <dt>{t('论文语种')}</dt><dd>{t(thesisLanguages[current.language])}</dd>
        <dt>{t('学校名称')}</dt><dd>{current.school || t('未填写')}</dd>
        <dt>{t('论文题目')}</dt><dd>{current.title || t('未填写')}</dd>
        <dt>{t('关键词')}</dt><dd>{current.keywords.join(' · ') || t('未填写')}</dd>
      </dl>
    </>}
    {!edit && <button type="button" onClick={() => change(baseline)}>{t(current.title ? '编辑毕业论文需求' : '填写毕业论文需求')}</button>}
    {edit && <form className="thesis-requirements-edit" aria-busy={busy} noValidate onSubmit={event => void save(event)}>
      {stale ? staleNotice :
        <ThesisBasicsFields draft={edit.basics} disabled={busy} onChange={basics => change({ ...edit, basics })} onError={setError} />}
      {errorNotice}
      <div className="sci-inline-controls">
        <button type="submit" className="button-primary" disabled={busy || stale}>{t(busy ? '正在保存……' : '保存并继续 上传资料')}</button>
        <button type="button" disabled={busy} onClick={() => change(null)}>{t('取消')}</button>
      </div>
    </form>}
  </>
}
