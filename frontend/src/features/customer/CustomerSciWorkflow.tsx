import { useEffect, useState, type Ref } from 'react'
import { useI18n } from '../../shared/i18n'
import JournalWorkspace from '../journals/JournalWorkspace'
import ProjectManuscripts from '../manuscripts/ProjectManuscripts'
import type { NeedSource } from '../manuscripts/WritingLive'
import { journalViews } from '../projects/manuscriptViews'
import type { Project } from '../projects/projectTypes'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { projectBase } from '../research-intake/api'
import { useResearchRead } from '../research-results/api'
import CustomerWritingMaterials from './CustomerWritingMaterials'
import SciSettingsSummary from './SciSettingsSummary'
import { customerManuscriptNavigation, type UpdatePaperRoute } from './customerPaperNavigation'
import { validCustomerRouteId } from './customerReviewNavigation'
import { isLegacySciSettings, type SciSettingsState } from './sciProjectSettings'
import ReturnBar from './ReturnBar'
import { readReturn } from './returnToken'

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
  onOpenWord: (manuscriptId: string, revision: number, options?: { adopted?: boolean }) => void
  onOpenWordTask?: (taskId: string) => void
  /** A review paragraph lacks a source: open literature or materials with a token back to it (B03 task 7). */
  onNeedSource?: NeedSource
  onFollowReturn?: (href: string) => void
  /** Writing materials take a published analysis result (B05 task 6, wireframe 18). */
  onOpenAnalysisResults?: () => void
}

const titles: Record<Step, string> = {
  materials: '写作资料与引用', citations: '写作资料与引用', manuscripts: '稿件与复核', journals: '期刊适配与 Word', word: '固定版本与 Word',
}

export default function CustomerSciWorkflow({
  project, step, headingRef, registerLeaveGuard, onUnavailable, onNavigate, params, onUpdateRoute, onStartReview, onOpenWord,
  onNeedSource, onFollowReturn, onOpenAnalysisResults, onOpenWordTask,
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
  // Adding a source for a review paragraph: the page shows where it returns to, and returns by itself once the
  // reference is ready or a file is uploaded.
  const paragraphReturn = materialsStep && params.get('returnLabel') === 'paragraph' ? readReturn(params, id) : null
  const materialsReturn = materialsStep && params.get('returnLabel') === 'materials' ? readReturn(params, id) : null
  // A manuscript opened from a review opinion or round (B05 task 7).
  const reviewReturn = step === 'manuscripts' && ['review-item', 'review-round'].includes(params.get('returnLabel') ?? '')
    ? readReturn(params, id) : null
  const [finished, setFinished] = useState(false)
  const finish = paragraphReturn && onFollowReturn ? () => setFinished(true) : undefined
  // oxlint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (finished && paragraphReturn) onFollowReturn?.(paragraphReturn.href) }, [finished])

  return <section className="customer-section customer-manuscript-workflow">
    <div className="customer-section-heading">
      <h1 ref={headingRef} tabIndex={-1}>{t(titles[step])}</h1>
      {step === 'journals' && <button type="button" className="button-primary" onClick={() => onNavigate('word')}>{t('通用 Word 与固定版本')}</button>}
      {step === 'word' && <button type="button" className="button-quiet" onClick={() => onNavigate('journals')}>{t('返回期刊适配')}</button>}
      {step === 'manuscripts' && <button type="button" className="button-quiet" onClick={() => manuscript.manuscriptId && manuscript.revision
        ? onOpenWord(manuscript.manuscriptId, manuscript.revision) : onNavigate('word')}>{t('固定版本与 Word')}</button>}
    </div>
    {paragraphReturn && <ReturnBar target={paragraphReturn} onReturn={onFollowReturn}>
      {t('正在为“{place}”补充依据', { place: paragraphReturn.label })}
    </ReturnBar>}
    {reviewReturn && <ReturnBar target={reviewReturn} onReturn={onFollowReturn}>
      {t('正在查看“{place}”所用的稿件', { place: reviewReturn.label })}
    </ReturnBar>}
    {finished && paragraphReturn && <p role="status">{t('完成并返回 {place}', { place: paragraphReturn.label })}</p>}
    {step !== 'word' && receipt.error && <p role="alert" className="error-panel">{t(receipt.error)}{' '}
      <button type="button" onClick={receipt.refresh}>{t('重试')}</button>
    </p>}
    {step !== 'word' && !receipt.data && !receipt.error && <p role="status">{t('正在读取 SCI 建项资料……')}</p>}
    {step !== 'word' && receipt.data && !settings && <p className="warning-panel">{t('此项目尚未保存 SCI 建项资料。')}
      {' '}<button type="button" onClick={() => onNavigate('details')}>{t('补充 SCI 建项资料')}</button>
    </p>}
    {settings && (materialsStep || step === 'manuscripts' && isLegacySciSettings(settings)) && <section className="manuscript-panel" aria-label={t('已保存的写作意向')}>
      <h2>{t('已保存的写作意向')}</h2>
      {isLegacySciSettings(settings) ? <>
        <p className="muted">{t('主要结果或结论与图表计划来自建项填写。请在写作材料中选择对应资料并核对来源。')}</p>
        <SciSettingsSummary settings={settings} />
      </> : <>
        <dl className="sci-settings-summary">
          <dt>{t('拟定论文题目')}</dt><dd>{settings.proposed_title}</dd>
          <dt>{t('关键词')}</dt><dd>{settings.keywords.join(' · ')}</dd>
        </dl>
        <button type="button" className="button-quiet" onClick={() => onNavigate('details')}>{t('查看 SCI 建项资料')}</button>
      </>}
    </section>}
    {materialsStep && <CustomerWritingMaterials project={project} startWithCitations={step === 'citations'}
      projectKeywords={settings?.keywords} literatureReady={!!(receipt.data || receipt.error)}
      params={params} onUpdateRoute={onUpdateRoute} onReferenceReady={finish} onUploaded={finish}
      onOpenAnalysisResults={onOpenAnalysisResults} materialsReturn={materialsReturn} onFollowReturn={onFollowReturn}
      onContinue={() => onNavigate('manuscripts')} onRequirements={() => onNavigate('details')} onUnavailable={onUnavailable} registerLeaveGuard={registerLeaveGuard} />}
    {(step === 'word' || step === 'manuscripts') && manuscript.invalid &&
      <p role="alert">{t('指定固定稿件版本不可用；不会自动替换为最新版本。')}</p>}
    {(step === 'word' || step === 'manuscripts' && !!receipt.data) && <ProjectManuscripts
      projectId={id} researchTopic={project.research_topic} outputLanguage={outputLanguage} active
      projectType="sci" customerSci={{ settings, wordOnly: step === 'word' }}
      onOpenTask={manuscript.view==='exports'?onOpenWordTask:undefined}
      initialManuscript={manuscript.manuscriptId} initialRevision={manuscript.revision} view={manuscript.view}
      initialWritingRequest={manuscript.writingRequest} initialParagraph={manuscript.paragraph} onNeedSource={onNeedSource}
      onSelectVersion={(id, revision, replace) => onUpdateRoute({ manuscript: id, revision, view: step === 'word' ? 'exports' : 'body' }, true, replace)}
      openLatest={step === 'word' && !params.has('manuscript') && !params.has('revision')}
      onAdopted={(id, revision) => onOpenWord(id, revision, { adopted: true })}
      adoptedNotice={step === 'word' && manuscript.adopted}
      onAutoWordStarted={() => { if (params.has('adopted')) onUpdateRoute({ adopted: undefined }, true, true) }}
      onViewChange={view => onUpdateRoute({ view: step === 'word' && view === 'body' ? 'exports' : view }, true)}
      onStartReview={onStartReview}
      onOpenLiterature={() => onNavigate('citations')} onOpenRequirements={() => onNavigate('details')}
      onOpenMaterials={() => onNavigate('materials')} registerLeaveGuard={registerLeaveGuard} />}
    {step === 'journals' && params.has('adaptation') && !adaptationId &&
      <p role="alert">{t('指定适配记录尚未读取，请刷新；不会代用其他记录。')}</p>}
    {step === 'journals' && receipt.data && <JournalWorkspace projectId={id} active view={journalView}
      initialAdaptation={adaptationId} onSelectAdaptation={adaptation => onUpdateRoute({ adaptation, view: 'adaptation' }, true)}
      onViewChange={view => onUpdateRoute({ view }, true)} customerSci={settings} registerLeaveGuard={registerLeaveGuard} />}
  </section>
}
