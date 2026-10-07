import { useLayoutEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../shared/i18n'

export default function ProjectCreateDialog({ busy, onClose, children }: { busy: boolean; onClose: () => void; children: ReactNode }) {
  const { t } = useI18n()
  const dialog = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const trigger = document.activeElement as HTMLElement | null
    return () => { if (trigger?.isConnected) trigger.focus() }
  }, [])
  useLayoutEffect(() => {
    if (busy) dialog.current?.focus()
    else dialog.current?.querySelector<HTMLInputElement>('input')?.focus()
  }, [busy])
  return createPortal(<div className="project-dialog-backdrop">
    <div ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="create-project-title" className="project-dialog" onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); if (!busy) onClose() }
      if (event.key !== 'Tab') return
      const controls = dialog.current?.querySelectorAll<HTMLElement>('input:not(:disabled),select:not(:disabled),textarea:not(:disabled),button:not(:disabled)')
      if (!controls?.length) { event.preventDefault(); return }
      const first = controls[0], last = controls[controls.length - 1]
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }}>
      <header><span className="workspace-eyebrow">{t('开始一项新研究')}</span><h2 id="create-project-title">{t('新建项目')}</h2>
        <p>{t('先记录研究主题，再逐步整理资料与分析。')}</p></header>
      {children}
    </div>
  </div>, document.body)
}
