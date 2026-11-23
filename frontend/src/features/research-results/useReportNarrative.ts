import {useEffect, useRef, useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError} from '../../shared/i18n'
import {jsonRequest, projectBase, researchRequest, useResearchRead} from './api'
import type {ReportDisclosureFact, ReportDisclosureMaterial, ReportRequest, ReportNarrative, ResearchTask} from './contracts'
import useResearchOperation from './useResearchOperation'

export type NarrativeBinding = {id: string | null; fingerprint: string; binding: string; bundle: string; taskId?: string}
type Preview = {
  bundle_sha256: string
  binding_sha256: string
  model: string
  reserved_micro_usd?: number | null
  fact_count: number
  facts?: ReportDisclosureMaterial
  figures: {number: number; title: string; source_caption?: string; caption_facts?: ReportDisclosureFact[]}[]
  real_calls_enabled: boolean
  cached?: boolean
}
type NarrativeStatus = {
  id: string
  task: ResearchTask
  result: ReportNarrative | null
  artifact_sha256: string | null
  binding_sha256: string
  bundle_sha256: string
  allowed_actions?: string[]
  can_regenerate?: boolean
}

export function useReportNarrative(projectId: string, scope: string, active: boolean, projection: ReportRequest,
  saved: NarrativeBinding | undefined, save: (update: (old: NarrativeBinding | undefined) => NarrativeBinding | undefined) => void) {
  const base = `${projectBase(projectId)}/research-report-narratives`
  const fingerprint = JSON.stringify(projection)
  const matching = saved?.fingerprint === fingerprint ? saved : undefined
  const operation = useResearchOperation<NarrativeStatus>(projectId, 'report_narrative', scope, {
    onResolved: result => save(old => old ? {...old, id: result.id} : old),
  })
  const [previewState, setPreview] = useState<{fingerprint: string; value: Preview} | null>(null)
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<{fingerprint: string; text: string} | null>(null)
  const request = useRef<AbortController | null>(null)
  useEffect(() => {
    function abort() { request.current?.abort(); request.current = null }
    const unsubscribe = onApiSessionChanged(abort)
    return () => { unsubscribe(); abort() }
  }, [])
  const url = matching?.id ? `${base}/${encodeURIComponent(matching.id)}` : ''
  const read = useResearchRead<NarrativeStatus>(url, active, value => ['queued', 'running'].includes(value.task.status))
  const status = read.data && matching && read.data.id === matching.id && read.data.binding_sha256 === matching.binding
    && read.data.bundle_sha256 === matching.bundle && (!matching.taskId || read.data.task?.id === matching.taskId) ? read.data : null
  const ready = status?.task.status === 'succeeded' && status.artifact_sha256 && status.result ? status : null
  const canRegenerate = status?.task.status === 'failed' && status.can_regenerate === true
  const preview = previewState?.fingerprint === fingerprint ? previewState.value : null
  const error = failure?.fingerprint === fingerprint ? failure.text : ''
  const blocking = busy || operation.busy || operation.unknown || !operation.valid

  async function run<T>(url: string, body: unknown, onSuccess: (value: T) => void, fallback: string) {
    if (!active || request.current || operation.unresolved() || !operation.valid) return
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    setFailure(null)
    try {
      const value = await researchRequest<T>(url, {...jsonRequest(body), signal: controller.signal})
      if (!controller.signal.aborted) onSuccess(value)
    } catch (cause) {
      if (!controller.signal.aborted) setFailure({fingerprint, text: safeError(cause, fallback)})
    } finally {
      if (request.current === controller) { request.current = null; setBusy(false) }
    }
  }

  function inspect() {
    if (matching?.id && !canRegenerate) return
    setConsent(false)
    operation.clear()
    return run<Preview>(`${base}/preview`, projection, value => setPreview({fingerprint, value}), '无法读取解读材料与费用，请重试。')
  }

  async function submit() {
    if (!active || !preview || request.current || operation.unresolved() || blocking) return
    if (matching?.id && !canRegenerate) return
    if (!consent || !preview.real_calls_enabled && !preview.cached) return
    save(() => ({id: null, fingerprint, binding: preview.binding_sha256, bundle: preview.bundle_sha256}))
    setPreview(null)
    setConsent(false)
    await operation.submit(base, {report: projection, bundle_sha256: preview.bundle_sha256, confirmed_external_processing: true}, {silent: true})
  }

  async function retry() {
    if (!status?.allowed_actions?.some(action => action === 'retry' || action === 'resume') || !status.task.revision) return
    await run<NarrativeStatus>(`${url}/retry`, {expected_revision: status.task.revision}, read.refresh, '未能确认解读重试状态，请刷新。')
  }

  return {operation, preview, consent, setConsent, inspect, submit, retry, ready, status, read, error, busy, blocking, canRegenerate,
    matching, cancelPreview: () => { setPreview(null); setConsent(false) }}
}
