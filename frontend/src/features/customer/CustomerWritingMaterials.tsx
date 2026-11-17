import { useState } from 'react'
import { useI18n } from '../../shared/i18n'
import ProjectLiterature from '../literature/ProjectLiterature'
import type { LiteratureView } from '../projects/literatureViews'
import type { Project } from '../projects/projectTypes'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import CustomerMaterials from './CustomerMaterials'
import type { UpdatePaperRoute } from './customerPaperNavigation'
import { validCustomerRouteId } from './customerReviewNavigation'

const literatureViews: LiteratureView[] = ['list', 'search', 'history', 'detail', 'evidence', 'citations']

type Props = {
  project: Project
  startWithCitations: boolean
  projectKeywords?: readonly string[]
  literatureReady?: boolean
  onContinue: () => void
  onRequirements: () => void
  onUnavailable: () => void
  registerLeaveGuard: RegisterLeaveGuard
  params: URLSearchParams
  onUpdateRoute: UpdatePaperRoute
}

export default function CustomerWritingMaterials({
  project, startWithCitations, projectKeywords, literatureReady = true, onContinue, onRequirements, onUnavailable, registerLeaveGuard,
  params, onUpdateRoute,
}: Props) {
  const { t } = useI18n()
  const routeView = params.get('view')
  const literatureView = literatureViews.find(view => view === routeView)
  const showUpload = routeView === 'files' || (!startWithCitations && !literatureView)
  const search = params.get('search')
  const reference = params.get('reference')
  const searchId = validCustomerRouteId(search) ? search : ''
  const referenceId = validCustomerRouteId(reference) ? reference : ''
  const [openUpload, setOpenUpload] = useState(showUpload)
  const [openLiterature, setOpenLiterature] = useState(!showUpload)
  if (showUpload && !openUpload) setOpenUpload(true)
  if (!showUpload && !openLiterature) setOpenLiterature(true)
  return <>
    <div className="customer-switches" role="group" aria-label={t('写作资料视图')}>
      <button type="button" className="button-quiet" aria-pressed={showUpload}
        onClick={() => onUpdateRoute({ view: 'files' })}>{t('项目文件')}</button>
      <button type="button" className="button-quiet" aria-pressed={!showUpload}
        onClick={() => onUpdateRoute({ view: literatureView ?? 'list' })}>{t('文献与引用')}</button>
    </div>
    {openUpload && <div hidden={!showUpload}>
      <CustomerMaterials projectId={project.id} onContinue={onContinue} onUnavailable={onUnavailable}
        registerLeaveGuard={registerLeaveGuard} active={showUpload} forWriting={project.project_type === 'thesis' ? 'thesis' : 'sci'}
        onRequirements={onRequirements} />
    </div>}
    {!showUpload && !literatureReady && <p role="status">{t('正在读取项目关键词……')}</p>}
    {openLiterature && literatureReady && <ProjectLiterature projectId={project.id} researchTopic={project.research_topic}
      outputLanguage={project.default_output_language ?? 'zh-CN'} projectKeywords={projectKeywords} initialSearchId={searchId}
      literatureNavigation={{ view: literatureView ?? 'list', referenceId }}
      onSearchChange={search => onUpdateRoute({ search, view: 'list', reference: undefined }, true)}
      onLiteratureNavigate={({ view, referenceId }) => onUpdateRoute({ view, reference: referenceId }, true)}
      active={!showUpload} customerSci registerLeaveGuard={registerLeaveGuard} />}
  </>
}
