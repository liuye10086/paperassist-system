import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { apiFetch } from '../../shared/api/client'
import { watchProjectAccess } from '../../shared/api/projectAccess'
import { isProject, type Project } from './projectTypes'
import { apiError, safeError } from '../../shared/i18n'

type Instance = { id: string; key: number }
type Request = { controller: AbortController; timeout: number }

export default function useProjectSelection(onUnavailable: (id: string) => void, onAvailable: (id: string) => void) {
  const nextKey = useRef(1)
  const [instance, setInstance] = useState<Instance | null>(() => {
    const id = new URLSearchParams(window.location.hash.slice(1)).get('project')
    return id ? { id, key: 1 } : null
  })
  const [detail, setDetail] = useState<{ instance: Instance; project: Project } | null>(null)
  const [failure, setFailure] = useState<{ instance: Instance; message: string } | null>(null)
  const [unavailableId, setUnavailableId] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(Boolean(instance))
  const current = useRef<Instance | null>(null)
  const callbacks = useRef({ onUnavailable, onAvailable })
  const request = useRef<Request | null>(null)
  const sequence = useRef(0)

  function cancel() {
    sequence.current++
    if (request.current) {
      request.current.controller.abort()
      window.clearTimeout(request.current.timeout)
      request.current = null
    }
  }

  useLayoutEffect(() => { callbacks.current = { onUnavailable, onAvailable } })
  // The parent registers this instance before detail or child passive effects issue requests.
  useLayoutEffect(() => {
    current.current = instance
    if (!instance) return
    const stop = watchProjectAccess(instance.id, () => {
      if (current.current !== instance) return
      cancel()
      current.current = null
      setInstance(null)
      setDetail(null)
      setFailure(null)
      setLoading(false)
      setUnavailableId(instance.id)
      callbacks.current.onUnavailable(instance.id)
    })
    return () => { stop(); cancel(); if (current.current === instance) current.current = null }
  }, [instance])

  useLayoutEffect(() => {
    window.history.replaceState(null, '', window.location.pathname + window.location.search
      + (instance ? `#project=${encodeURIComponent(instance.id)}` : ''))
  }, [instance])

  useEffect(() => {
    if (!instance) return
    const controller = new AbortController()
    const id = ++sequence.current
    const isCurrent = () => current.current === instance && sequence.current === id && !controller.signal.aborted
    const timeout = window.setTimeout(() => {
      if (!isCurrent()) return
      controller.abort()
      setFailure({ instance, message: '项目详情读取超时，请稍后重试。' })
      setLoading(false)
    }, 15_000)
    request.current = { controller, timeout }
    async function load() {
      try {
        const response = await apiFetch(`/api/v1/projects/${encodeURIComponent(instance!.id)}`, { signal: controller.signal })
        const result: unknown = await response.json()
        if (!isCurrent()) return
        if (!response.ok) throw new Error(apiError(result, '项目详情读取失败，请稍后重试。'))
        if (!isProject(result) || result.id !== instance!.id) throw new Error('项目详情格式不正确，请重试。')
        setDetail({ instance: instance!, project: result })
        callbacks.current.onAvailable(instance!.id)
      } catch (cause) {
        if (isCurrent()) setFailure({ instance: instance!, message: cause instanceof TypeError
          ? '无法连接后端，请稍后重试项目详情。' : safeError(cause, '项目详情读取失败。') })
      } finally {
        window.clearTimeout(timeout)
        if (isCurrent()) setLoading(false)
        if (request.current?.controller === controller) request.current = null
      }
    }
    void load()
    return () => { controller.abort(); window.clearTimeout(timeout) }
  }, [instance, attempt])

  function refresh() {
    cancel()
    setFailure(null)
    setLoading(true)
    setAttempt(value => value + 1)
  }

  function open(id: string, seed?: Project) {
    setUnavailableId('')
    if (instance?.id === id && current.current === instance) { refresh(); return }
    cancel()
    const next = { id, key: ++nextKey.current }
    setInstance(next)
    setDetail(seed ? { instance: next, project: seed } : null)
    setFailure(null)
    setLoading(true)
  }

  function update(project: Project) {
    if (!instance || current.current !== instance || project.id !== instance.id) return
    cancel()
    setDetail({ instance, project })
    setFailure(null)
    setLoading(false)
  }

  function close() {
    cancel()
    setInstance(null)
    setDetail(null)
    setFailure(null)
    setUnavailableId('')
    setLoading(false)
  }

  return { instance, project: detail?.instance === instance ? detail.project : null,
    error: failure?.instance === instance ? failure.message : '', loading, unavailableId, open, refresh, update, close }
}
