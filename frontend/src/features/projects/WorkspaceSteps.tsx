import { useContext } from 'react'
import { createPortal } from 'react-dom'
import { WorkspaceChromeContext } from '../../shared/components/WorkspaceChromeContext'
import { useI18n } from '../../shared/i18n'
import './projectJourney.css'

type Step = {
  title: string
  description?: string
  status?: string
  disabledReason?: string
  action: () => void
}

export default function WorkspaceSteps({ steps, current }: { steps: Step[]; current: number }) {
  const { t } = useI18n()
  const chrome = useContext(WorkspaceChromeContext)
  const navigation = <nav className={`project-steps${chrome ? ' is-compact' : ''}`} aria-label={t('项目操作步骤')}>
    <ol>{steps.map((step, index) => <li key={step.title}>
      <button type="button" disabled={!!step.disabledReason} title={t(step.disabledReason || step.description || step.title)}
        aria-label={t('第 {number} 步：{title}', { number: index + 1, title: t(step.title) })}
        aria-current={current === index ? 'step' : undefined} onClick={step.action}>
        <span className="journey-number" aria-hidden="true">{index + 1}</span>
        <span><strong>{t(step.title)}</strong>
          {step.description && <small>{t(step.description)}</small>}
          {step.status && <em className="journey-status">{t(step.status)}</em>}
        </span>
      </button>
    </li>)}</ol>
  </nav>
  return chrome ? chrome.navigation && createPortal(navigation, chrome.navigation) : navigation
}
