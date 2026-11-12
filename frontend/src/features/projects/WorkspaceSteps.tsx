import { useContext, useEffect, useRef } from 'react'
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
  const scrollArea = useRef<HTMLElement>(null)
  const currentStep = useRef<HTMLButtonElement>(null)
  const slot = chrome?.navigation
  useEffect(() => {
    const area = scrollArea.current
    const step = currentStep.current
    if (!area || !step) return
    function revealStep() {
      if (!area || !step || area.scrollWidth <= area.clientWidth) return
      const visible = area.getBoundingClientRect()
      const active = step.getBoundingClientRect()
      if (active.left < visible.left || active.right > visible.right) {
        area.scrollLeft += active.left + active.width / 2 - visible.left - visible.width / 2
      }
    }
    revealStep()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(revealStep)
    observer.observe(area)
    observer.observe(step)
    return () => observer.disconnect()
  }, [current, slot, steps.length])

  const navigation = <nav ref={scrollArea} className={`project-steps${chrome ? ' is-compact' : ''}`} aria-label={t('项目操作步骤')}>
    <ol>{steps.map((step, index) => <li key={step.title}>
      <button ref={current === index ? currentStep : undefined} type="button" disabled={!!step.disabledReason} title={t(step.disabledReason || step.description || step.title)}
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
  return chrome ? slot && createPortal(navigation, slot) : navigation
}
