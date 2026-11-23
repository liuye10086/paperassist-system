import {captureApiSession} from '../../shared/api/client'
import {STANDARD_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
import {jsonRequest} from '../research-intake/api'
import {taskRequest, TaskRequestError} from '../tasks/taskApi'
import {isTask, isWorkspace, sameInputVersion, type TaskView, type TaskWorkspace} from '../tasks/taskTypes'
import type {SelectedReference} from './ManuscriptReferencePicker'
import {manuscriptBase, validManuscript, type Manuscript, type ManuscriptInput, type SourceCandidate} from './manuscriptTypes'

const filePriority: Record<string, number> = {original: 1, document_version: 2, ocr_review_version: 3}
export type DraftReference = Omit<SelectedReference, 'quote'> & {quote?: string}

export function defaultPaperFiles(items: SourceCandidate[], excluded: ReadonlySet<string>) {
  const byFile = new Map<string, SourceCandidate>()
  for (const item of items) {
    const priority = filePriority[item.kind]
    if (!priority || excluded.has(item.file_id) || !item.allowed_roles.length) continue
    const previous = byFile.get(item.file_id)
    if (!previous || priority > filePriority[previous.kind] ||
      (priority === filePriority[previous.kind] && (item.version ?? 0) > (previous.version ?? 0))) byFile.set(item.file_id, item)
  }
  return [...byFile.values()]
}

function waitForPublication(signal: AbortSignal) {
  signal.throwIfAborted()
  return new Promise<void>((resolve, reject) => {
    function abort() { window.clearTimeout(timer); reject(signal.reason) }
    const timer = window.setTimeout(() => {signal.removeEventListener('abort', abort); resolve()}, 2000)
    signal.addEventListener('abort', abort, {once: true})
  })
}

function validCitation(value: unknown): value is NonNullable<ManuscriptInput['citation_draft']> {
  return !!value && typeof value === 'object' && 'id' in value && typeof value.id === 'string' &&
    /^[A-Za-z0-9_-]{1,64}$/.test(value.id) && 'revision' in value && Number.isSafeInteger(value.revision) && Number(value.revision) > 0
}

export async function preparePaperDraft({projectId, manuscriptId, input, references, attemptKey, signal, existingRevision}: {
  projectId: string; manuscriptId?: string; input: ManuscriptInput; references: DraftReference[]; attemptKey: string; signal: AbortSignal
  existingRevision?: number
}) {
  signal.throwIfAborted()
  const checkSession = captureApiSession()
  const controller = new AbortController()
  const abort = () => controller.abort()
  signal.addEventListener('abort', abort, {once: true})
  const base = manuscriptBase(projectId)
  const readError = '写作材料保存结果未确认，请刷新后重试。'
  const revision = existingRevision ?? input.expected_revision + 1
  const isRoot = (v: unknown): v is Manuscript => validManuscript(v, projectId) && (!manuscriptId || v.id === manuscriptId)
  try {
    let root: Manuscript
    let mayResume = existingRevision !== undefined
    if (mayResume) {
      if (!manuscriptId) throw new TaskRequestError('这份稿件已有更新。请重新读取稿件资料。', 409)
      root = await taskRequest(base + '/' + encodeURIComponent(manuscriptId), controller, isRoot, readError)
    } else {
      const citation = references.length ? await taskRequest(base + '/selected-references', controller, validCitation, '文献摘录保存失败，请重试。',
        jsonRequest({references, output_language: input.output_language}, attemptKey + '-refs')) : input.citation_draft
      checkSession()
      signal.throwIfAborted()
      root = await taskRequest(manuscriptId ? base + '/' + encodeURIComponent(manuscriptId) + '/versions' : base, controller, isRoot, readError,
        jsonRequest({...input, citation_draft: citation}, attemptKey + '-materials'))
    }
    const rootId = root.id
    const end = Date.now() + STANDARD_REQUEST_TIMEOUT_MS
    while (true) {
      checkSession()
      signal.throwIfAborted()
      const version = root.versions.find(v => v.revision === revision)
      if (root.current_revision !== revision || !version) throw new TaskRequestError('这份稿件已有更新。请重新读取稿件资料。', 409)
      if (version.status === 'published') return {manuscriptId: root.id, version, root}
      if (version.status === 'failed') {
        if (!mayResume) throw new TaskRequestError('写作材料整理失败，请核对项目资料后重试。', 422)
        mayResume = false
        const url = '/api/v1/tasks/' + encodeURIComponent(version.task_id)
        const workspace = await taskRequest(url + '/workspace', controller, (v): v is TaskWorkspace =>
          isWorkspace(v, projectId, version.task_id) && v.task.task_type === 'manuscript_draft' &&
          v.task.input_version.kind === 'manuscript' && v.task.input_version.manuscript_version_id === version.id, readError)
        if (workspace.task.status === 'failed') {
          if (!workspace.allowed_actions.includes('retry') || version.current_changes.length) {
            throw new TaskRequestError('当前资料已变更，请使用当前资料生成。', 409)
          }
          const task = workspace.task
          await taskRequest(url + '/resume', controller, (v): v is TaskView => isTask(v, projectId, task.id) &&
            v.task_type === 'manuscript_draft' && sameInputVersion(v.input_version, task.input_version), readError,
            jsonRequest({operation:'retry', wait_id:null, expected_task_revision:task.revision, input_version:task.input_version},
              attemptKey + '-resume-' + task.revision))
        }
      }
      if (Date.now() >= end) throw new Error('写作材料仍在整理，可以稍后继续。')
      await waitForPublication(signal)
      root = await taskRequest(base + '/' + encodeURIComponent(rootId), controller, (v): v is Manuscript => isRoot(v) && v.id === rootId, readError)
    }
  } finally {signal.removeEventListener('abort', abort)}
}
