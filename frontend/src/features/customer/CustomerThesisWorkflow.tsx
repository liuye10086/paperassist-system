import type { Ref } from 'react'
import { useI18n } from '../../shared/i18n'
import ProjectManuscripts from '../manuscripts/ProjectManuscripts'
import { schoolTemplateViews, type SchoolTemplateNavigation } from '../projects/manuscriptViews'
import type { Project } from '../projects/projectTypes'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { projectBase, useResearchRead } from '../research-results/api'
import SchoolTemplates from '../school-templates/SchoolTemplates'
import CustomerWritingMaterials from './CustomerWritingMaterials'
import { customerManuscriptNavigation, type UpdatePaperRoute } from './customerPaperNavigation'
import { validCustomerRouteId } from './customerReviewNavigation'
import type { ThesisRequirements } from './thesisProjectRequirements'

type Step = 'school' | 'materials' | 'citations' | 'manuscripts' | 'word'
type Props = {
  project: Project
  step: Step
  headingRef: Ref<HTMLHeadingElement>
  registerLeaveGuard: RegisterLeaveGuard
  onUnavailable: () => void
  onNavigate: (step: Step | 'details') => void
  params: URLSearchParams
  onUpdateRoute: UpdatePaperRoute
  onStartReview: (id: string, revision: number) => void
}
const titles: Record<Step, string> = {
  school: '学校模板', materials: '写作资料与引用', citations: '写作资料与引用',
  manuscripts: '章节与复核', word: '固定版本与 Word',
}

export default function CustomerThesisWorkflow({
  project, step, headingRef, registerLeaveGuard, onUnavailable, onNavigate, params, onUpdateRoute, onStartReview,
}: Props) {
  const { t } = useI18n()
  const wordOnly = step === 'word'
  const materialsStep = step === 'materials' || step === 'citations'
  const requirements = useResearchRead<ThesisRequirements>(projectBase(project.id) + '/thesis-requirements', materialsStep)
  const manuscript = customerManuscriptNavigation(params, wordOnly, true)
  const template = params.get('template')
  const templateId = validCustomerRouteId(template) ? template : ''
  const schoolView: SchoolTemplateNavigation = {
    view: schoolTemplateViews.find(view => view === params.get('view')) ?? (templateId ? 'detail' : 'list'),
    templateId,
  }

  return <section className="customer-section customer-manuscript-workflow">
    <div className="customer-section-heading">
      <h1 ref={headingRef} tabIndex={-1}>{t(titles[step])}</h1>
      {step === 'school' && <div className="sci-inline-controls">
        <button type="button" className="button-quiet" onClick={() => onNavigate('details')}>{t('查看毕业论文需求')}</button>
        <button type="button" className="button-quiet" onClick={() => onNavigate('materials')}>{t('下一步 写作资料与引用')}</button>
      </div>}
      {step === 'manuscripts' && <button type="button" className="button-quiet"
        onClick={() => onNavigate('word')}>{t('查看固定版本 Word')}</button>}
    </div>
    {step === 'school' && params.has('template') && !templateId && <p role="alert">{t('指定学校模板版本不可用。')}</p>}
    {step === 'school' && <SchoolTemplates projectId={project.id} active customerView navigation={schoolView}
      onNavigate={({ view, templateId }) => onUpdateRoute({ view, template: templateId }, true)} registerLeaveGuard={registerLeaveGuard} />}
    {materialsStep && <CustomerWritingMaterials project={project}
      startWithCitations={step === 'citations'} onContinue={() => onNavigate('manuscripts')} onRequirements={() => onNavigate('details')}
      projectKeywords={requirements.data?.keywords} literatureReady={!!(requirements.data || requirements.error)}
      params={params} onUpdateRoute={onUpdateRoute}
      onUnavailable={onUnavailable} registerLeaveGuard={registerLeaveGuard} />}
    {(step === 'manuscripts' || wordOnly) && manuscript.invalid &&
      <p role="alert">{t('指定固定稿件版本不可用；不会自动替换为最新版本。')}</p>}
    {(step === 'manuscripts' || wordOnly) && <ProjectManuscripts projectId={project.id}
      researchTopic={project.research_topic} outputLanguage={project.default_output_language ?? 'zh-CN'}
      active projectType="thesis" customerThesis={{ wordOnly }} view={manuscript.view}
      initialManuscript={manuscript.manuscriptId} initialRevision={manuscript.revision}
      onSelectVersion={(id, revision) => onUpdateRoute({ manuscript: id, revision, view: wordOnly ? 'exports' : 'body' }, true)}
      onViewChange={view => onUpdateRoute({ view: wordOnly && view === 'body' ? 'exports' : view }, true)}
      onStartReview={onStartReview}
      onOpenLiterature={() => onNavigate('citations')} onOpenSchoolTemplate={() => onNavigate('school')}
      onOpenRequirements={() => onNavigate('details')} onOpenMaterials={() => onNavigate('materials')}
      registerLeaveGuard={registerLeaveGuard} />}
  </section>
}
