import { useCallback, useEffect, useRef, useState } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { safeError } from '../../shared/i18n'

type Frozen = { url: string; body: string; key: string }
export default function useLifecycleSubmission<T>(
 send: (request: Frozen, signal: AbortSignal) => Promise<T>,
 success: (value: T) => void, rejected: () => void,
) {
 const frozen = useRef<Frozen | null>(null)
 const controller = useRef<AbortController | null>(null)
 const generation = useRef(0), available = useRef(true)
 const [busy, setBusy] = useState(false), [unknown, setUnknown] = useState(false)
 const [error, setError] = useState(''), [valid, setValid] = useState(true)
 const invalidate = useCallback(() => {
  generation.current++; available.current = false
  controller.current?.abort(); frozen.current = null
  setBusy(false); setUnknown(false); setError(''); setValid(false)
 }, [])
 useEffect(() => {
  available.current = true
  const unsubscribe = onApiSessionChanged(invalidate)
  // Cleanup must abort the latest request, not the null controller at mount.
  // oxlint-disable-next-line react-hooks/exhaustive-deps
  return () => { generation.current++; available.current = false; controller.current?.abort(); unsubscribe() }
 }, [invalidate])
 async function submit(request?: { url: string; body: string }) {
  if (controller.current || !available.current) return
  if (!frozen.current) {
   if (!request) return
   frozen.current = { ...request, key: crypto.randomUUID() }
  }
  const captured = generation.current, c = new AbortController()
  controller.current = c; setBusy(true); setError('')
  const timer = window.setTimeout(() => c.abort(), 15_000)
  try {
   const value = await send(frozen.current, c.signal)
   if (captured !== generation.current) return
   frozen.current = null; setUnknown(false); success(value)
  } catch (cause) {
   if (captured !== generation.current) return
   if (cause instanceof DOMException && cause.name === 'AbortError' && !c.signal.aborted) {
    invalidate(); return
   }
   const status = cause && typeof cause === 'object' && 'status' in cause ? cause.status : null
   if (typeof status === 'number' && status >= 400 && status < 500) {
    frozen.current = null; setUnknown(false)
    setError(safeError(cause, '请求未被接受，请重新读取影响并确认。')); rejected()
   } else {
    setUnknown(true); setError('提交结果尚未确认，请使用同一请求确认结果。')
   }
  } finally {
   window.clearTimeout(timer)
   if (controller.current === c) controller.current = null
   if (captured === generation.current) setBusy(false)
  }
 }
 return { submit, busy, unknown, error, valid, invalidate }
}
