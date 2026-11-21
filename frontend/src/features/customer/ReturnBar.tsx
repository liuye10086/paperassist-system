import type { ReactNode } from 'react'
import { useI18n } from '../../shared/i18n'
import type { ReturnTarget } from './returnToken'
import './returnBar.css'

type Props = {
  target: ReturnTarget | null
  /** Called instead of following the link, e.g. to navigate through the workspace router. */
  onReturn?: (href: string) => void
  /** What the customer is doing here for the original location, e.g. “正在为“任务进度”补充资料”. */
  children?: ReactNode
}

// Shown at the top of a page reached with a valid return token (wireframe 02 `.return-bar`).
// Following the link changes the hash, which the customer workspace treats as navigation.
export default function ReturnBar({ target, onReturn, children }: Props) {
  const { t } = useI18n()
  if (!target) return null
  return <div className="return-bar">
    <p className="return-bar-purpose"><span aria-hidden="true">↩ </span><span>{children}</span></p>
    <a className="return-bar-link" href={target.href} onClick={onReturn ? event => {
      event.preventDefault()
      onReturn(target.href)
    } : undefined}>{t('返回 {place}', { place: target.label })}</a>
  </div>
}
