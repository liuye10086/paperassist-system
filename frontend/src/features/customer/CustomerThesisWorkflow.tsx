import { useEffect, useState, type Ref } from 'react'
import { useI18n } from '../../shared/i18n'
import ProjectManuscripts from '../manuscripts/ProjectManuscripts'
import type { NeedSource } from '../manuscripts/WritingLive'
import { schoolTemplateViews, type SchoolTemplateNavigation } from '../projects/manuscriptViews'
import type { Project } from '../projects/projectTypes'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { projectBase, useResearchRead } from '../research-results/api'
import SchoolTemplates from '../school-templates/SchoolTemplates'
import CustomerWritingMaterials from './CustomerWritingMaterials'
import { customerManuscriptNavigation, type UpdatePaperRoute } from './customerPaperNavigation'
import { validCustomerRouteId } from './customerReviewNavigation'
import ReturnBar from './ReturnBar'
import { readReturn } from './returnToken'
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
  /** The Word page of one fixed version; `adopted` says it was opened by adopting it (B03, B04 task 7). */
  onOpenWord?: (manuscriptId: string, revision: number, options?: { adopted?: boolean }) => void
  onOpenWordTask?: (taskId: string) => void
  /** A review paragraph lacks a source: open literature or materials with a token back to it (B03 task 7). */
  onNeedSource?: NeedSource
  /** `confirmed`: the page already saved what it was for (an adopted template), so it leaves without a prompt. */
  onFollowReturn?: (href: string, confirmed?: boolean) => void
  /** A chapter lacks a school template: open the template page with a token back to it (B04 task 8). */
  onOpenTemplateWithReturn?: (place: { chapter?: string; title: string }) => void
  /** The migration page of one version with the new template preselected (B04 task 9, D6). */
  onOpenMigration?: (manuscriptId: string, revision: number, confirmationId: string) => void
  /** Writing materials take a published analysis result (B05 task 6, wireframe 18). */
  onOpenAnalysisResults?: () => void
}
const titles: Record<Step, string> = {
  school: '学校模板', materials: '写作资料与引用', citations: '写作资料与引用',
  manuscripts: '章节与复核', word: '固定版本与 Word',
}

export default function CustomerThesisWorkflow({
  project, step, headingRef, registerLeaveGuard, onUnavailable, onNavigate, params, onUpdateRoute, onStartReview,
  onOpenWord, onOpenWordTask, onNeedSource, onFollowReturn, onOpenTemplateWithReturn, onOpenMigration, onOpenAnalysisResults,
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
  // Adding a source for a review paragraph (as in CustomerSciWorkflow): the page shows where it returns to, and
  // returns by itself once the reference is ready or a file is uploaded.
  const paragraphReturn = materialsStep && params.get('returnLabel') === 'paragraph' ? readReturn(params, project.id) : null
  const materialsReturn = materialsStep && params.get('returnLabel') === 'materials' ? readReturn(params, project.id) : null
  // A manuscript opened from a review opinion or round (B05 task 7).
  const reviewReturn = step === 'manuscripts' && ['review-item', 'review-round'].includes(params.get('returnLabel') ?? '')
    ? readReturn(params, project.id) : null
  const [finished, setFinished] = useState(false)
  const finish = paragraphReturn && onFollowReturn ? () => setFinished(true) : undefined
  // oxlint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (finished && paragraphReturn) onFollowReturn?.(paragraphReturn.href) }, [finished])
  // Adopting a template for a chapter (wireframe 13b): the page shows where it returns to, and returns by itself
  // once the template is adopted. Without a token the template page stays on its success notice.
  const chapterReturn = step === 'school' && params.get('returnLabel') === 'chapter' ? readReturn(params, project.id) : null
  // “迁移到新模板” reports the adoption and then opens the migration in the same turn. The return is followed one
  // render later, so the migration wins: it leaves this step, which remounts the workflow and drops the token.
  const [adoptedForChapter, setAdoptedForChapter] = useState(false)
  // oxlint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (adoptedForChapter && chapterReturn) onFollowReturn?.(chapterReturn.href, true) }, [adoptedForChapter])

  return <section className="customer-section customer-manuscript-workflow">
    <div className="customer-section-heading">
      <h1 ref={headingRef} tabIndex={-1}>{t(titles[step])}</h1>
      {step === 'school' && <div className="sci-inline-controls">
        <button type="button" className="button-quiet" onClick={() => onNavigate('details')}>{t('查看毕业论文需求')}</button>
        <button type="button" className="button-quiet" onClick={() => onNavigate('materials')}>{t('下一步 写作资料与引用')}</button>
      </div>}
      {step === 'manuscripts' && <button type="button" className="button-quiet"
        onClick={() => manuscript.manuscriptId && manuscript.revision && onOpenWord
          ? onOpenWord(manuscript.manuscriptId, manuscript.revision) : onNavigate('word')}>{t('查看固定版本 Word')}</button>}
    </div>
    {paragraphReturn && <ReturnBar target={paragraphReturn} onReturn={onFollowReturn}>
      {t('正在为“{place}”补充依据', { place: paragraphReturn.label })}
    </ReturnBar>}
    {reviewReturn && <ReturnBar target={reviewReturn} onReturn={onFollowReturn}>
      {t('正在查看“{place}”所用的稿件', { place: reviewReturn.label })}
    </ReturnBar>}
    {finished && paragraphReturn && <p role="status">{t('完成并返回 {place}', { place: paragraphReturn.label })}</p>}
    {chapterReturn && <ReturnBar target={chapterReturn} onReturn={onFollowReturn}>
      {t('正在为“{place}”采用学校模板', { place: chapterReturn.label })}
    </ReturnBar>}
    {step === 'school' && params.has('template') && !templateId && <p role="alert">{t('指定学校模板版本不可用。')}</p>}
    {step === 'school' && <SchoolTemplates projectId={project.id} active customerView navigation={schoolView}
      onNavigate={({ view, templateId }) => onUpdateRoute({ view, template: templateId }, true)} registerLeaveGuard={registerLeaveGuard}
      returnPlace={chapterReturn?.label}
      onAdopted={chapterReturn && onFollowReturn ? () => setAdoptedForChapter(true) : undefined}
      onContinue={chapterReturn ? undefined : () => onNavigate('materials')} onOpenMigration={onOpenMigration} />}
    {materialsStep && <CustomerWritingMaterials project={project}
      startWithCitations={step === 'citations'} onContinue={() => onNavigate('manuscripts')} onRequirements={() => onNavigate('details')}
      projectKeywords={requirements.data?.keywords} literatureReady={!!(requirements.data || requirements.error)}
      params={params} onUpdateRoute={onUpdateRoute} onReferenceReady={finish} onUploaded={finish}
      onOpenAnalysisResults={onOpenAnalysisResults} materialsReturn={materialsReturn} onFollowReturn={onFollowReturn}
      onUnavailable={onUnavailable} registerLeaveGuard={registerLeaveGuard} />}
    {(step === 'manuscripts' || wordOnly) && manuscript.invalid &&
      <p role="alert">{t('指定固定稿件版本不可用；不会自动替换为最新版本。')}</p>}
    {(step === 'manuscripts' || wordOnly) && <ProjectManuscripts projectId={project.id}
      researchTopic={project.research_topic} outputLanguage={project.default_output_language ?? 'zh-CN'}
      active projectType="thesis" customerThesis={{ wordOnly }} view={manuscript.view}
      initialManuscript={manuscript.manuscriptId} initialRevision={manuscript.revision}
      initialWritingRequest={manuscript.writingRequest} initialParagraph={manuscript.paragraph} onNeedSource={onNeedSource}
      onSelectVersion={(id, revision, replace) => onUpdateRoute({ manuscript: id, revision, view: wordOnly ? 'exports' : 'body' }, true, replace)}
      openLatest={wordOnly && !params.has('manuscript') && !params.has('revision')}
      onAdopted={onOpenWord ? (id, revision) => onOpenWord(id, revision, { adopted: true }) : undefined}
      adoptedNotice={wordOnly && manuscript.adopted}
      onAutoWordStarted={() => { if (params.has('adopted')) onUpdateRoute({ adopted: undefined }, true, true) }}
      onViewChange={view => onUpdateRoute({ view: wordOnly && view === 'body' ? 'exports' : view }, true)}
      onStartReview={onStartReview}
      initialChapter={manuscript.chapter} initialTarget={manuscript.target} onChapterFocused={() => onUpdateRoute({ chapter: undefined, focus: undefined }, true, true)}
      onOpenLiterature={() => onNavigate('citations')}
      onOpenSchoolTemplate={chapter => onOpenTemplateWithReturn
        ? onOpenTemplateWithReturn({ chapter: chapter?.id, title: chapter?.title ?? t('章节与复核') }) : onNavigate('school')}
      onOpenRequirements={() => onNavigate('details')} onOpenMaterials={() => onNavigate('materials')}
      onOpenMigration={onOpenMigration}
      onOpenTask={manuscript.view==='exports'?onOpenWordTask:undefined}
      registerLeaveGuard={registerLeaveGuard} />}
  </section>
}
