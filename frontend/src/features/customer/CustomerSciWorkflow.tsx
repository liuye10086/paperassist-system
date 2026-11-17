import type { Ref } from 'react'
import { useI18n } from '../../shared/i18n'
import JournalWorkspace from '../journals/JournalWorkspace'
import ProjectManuscripts from '../manuscripts/ProjectManuscripts'
import { journalViews } from '../projects/manuscriptViews'
import type { Project } from '../projects/projectTypes'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { projectBase } from '../research-intake/api'
import { useResearchRead } from '../research-results/api'
import CustomerWritingMaterials from './CustomerWritingMaterials'
import { customerManuscriptNavigation, type UpdatePaperRoute } from './customerPaperNavigation'
import { validCustomerRouteId } from './customerReviewNavigation'
import { articleTypes, type SciSettingsState } from './sciProjectSettings'

type Step = 'materials' | 'citations' | 'manuscripts' | 'journals' | 'word'
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
  materials: '写作资料与引用', citations: '写作资料与引用', manuscripts: '稿件与复核', journals: '期刊适配与 Word', word: '固定版本与 Word',
}

export default function CustomerSciWorkflow({
  project, step, headingRef, registerLeaveGuard, onUnavailable, onNavigate, params, onUpdateRoute, onStartReview,
}: Props) {
  const { t } = useI18n()
  const id = project.id
  const outputLanguage = project.default_output_language ?? 'zh-CN'
  const receipt = useResearchRead<SciSettingsState>(projectBase(id) + '/sci-settings', step !== 'word')
  const settings = receipt.data?.settings ?? null
  const materialsStep = step === 'materials' || step === 'citations'
  const manuscript = customerManuscriptNavigation(params, step === 'word')
  const adaptation = params.get('adaptation')
  const adaptationId = validCustomerRouteId(adaptation) ? adaptation : undefined
  const journalView = journalViews.find(view => view !== 'submission' && view === params.get('view')) ??
    (adaptationId ? 'adaptation' : 'overview')

  return <section className="customer-section customer-manuscript-workflow">
    <div className="customer-section-heading">
      <h1 ref={headingRef} tabIndex={-1}>{t(titles[step])}</h1>
      {step === 'journals' && <button type="button" className="button-primary" onClick={() => onNavigate('word')}>{t('通用 Word 与固定版本')}</button>}
      {step === 'word' && <button type="button" className="button-quiet" onClick={() => onNavigate('journals')}>{t('返回期刊适配')}</button>}
      {step === 'manuscripts' && <button type="button" className="button-quiet" onClick={() => onNavigate('word')}>{t('固定版本与 Word')}</button>}
    </div>
    {step !== 'word' && receipt.error && <p role="alert" className="error-panel">{t(receipt.error)}{' '}
      <button type="button" onClick={receipt.refresh}>{t('重试')}</button>
    </p>}
    {step !== 'word' && !receipt.data && !receipt.error && <p role="status">{t('正在读取 SCI 建项资料……')}</p>}
    {step !== 'word' && receipt.data && !settings && <p className="warning-panel">{t('此项目尚未保存 SCI 建项资料。')}
      {' '}<button type="button" onClick={() => onNavigate('details')}>{t('补充 SCI 建项资料')}</button>
    </p>}
    {(step === 'manuscripts' || materialsStep) && settings && <section className="manuscript-panel sci-workflow-context" aria-label={t('已保存的写作意向')}>
      <h2>{t('已保存的写作意向')} · {t(articleTypes[settings.article_type])}</h2>
      <p className="muted">{t('主要结果或结论与图表计划来自建项填写。请在事实稿中选择对应资料并核对来源。')}</p>
      <dl className="sci-settings-summary">
        <dt>{t('关键词')}</dt><dd>{settings.keywords.join('、')}</dd>
        <dt>{t('客户提供的主要结果或结论')}</dt><dd>{settings.main_results}</dd>
        <dt>{t('图表计划（待绑定实际图表）')}</dt>
        <dd><ul>{settings.figure_plan.map((figure, i) => <li key={i}><strong>{figure.title}</strong> · <span>{figure.description}</span></li>)}</ul></dd>
      </dl>
    </section>}
    {materialsStep && <CustomerWritingMaterials project={project} startWithCitations={step === 'citations'}
      initialQuery={settings?.keywords.join(' AND ')} literatureReady={!!(receipt.data || receipt.error)}
      params={params} onUpdateRoute={onUpdateRoute}
      onContinue={() => onNavigate('manuscripts')} onUnavailable={onUnavailable} registerLeaveGuard={registerLeaveGuard} />}
    {(step === 'word' || step === 'manuscripts') && manuscript.invalid &&
      <p role="alert">{t('指定固定稿件版本不可用；不会自动替换为最新版本。')}</p>}
    {(step === 'word' || step === 'manuscripts' && !!receipt.data) && <ProjectManuscripts
      projectId={id} researchTopic={project.research_topic} outputLanguage={outputLanguage} active
      projectType="sci" customerSci={{ settings, wordOnly: step === 'word' }}
      initialManuscript={manuscript.manuscriptId} initialRevision={manuscript.revision} view={manuscript.view}
      onSelectVersion={(id, revision) => onUpdateRoute({ manuscript: id, revision, view: step === 'word' ? 'exports' : 'body' }, true)}
      onViewChange={view => onUpdateRoute({ view: step === 'word' && view === 'body' ? 'exports' : view }, true)}
      onStartReview={onStartReview}
      onOpenLiterature={() => onNavigate('citations')} registerLeaveGuard={registerLeaveGuard} />}
    {step === 'journals' && params.has('adaptation') && !adaptationId &&
      <p role="alert">{t('指定适配记录尚未读取，请刷新；不会代用其他记录。')}</p>}
    {step === 'journals' && receipt.data && <JournalWorkspace projectId={id} active view={journalView}
      initialAdaptation={adaptationId} onSelectAdaptation={adaptation => onUpdateRoute({ adaptation, view: 'adaptation' }, true)}
      onViewChange={view => onUpdateRoute({ view }, true)} customerSci={settings} registerLeaveGuard={registerLeaveGuard} />}
  </section>
}
