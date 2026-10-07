import { useI18n, apiError, safeError } from '../i18n'
import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from 'react'
import { apiFetch, captureApiSession, onApiSessionChanged } from '../api/client'
import { captureProjectAccess } from '../api/projectAccess'
type Props = { href: string; filename: string; children: ReactNode; ariaLabel?: string }
export default function ProjectDownloadLink(props: Props) {
  return <DownloadLink key={props.href} {...props} />
}

function DownloadLink({ href, filename, children, ariaLabel }: Props) {
  const { t } = useI18n()
  const [checkSession] = useState(captureApiSession)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const active = useRef(true)
  const request = useRef<AbortController | null>(null)
  useEffect(() => {
    active.current = true
    const unsubscribe = onApiSessionChanged(() => { request.current?.abort(); setBusy(false) })
    return () => { active.current = false; request.current?.abort(); unsubscribe() }
  }, [])

  async function download(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    if (request.current) return
    const scope = captureProjectAccess(href)
    try { checkSession(); scope.check() } catch { return }
    const controller = new AbortController()
    request.current = controller; setBusy(true); setError('')
    let timer = 0
    const check = () => {
      checkSession(); scope.check()
      if (!active.current || controller.signal.aborted) throw new DOMException('下载已取消', 'AbortError')
    }
    try {
      const blob = await Promise.race([
        apiFetch(href, { signal: controller.signal }).then(async response => {
          if (!response.ok) {
            const body = await response.json().catch(() => null)
            throw new Error(apiError(body, '下载失败，请重试。'))
          }
          return response.blob()
        }),
        new Promise<never>((_, reject) => {
          timer = window.setTimeout(() => { controller.abort(); reject(new Error('下载超时，请重试。')) }, 30_000)
        }),
      ])
      check()
      const url = URL.createObjectURL(blob)
      try {
        const anchor = document.createElement('a')
        anchor.href = url
        // Keep only the final path segment and remove characters unsafe for file names.
        // eslint-disable-next-line no-control-regex
        anchor.download = filename.split(/[\\/]/).pop()?.replace(/[\u0000-\u001f\u007f<>:"|?*]/g, '').replace(/[. ]+$/g, '').trim() || 'download'
        document.body.append(anchor)
        try { anchor.click() } finally { anchor.remove() }
      } finally { URL.revokeObjectURL(url) }
    } catch (cause) {
      if (active.current && !(cause instanceof DOMException && cause.name === 'AbortError')) {
        setError(safeError(cause, '下载失败，请重试。'))
      }
    } finally {
      window.clearTimeout(timer)
      if (request.current === controller) request.current = null
      if (active.current) setBusy(false)
    }
  }
  return <><a href={href} aria-label={ariaLabel} aria-busy={busy} aria-disabled={busy} onClick={event => void download(event)}>{children}</a>
    {busy && <span role="status">{t("正在下载……")}</span>}{error && <span role="alert" className="error-panel">{t(error)}</span>}</>
}
