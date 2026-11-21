import { useCallback, useEffect, useRef, useState } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { captureProjectAccess } from '../../shared/api/projectAccess'
import { safeError } from '../../shared/i18n'
import { intakeRequest, jsonRequest, projectBase } from '../research-intake/api'

export const analystStatuses = {
  draft: '尚未提交需求', assigned: '已分配', analyzing: '分析中', needs_materials: '待补材料',
  materials_submitted: '已补交，等待核对', delivered: '已交付',
} as const
export type ProgressStatus = 'analyzing' | 'needs_materials'
export type SubmittedVersion = { id: string; version: number }
export type AnalystFeedback = { id: string; message: string; created_at: string }
export type AnalystPublication = { id: string; title: string; published_at: string; feedback: AnalystFeedback[] }
export type AnalystSubmission = {
  id: string
  requirement_version: number
  file_ids: string[]
  files: { id: string; name: string }[]
  note: string | null
  created_at: string
}
type AnalystData = {
  assignment_revision: number
  requirement: SubmittedVersion | null
  status: keyof typeof analystStatuses
  note: string | null
  feedback: AnalystFeedback[]
  publications: AnalystPublication[]
  // Customer resubmissions for the current requirement, newest first.
  submissions: AnalystSubmission[]
}
type Mutation = { kind: 'progress'; requirement: string; status: ProgressStatus; note: string }
  | { kind: 'publish'; snapshot: string; title: string }

function isFeedback(items: unknown): items is AnalystFeedback[] {
  return Array.isArray(items) && items.every(item => item && typeof item.id === 'string'
    && typeof item.message === 'string' && typeof item.created_at === 'string')
}

function isSubmissions(items: unknown): items is AnalystSubmission[] {
  return Array.isArray(items) && items.every(item => item && typeof item.id === 'string' && Number.isSafeInteger(item.requirement_version)
    && Array.isArray(item.file_ids) && item.file_ids.every((id: unknown) => typeof id === 'string')
    && Array.isArray(item.files) && item.files.every((file: unknown) => !!file && typeof (file as { id: unknown }).id === 'string'
      && typeof (file as { name: unknown }).name === 'string')
    && (item.note === null || typeof item.note === 'string') && typeof item.created_at === 'string')
}

function isAnalystData(data: AnalystData | null): data is AnalystData {
  return !!data && Number.isSafeInteger(data.assignment_revision) && data.assignment_revision > 0
    && (data.requirement === null || !!data.requirement && typeof data.requirement.id === 'string' && Number.isSafeInteger(data.requirement.version))
    && Object.hasOwn(analystStatuses, data.status) && (data.note === null || typeof data.note === 'string') && isFeedback(data.feedback)
    && Array.isArray(data.publications) && data.publications.every(item => item && typeof item.id === 'string' && typeof item.title === 'string'
      && typeof item.published_at === 'string' && isFeedback(item.feedback))
    && (data.submissions === undefined || isSubmissions(data.submissions))
}

type RequestState = { key: string; value: AnalystData | null; busy: boolean; error: string; notice: string }

export default function useAnalystWorkspace(projectId: string, revision: number | undefined) {
  const url = projectId && revision !== undefined ? `${projectBase(projectId)}/analyst-workspace` : ''
  const key = `${url}:${revision}`
  const [state, setState] = useState<RequestState | null>(null)
  // Snapshots whose publish request succeeded; the confirmation must not depend on the follow-up read.
  const [published, setPublished] = useState<{ key: string; ids: string[] }>({ key: '', ids: [] })
  const request = useRef<AbortController | null>(null)
  const run = useCallback(async (mutation?: Mutation) => {
    if (!url || request.current) return
    const controller = new AbortController()
    const signal = controller.signal
    request.current = controller
    setState(previous => ({ key, value: previous?.key === key ? previous.value : null, busy: true, error: '', notice: '' }))
    let mutationError = ''
    let notice = ''
    try {
      if (mutation) {
        const progress = mutation.kind === 'progress'
        const body = progress
          ? { assignment_revision: revision, requirement_version_id: mutation.requirement, status: mutation.status, note: mutation.note.trim() || null }
          : { assignment_revision: revision, snapshot_id: mutation.snapshot, title: mutation.title.trim() }
        try {
          await intakeRequest(`${url}/${mutation.kind}`, { ...jsonRequest(body), method: progress ? 'PATCH' : 'POST', signal })
          notice = progress ? '进度已保存。' : '交付已发布。'
          if (!progress) {
            const snapshot = mutation.snapshot
            setPublished(previous => ({ key, ids: [...previous.key === key ? previous.ids : [], snapshot] }))
          }
        } catch (cause) {
          mutationError = safeError(cause, progress ? '进度保存失败，请重新核对。' : '发布失败，请重新核对。')
        }
      }
      if (signal.aborted) return
      const access = captureProjectAccess(url)
      const value = await intakeRequest<AnalystData>(url, { signal })
      access.check()
      if (signal.aborted) return
      if (!isAnalystData(value)) throw new Error('处理进度响应格式不正确。')
      if (value.assignment_revision !== revision) {
        access.unavailable()
        return
      }
      setState({ key, value: { ...value, submissions: value.submissions ?? [] }, busy: false, error: mutationError, notice })
    } catch (cause) {
      if (!signal.aborted) setState({ key, value: null, busy: false, error: safeError(cause, '无法读取进度与反馈，请重试。'), notice })
    } finally {
      if (request.current === controller) request.current = null
    }
  }, [key, revision, url])

  useEffect(() => {
    void run()
    return () => { request.current?.abort(); request.current = null }
  }, [run])
  useEffect(() => onApiSessionChanged(() => {
    request.current?.abort()
    setState(null)
    setPublished({ key: '', ids: [] })
  }), [])

  const current = state?.key === key ? state : null
  return {
    value: current?.value ?? null, busy: current?.busy ?? !!url, error: current?.error ?? '', notice: current?.notice ?? '',
    published: published.key === key ? published.ids : [],
    assignmentRevision: url ? revision : undefined,
    refresh: () => { void run() },
    saveProgress: (requirement: string, status: ProgressStatus, note: string) => { void run({ kind: 'progress', requirement, status, note }) },
    publish: (snapshot: string, title: string) => { void run({ kind: 'publish', snapshot, title }) },
  }
}

export type AnalystWorkspace = ReturnType<typeof useAnalystWorkspace>
