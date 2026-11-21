import { useId, useLayoutEffect, useRef } from 'react'
import { useI18n } from '../../shared/i18n'

type Props = {
  /** Revision currently in use; the save creates revision + 1. */
  revision: number
  busy: boolean
  onConfirm: () => void
  onCancel: () => void
}

// Asked before overwriting writing materials whose current version already has a generated body or checks.
export default function OverwriteConfirm({ revision, busy, onConfirm, onCancel }: Props) {
  const { t } = useI18n(), id = useId(), dialog = useRef<HTMLDialogElement>(null), cancel = useRef<HTMLButtonElement>(null)
  useLayoutEffect(() => {
    const element = dialog.current
    if (!element) return
    if (!element.open) {
      if (typeof element.showModal === 'function') element.showModal()
      else element.setAttribute('open', '')
    }
    cancel.current?.focus({ preventScroll: true })
    return () => { if (element.open && typeof element.close === 'function') element.close() }
  }, [])
  return <dialog ref={dialog} className="manuscript-overwrite-dialog" aria-labelledby={`${id}-title`} aria-describedby={`${id}-body`} aria-busy={busy}
    onCancel={event => { event.preventDefault(); if (!busy) onCancel() }}>
    <h2 id={`${id}-title`}>{t('覆盖之前的写作材料？')}</h2>
    <div id={`${id}-body`}>
      <p>{t('保存后，这份稿件会按新材料更新为第 {next} 版。第 {revision} 版已生成的正文和核对结果不会带到新版本，需要重新生成正文并重新核对，重新生成会再次产生写作费用。', { next: revision + 1, revision })}</p>
      <p>{t('第 {revision} 版、已下载的 Word 和已开始的返修保持原样，可以在历史中查看。', { revision })}</p>
    </div>
    <div className="manuscript-overwrite-actions">
      <button type="button" ref={cancel} disabled={busy} onClick={onCancel}>{t('取消')}</button>
      <button type="button" className="button-primary" disabled={busy} onClick={onConfirm}>{t(busy ? '正在保存……' : '覆盖并保存')}</button>
    </div>
  </dialog>
}
