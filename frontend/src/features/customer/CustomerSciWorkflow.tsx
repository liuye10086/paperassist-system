import { useEffect, type Ref } from 'react'
import { useI18n } from '../../shared/i18n'
import type { Project } from '../projects/projectTypes'
import { projectBase } from '../research-intake/api'
import { useResearchRead } from '../research-results/api'
import { SciDraftGenerator, ThesisDraftGenerator } from './SciDraftGenerator'
import { SciDraftReader } from './SciDraftReader'
import { SciDraftRevision } from './SciDraftRevision'
import type { UpdatePaperRoute } from './customerPaperNavigation'
import { fixedRevision, validCustomerRouteId } from './customerReviewNavigation'
import type { ThesisRequirements } from './thesisProjectRequirements'
import { PastThesisOpinions, SavedThesisVersion, ThesisHistory } from './ThesisDraftHistory'
import type { SciSettingsState } from './sciProjectSettings'

type Draft = { manuscript_id: string; revision: number; request_id: string }

export default function CustomerSciWorkflow({ project, params, headingRef, onDetails, onMaterials, onOrganizer, onResources, onUpdateRoute, openSearch }: {
  project: Project; params: URLSearchParams; headingRef: Ref<HTMLHeadingElement>; onDetails: () => void
  onUpdateRoute: UpdatePaperRoute; openSearch?: boolean; onMaterials?: () => void; onOrganizer?: () => void; onResources?: () => void
}) {
  const { t } = useI18n()
  const base = projectBase(project.id)
  const view = params.get('view')
  const manuscript = params.get('manuscript')
  const revision = fixedRevision(params.get('revision'))
  const request = params.get('writingRequest')
  const pinned = params.has('manuscript') || params.has('revision') || params.has('writingRequest')
  const validVersion = validCustomerRouteId(manuscript) && !!revision
  const invalid = pinned && (!validVersion || (request !== null && !validCustomerRouteId(request)))
  const thesis = project.project_type === 'thesis'
  const history = thesis && view === 'draft-history'
  const pastOpinions = thesis && view === 'past-opinions' && validCustomerRouteId(params.get('round'))
  const saved = thesis && validVersion && !request && ['exports','saved','body'].includes(view ?? '')
  const search = openSearch || view === 'select'
  const query = validVersion ? '?' + new URLSearchParams({ manuscript_id: manuscript, revision: String(revision) }) : ''
  const current = useResearchRead<{ draft: Draft | null }>(base + '/sci-current-draft' + query, !invalid && !request && !history && !pastOpinions && !saved)
  const currentDraft = current.data?.draft
  const draft = validVersion && request ? { manuscript_id: manuscript, revision, request_id: request } : currentDraft
  const generator = search || (!pinned && currentDraft === null)
  const settings = useResearchRead<SciSettingsState>(base + '/sci-settings', generator && !thesis)
  const requirements = useResearchRead<ThesisRequirements>(base + '/thesis-requirements', generator && thesis)
  const clear = { round:undefined, item:undefined, reference:undefined, manuscript: undefined, revision: undefined, writingRequest: undefined, paragraph: undefined, search: undefined }
  const show = (manuscript: string, revision: number, writingRequest: string) =>
    onUpdateRoute({ ...clear, manuscript, revision, writingRequest, view: 'writing' }, true)
  useEffect(() => {
    if (search || invalid || request || history || pastOpinions || saved || !currentDraft) return
    // Keep the base request in the address so a refresh can resume the same conversation.
    onUpdateRoute({ manuscript: currentDraft.manuscript_id, revision: currentDraft.revision, writingRequest: currentDraft.request_id,
      view: 'writing' }, true, true)
  }, [currentDraft, history, invalid, onUpdateRoute, pastOpinions, request, saved, search])
  const currentButton = <button type="button" className="button-quiet"
    onClick={() => onUpdateRoute({ ...clear, view: undefined }, true)}>{t('查看当前初稿')}</button>

  let content
  if (invalid || (!thesis && !search && pinned && !request && current.data?.draft === null)) {
    content = <div role="alert">{t('这个版本没有可读取的正文。')} {currentButton}</div>
  } else if (history) {
    content = <ThesisHistory projectId={project.id} update={onUpdateRoute}/>
  } else if (pastOpinions) {
    content = <PastThesisOpinions projectId={project.id} roundId={params.get('round')!} update={onUpdateRoute}/>
  } else if (saved || (thesis && validVersion && !request && current.data?.draft === null)) {
    content = <SavedThesisVersion projectId={project.id} manuscript={manuscript!} revision={revision!} update={onUpdateRoute}/>
  } else if (generator) {
    content = <>
      {search && draft && <button type="button" className="button-quiet" onClick={() =>
        show(draft.manuscript_id, draft.revision, draft.request_id)}>{t('返回初稿')}</button>}
      {thesis ? (requirements.error ? <p role="alert">{t(requirements.error)} <button onClick={requirements.refresh}>{t('重试')}</button></p>
        : !requirements.data ? <p role="status">{t('正在读取毕业论文需求……')}</p>
        : <ThesisDraftGenerator project={project} requirements={requirements.data} onOpenProject={onDetails} onOpenMaterials={onMaterials} onOpenOrganizer={onOrganizer}
            onSubmitted={show} initialSearchId={validCustomerRouteId(params.get('search')) ? params.get('search')! : undefined}/>)
        : settings.error ? <p role="alert">{t(settings.error)} <button onClick={settings.refresh}>{t('重试')}</button></p>
        : !settings.data ? <p role="status">{t('正在读取 SCI 建项资料……')}</p>
        : !settings.data.settings ? <p>{t('此项目尚未保存 SCI 建项资料。')} <button onClick={onDetails}>{t('补充 SCI 建项资料')}</button></p>
        : <SciDraftGenerator project={project} settings={settings.data.settings} onSubmitted={show} onOpenProject={onDetails}
            onOpenOrganizer={onOrganizer} onOpenResources={onResources} />}
    </>
  } else if (draft) {
    const props = { thesis, projectId: project.id, manuscriptId: draft.manuscript_id, revision: draft.revision, requestId: draft.request_id }
    const adjustSources = () => onUpdateRoute({ manuscript: props.manuscriptId,
      revision: props.revision, writingRequest: props.requestId, view: 'select' })
    if (!thesis && view === 'body') {
      content = <>{currentButton}<SciDraftReader key={props.requestId} {...props}/></>
    } else {
      content = <SciDraftRevision key={props.requestId} {...props} onAdjustSources={adjustSources} />
    }
  } else if (current.error) {
    content = <p role="alert" className="error-panel">{t(current.error)} <button onClick={current.refresh}>{t('重试')}</button></p>
  } else {
    content = <p role="status">{t('正在读取初稿……')}</p>
  }
  return <section className="customer-section customer-manuscript-workflow">
    <div className="customer-section-heading"><h1 ref={headingRef} tabIndex={-1} className="visually-hidden">{t('文献与初稿')}</h1>
      {thesis && (history || saved || pastOpinions ? currentButton : <button type="button" className="button-quiet"
        onClick={() => onUpdateRoute({...clear, view:'draft-history'})}>{t('历史版本')}</button>)}
    </div>
    {content}
  </section>
}
