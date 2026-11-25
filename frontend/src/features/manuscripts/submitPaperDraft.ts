import {captureApiSession} from '../../shared/api/client'
import {safeError} from '../../shared/i18n'
import type {SciSettings} from '../customer/sciProjectSettings'
import {jsonRequest} from '../research-intake/api'
import {taskRequest, TaskRequestError} from '../tasks/taskApi'
import {isNativeReviewFigure, manuscriptBase, type ManuscriptVersion, type Snapshot} from './manuscriptTypes'
import {authorizationsUrl, intactBundle, materialsChanged} from './useCustomerWritingSubmit'
import {
  canonicalJson, frozenWritingEvidence, jsonDigest, listOf, object, requestUsesGroup,
  validAuthorization, validBundle, validCapabilities, validLiveRequest, writableSchoolPurpose,
  type Authorization, type Bundle, type LiveRequest, type PreviewInput, type WritingCapabilities,
} from './writingLiveTypes'

type DraftAttempt = {projectId: string; manuscriptId: string; attemptKey: string; signal: AbortSignal}
type DraftSubmission = DraftAttempt & {version: ManuscriptVersion; documentKind?: 'sci' | 'thesis'; sciSettings?: Pick<SciSettings, 'article_type' | 'keywords'> | null}

const unknownResult = '暂时无法确定这次提交是否成功。请先查看提交结果。'

class DraftNotSubmitted extends Error {}
class RejectedDraftRequest extends TaskRequestError {}

export function isPaperDraftRejected(error: unknown) {
  return error instanceof DraftNotSubmitted || error instanceof RejectedDraftRequest
}

// The article protocol accepts a review's own planned illustrations but excludes original study results.
function reviewSources(snapshot: Snapshot) {
  const plan = snapshot.paper_plan
  const sections = new Set(plan?.sections.map(section => section.id))
  const illustrations = new Map(plan?.materials.filter(item => sections.has(item.section_id) ||
    isNativeReviewFigure(item.section_id, item.kind, item.selection))
    .map(item => [item.selection.id, item]))
  return snapshot.sources.filter(source => {
    if (!(source.kind === 'analysis_run' || ['computed_results', 'user_results', 'image_observation'].includes(source.role))) return true
    const item = illustrations.get(source.id)
    return plan?.kind === 'narrative_review' && source.kind === 'original' && item?.selection.kind === source.kind &&
      item.selection.file_id === source.file_id && item.selection.role === source.role &&
      source.role === (item.kind === 'figure' ? 'image_observation' : 'user_results')
  })
}

function draftInput({version, sciSettings, documentKind}: DraftSubmission): PreviewInput {
  const {snapshot} = version
  if ((documentKind === 'thesis' || version.input.thesis || snapshot.paper_plan?.kind === 'thesis') && !snapshot.thesis_context) {
    throw new DraftNotSubmitted('当前稿件缺少学校目录，请重新确认目录后生成。')
  }
  const common = {
    base_revision: version.revision, mode: 'full_draft' as const, document_context_version: 'selected-text-v1' as const,
    target_section: null, output_language: snapshot.output_language,
    keywords: [] as string[], instructions: '', acknowledgements: '', selected_source_ids: [...new Set(snapshot.sources.map(s => s.id))],
    selected_evidence_ids: frozenWritingEvidence(snapshot).map(e => e.id),
  }
  if (snapshot.thesis_context) {
    if (!snapshot.thesis_context.confirmation_id || !snapshot.thesis_context.chapters.some(c => writableSchoolPurpose(c.purpose))) {
      throw new DraftNotSubmitted('当前预览的基础版本不可用。')
    }
    return {...common, schema_version: 3}
  }
  const articleType = snapshot.article_type ?? snapshot.paper_plan?.kind ?? sciSettings?.article_type ?? 'research'
  if (articleType !== 'research' && articleType !== 'narrative_review') throw new DraftNotSubmitted('当前预览的基础版本不可用。')
  return {...common, schema_version: 4, document_kind: 'sci', article_type: articleType,
    keywords: snapshot.keywords ?? snapshot.paper_plan?.keywords ?? sciSettings?.keywords ?? [],
    selected_source_ids: articleType === 'narrative_review' ? [...new Set(reviewSources(snapshot).map(s => s.id))] : common.selected_source_ids,
    target_sections: [], target_paragraph_ids: [], paragraph_plan: [], brief_limits: null, validation_source_ids: [],
  }
}

async function writingAttempt({projectId, manuscriptId, attemptKey, signal}: DraftAttempt) {
  signal.throwIfAborted()
  if (!attemptKey.trim()) throw new DraftNotSubmitted('请求标识无效。')
  const checkSession = captureApiSession()
  const base = manuscriptBase(projectId) + '/' + encodeURIComponent(manuscriptId)
  // The server exposes the logical task ID even before the worker records a model call.
  const logical = await jsonDigest(['paper-draft', projectId, manuscriptId, attemptKey])
  const requestUrl = base + '/writing-requests'
  const previewUrl = base + '/writing-previews'
  const live = (v: unknown): v is LiveRequest => validLiveRequest(v, projectId, manuscriptId)
  async function request<T>(url: string, valid: (v: unknown) => v is T, init?: RequestInit) {
    signal.throwIfAborted()
    checkSession()
    const controller = new AbortController()
    const abort = () => controller.abort()
    signal.addEventListener('abort', abort, {once: true})
    try {
      return await taskRequest(url, controller, valid, unknownResult, init)
    } catch (error) {
      signal.throwIfAborted()
      if (error instanceof TaskRequestError && url !== requestUrl && error.status >= 400 && error.status < 500 &&
          error.status !== 408 && error.code !== 'task_idempotency_conflict') {
        throw new RejectedDraftRequest(error.message, error.status, error.code)
      }
      if (error instanceof TaskRequestError) throw error
      throw new Error(safeError(error, unknownResult))
    } finally {
      signal.removeEventListener('abort', abort)
    }
  }
  async function find() {
    type Historical = {schema_version?: 1}
    const list = await request(requestUrl, listOf((v): v is LiveRequest | Historical =>
      live(v) || object(v) && (v.schema_version === 1 || v.schema_version === undefined)))
    return list.items.find((v): v is LiveRequest => v.schema_version === 2 &&
      (v.execution?.logical_task_id === logical || v.model_calls.some(call => call.logical_task_id === logical))) ?? null
  }
  async function getCapabilities(only = false) {
    const result = await request(previewUrl + (only ? '?capabilities_only=true' : ''),
      (v): v is {capabilities: WritingCapabilities} => object(v) && validCapabilities(v.capabilities))
    return result.capabilities
  }
  return {logical, requestUrl, previewUrl, live, request, find, getCapabilities}
}

/** Reads this attempt's receipt without confirming or submitting anything. */
export async function findPaperDraft(attempt: DraftAttempt): Promise<LiveRequest | null> {
  return (await writingAttempt(attempt)).find()
}

/** Called only after the user confirms external transmission and the writing charge. */
export async function submitPaperDraft(submission: DraftSubmission): Promise<LiveRequest> {
  const {projectId, version} = submission
  const attempt = await writingAttempt(submission)
  const previous = await attempt.find()
  if (previous) return previous
  if (version.snapshot.project_id !== projectId || version.status !== 'published') {
    throw new DraftNotSubmitted('当前预览的基础版本不可用。')
  }
  return submitPreparedInput(submission, attempt, version.id, draftInput(submission))
}

export function matchesDraftRevisionScope(input: PreviewInput, sectionIds?: string[], advice = false) {
  return Boolean(input.draft_advice) === advice && canonicalJson(input.target_sections ?? []) === canonicalJson(sectionIds ?? [])
}

export async function submitPaperDraftRevision(submission: DraftAttempt & {
  requestId: string; revision: number; feedback: string; targetSections?: string[]; advice?: boolean; newAttempt?: boolean
}) {
  const attempt = await writingAttempt(submission)
  const targetSections = submission.targetSections ?? []
  const scoped = targetSections.length > 0
  // Only the first send with a newly generated key can skip recovering an existing receipt.
  const previous = scoped && submission.newAttempt ? null : await attempt.find()
  if (previous) {
    if (previous.input.revision_of_request_id !== submission.requestId || previous.input.instructions !== submission.feedback ||
        !matchesDraftRevisionScope(previous.input, submission.targetSections, submission.advice)) {
      throw new Error(unknownResult)
    }
    return previous
  }
  const [original, capabilities] = await Promise.all([
    attempt.request(attempt.requestUrl + '/' + encodeURIComponent(submission.requestId), attempt.live),
    scoped ? attempt.getCapabilities(true) : undefined,
  ])
  const version = original.task.input_version
  const kind = original.candidate?.article_type ?? original.input.article_type ?? 'research'
  const school = !!original.candidate?.thesis_context
  if (original.id !== submission.requestId || original.base_revision !== submission.revision ||
      original.task.status !== 'succeeded' || !original.candidate ||
      original.published_revision !== null || original.input.mode !== 'full_draft' || version.kind !== 'manuscript_writing' ||
      (school ? original.input.schema_version !== 3 : !['research', 'narrative_review'].includes(kind)) ||
      !submission.feedback.trim() || submission.feedback.length > 10000) {
    throw new DraftNotSubmitted(school ? '请选择已生成的毕业论文初稿并填写修改要求。' : '请选择已生成的 SCI 正文并填写审稿意见。')
  }
  const {target_sections: _priorSections, draft_advice: _priorAdvice, ...parentInput} = original.input
  const revisionInput: PreviewInput = {...parentInput, revision_of_request_id: original.id, instructions: submission.feedback,
    ...(submission.advice ? {draft_advice:true} : {})}
  const input: PreviewInput = school ? {...revisionInput, ...(scoped ? {target_sections:targetSections} : {})}
    : {...revisionInput, schema_version: 4, document_kind: 'sci', article_type: kind,
      mode: 'full_draft', target_section: null, target_sections: targetSections, target_paragraph_ids: [], paragraph_plan: [],
      brief_limits: null, validation_source_ids: []}
  return submitPreparedInput(submission, attempt, version.base_version_id, input, capabilities)
}

async function submitPreparedInput({projectId, manuscriptId}: DraftAttempt, attempt: Awaited<ReturnType<typeof writingAttempt>>,
  baseVersionId: string, input: PreviewInput, capabilities?: WritingCapabilities) {
  const {logical, requestUrl, previewUrl, live, request} = attempt
  const available = capabilities ?? await attempt.getCapabilities()
  if (!available.real_calls_enabled) throw new DraftNotSubmitted('写作服务暂未开启，暂时不能生成正文。')
  const bundle = await request(previewUrl, (v): v is Bundle => validBundle(v, projectId, manuscriptId),
    jsonRequest(input, logical + '-preview'))
  if (bundle.base_version_id !== baseVersionId || canonicalJson(bundle.request_json) !== canonicalJson(input) || !await intactBundle(bundle)) {
    throw new DraftNotSubmitted(materialsChanged)
  }
  const ref = {bundle_id: bundle.id, bundle_sha256: bundle.bundle_sha256}
  const tasks = [{logical_task_id: logical, bundles: [ref]}]
  const auth = await request(authorizationsUrl(projectId), (v): v is Authorization => validAuthorization(v, projectId),
    jsonRequest({schema_version: 2, confirmed: true, tasks}, logical + '-authorize'))
  if (auth.occupied_posts > 0) throw new Error(unknownResult)
  if (auth.status !== 'active' || canonicalJson(auth.manifest.tasks) !== canonicalJson(tasks)) {
    throw new DraftNotSubmitted(materialsChanged)
  }
  const execution = {authorization_id: auth.id, logical_task_id: logical, ...ref}
  const result = await request(requestUrl, live, jsonRequest({schema_version: 2, ...execution}, logical + '-write'))
  if (result.task.input_version.kind !== 'manuscript_writing' || result.task.input_version.base_version_id !== baseVersionId ||
      canonicalJson(result.input) !== canonicalJson(input) || !requestUsesGroup(result, execution)) throw new Error(unknownResult)
  return result
}
