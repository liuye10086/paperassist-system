import { useEffect, useId, useRef, useState, type Ref } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { safeError, useI18n } from '../../shared/i18n'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { IntakeError, intakeRequest, jsonRequest, projectBase } from '../research-intake/api'
import type { Content, Intake, MaterialRef, Version } from '../research-intake/contracts'
import { cleanMaterialRefs } from '../research-intake/state'
import useResearchDraft from '../research-results/useResearchDraft'
import {
  analysisTypeChoices, analysisTypes, buildRequirementContent, deliveryChoices, mergeRequirementInput, readRequirementInput,
  sameRequirementInput, toggleRequirementChoice, type Choice, type RequirementInput,
} from './customerRequirementChoices'
import './customerRequirements.css'

type Props = {
  projectId: string
  headingRef?: Ref<HTMLHeadingElement>
  onSubmitted: () => void
  registerLeaveGuard?: RegisterLeaveGuard
}
type Operation = Version['operation']
type Draft = { revision: number; baseline: RequirementInput; input: RequirementInput }
type PendingWrite = { key: string; body: { expected_revision: number; operation: Operation; content: Content; material_refs: MaterialRef[] } }
type LocalState = { draft: Draft | null; pending: PendingWrite | null }
type WriteResult = { revision: number; version: Version }
const emptyLocalState = (): LocalState => ({ draft: null, pending: null })

export default function CustomerRequirements(props: Props) {
  return <RequirementsForm key={props.projectId} {...props}/>
}

function RequirementsForm({ projectId, headingRef, onSubmitted, registerLeaveGuard }: Props) {
  const { t } = useI18n()
  const headingId = useId()
  const base = projectBase(projectId)
  const [root, setRoot] = useState<Intake | null>(null)
  const [reading, setReading] = useState(true)
  const [readAttempt, setReadAttempt] = useState(0)
  const [working, setWorking] = useState(false)
  const [needsReload, setNeedsReload] = useState(false)
  const [error, setError] = useState('')
  const [{ draft, pending }, setLocal] = useResearchDraft(projectId, 'customer-requirements', emptyLocalState)
  const sessionValid = useRef(true)
  const request = useRef<AbortController | null>(null)

  const baseline = readRequirementInput(root?.current_requirement ?? null)
  const input = draft?.input ?? baseline
  const selectedTypes = analysisTypes.filter(group => input.selected.includes(group.type.id))
  const conflict = needsReload || !!(draft && root && draft.revision !== root.revision)
  const busy = reading || working
  useDraftLeaveGuard(registerLeaveGuard, !!draft, working || !!pending)

  useEffect(() => {
    const unsubscribe = onApiSessionChanged(() => {
      sessionValid.current = false
      request.current?.abort()
      setRoot(null)
      setReading(false)
      setWorking(false)
      setNeedsReload(false)
      setError('')
    })
    return () => { unsubscribe(); request.current?.abort() }
  }, [])

  useEffect(() => {
    if (!sessionValid.current) return
    const controller = new AbortController()
    request.current = controller
    void intakeRequest<Intake>(`${base}/research-intake`, { signal: controller.signal }).then(data => {
      if (controller.signal.aborted) return
      if (data?.project_id !== projectId || !Number.isSafeInteger(data.revision) || data.revision < 1 || !Array.isArray(data.deliveries)) {
        throw new Error('Invalid intake response')
      }
      setRoot(data)
      setNeedsReload(false)
    }).catch(cause => {
      if (!controller.signal.aborted) setError(safeError(cause, '需求读取失败，请重试。'))
    }).finally(() => {
      if (request.current === controller) request.current = null
      if (!controller.signal.aborted) setReading(false)
    })
    return () => controller.abort()
  }, [base, projectId, readAttempt])

  function reload() {
    if (!sessionValid.current || request.current) return
    setError('')
    setReading(true)
    setReadAttempt(value => value + 1)
  }

  function updateInput(next: RequirementInput) {
    if (!root || busy || pending) return
    setError('')
    const original = draft?.baseline ?? baseline
    setLocal({ pending: null, draft: sameRequirementInput(next, original) ? null : {
      revision: draft?.revision ?? root.revision, baseline: original, input: next,
    } })
  }

  function resolveConflict(keepLocal: boolean) {
    if (!root || !draft || needsReload || busy || pending) return
    const merged = keepLocal ? mergeRequirementInput(draft.baseline, draft.input, baseline) : baseline
    setLocal({ pending: null, draft: sameRequirementInput(merged, baseline) ? null : {
      revision: root.revision, baseline, input: merged,
    } })
    setError('')
  }

  async function resolveWrite(write: PendingWrite, lookup = false) {
    if (!sessionValid.current || request.current) return
    const controller = new AbortController()
    request.current = controller
    if (!lookup) setLocal({ draft, pending: write })
    setWorking(true)
    setError('')
    const { key, body } = write
    const revision = body.expected_revision + 1
    let accepted = false
    try {
      let version: Version
      if (lookup) {
        version = await intakeRequest<Version>(`${base}/requirements/requests/${encodeURIComponent(key)}`, { signal: controller.signal })
      } else {
        const result = await intakeRequest<WriteResult>(`${base}/requirements`, { ...jsonRequest(body, key), signal: controller.signal })
        if (result?.revision !== revision) throw new Error('Invalid requirement revision')
        version = result.version
      }
      if (controller.signal.aborted) return
      if (!version?.id || version.operation !== body.operation || version.content?.schema_version !== 1 ||
          (version.project_id && version.project_id !== projectId)) throw new Error('Invalid requirement version')
      setLocal(emptyLocalState())
      setNeedsReload(false)
      setRoot(previous => previous && previous.revision <= revision ? { ...previous, revision, current_requirement: version } : previous)
      accepted = true
    } catch (cause) {
      if (controller.signal.aborted) return
      if (lookup) {
        setError(cause instanceof IntakeError && cause.status === 404
          ? '尚未查到这次保存。可按原请求重试。'
          : safeError(cause, '需求读取失败，请重试。'))
      } else if (cause instanceof IntakeError && cause.status >= 400 && cause.status < 500 && cause.status !== 408) {
        setLocal({ draft, pending: null })
        if (cause.status === 409) setNeedsReload(true)
        else setError(safeError(cause, '需求保存失败，编辑内容已保留。'))
      }
    } finally {
      if (request.current === controller) request.current = null
      if (!controller.signal.aborted) setWorking(false)
    }
    if (accepted && body.operation === 'confirm') onSubmitted()
    else if (accepted && !root) reload()
  }

  function save(operation: Operation) {
    if (!root || busy || pending || conflict || request.current) return
    // Preserve submissions from drafts that already contain notes.
    if (operation === 'confirm' && !selectedTypes.length && !input.notes.trim()) {
      setError('请选择至少一种分析类型。')
      return
    }
    const content = buildRequirementContent(root, input, operation, t)
    if (Array.isArray(content.scope_items) && content.scope_items.length > 100) {
      setError('新选项与已有范围合计超过 100 项，请减少本次选择。')
      return
    }
    void resolveWrite({ key: crypto.randomUUID(), body: {
      expected_revision: root.revision, operation, content,
      material_refs: cleanMaterialRefs(root.current_requirement?.material_refs ?? []),
    } })
  }

  const choiceProps = { selected: input.selected, onChange: (id: string, checked: boolean) => updateInput(toggleRequirementChoice(input, id, checked)) }
  const current = root?.current_requirement
  const status = draft ? '有未保存的修改。' : current?.operation === 'confirm' ? '需求已提交。' : current ? '草稿已保存。' : '尚未保存需求。'
  const disabled = busy || !!pending
  return <section className="customer-section customer-requirements" aria-labelledby={headingId}>
    <header className="customer-requirements__header">
      <h1 id={headingId} ref={headingRef} tabIndex={-1}>{t('选择需求')}</h1>
      {root && !pending && <p role="status">{t(status)}</p>}
    </header>
    {reading && <p role="status">{t('正在读取需求……')}</p>}
    {!root && !reading && error && <button type="button" onClick={reload}>{t('重新读取需求')}</button>}
    {root && <div className="customer-requirements__form" aria-busy={busy}>
      <div className="customer-requirements__row">
        <span id={`${headingId}-types`}>{t('分析类型')}</span>
        <fieldset aria-labelledby={`${headingId}-types`} disabled={disabled}>
          <ChoiceGroup choices={analysisTypeChoices} {...choiceProps}/>
        </fieldset>
      </div>
      <div className="customer-requirements__row">
        <span id={`${headingId}-analyses`}>{t('个性化分析')}</span>
        <fieldset aria-labelledby={`${headingId}-analyses`} disabled={disabled}>
          {selectedTypes.length === 0 ? <p>{t('选择分析类型后可勾选对应的分析。')}</p> :
            <div className="customer-requirements__groups">
              {selectedTypes.map(group => <ChoiceGroup key={group.type.id} title={group.customerChoice.label} choices={group.analyses}
                disabled={!!group.customerChoice.disabledReason} {...choiceProps}/>)}
            </div>}
        </fieldset>
      </div>
      <div className="customer-requirements__row">
        <span id={`${headingId}-deliveries`}>{t('图件与交付')}</span>
        <fieldset aria-labelledby={`${headingId}-deliveries`} disabled={disabled}>
          <div className="customer-requirements__groups">
            {selectedTypes.map(group => <ChoiceGroup key={group.type.id} title={group.customerChoice.label} choices={group.figures}
              disabled={!!group.customerChoice.disabledReason} {...choiceProps}/>)}
            <ChoiceGroup title="项目交付" choices={deliveryChoices} {...choiceProps}/>
          </div>
        </fieldset>
      </div>
    </div>}
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    {conflict && !pending && <div className="customer-requirements__recovery">
      <p role="status">{t(needsReload
        ? '服务器已有新版本，草稿已保留。重新读取后核对并合并，再保存。'
        : '服务器版本已读取。可合并本地修改或采用服务器版本。')}</p>
      <div className="customer-requirements__actions">
        <button type="button" disabled={busy} onClick={reload}>{t('读取服务器版本并保留草稿')}</button>
        {!needsReload && draft && root && <>
          <button type="button" disabled={busy} onClick={() => resolveConflict(true)}>{t('合并本地修改')}</button>
          <button type="button" disabled={busy} onClick={() => resolveConflict(false)}>{t('采用已读取的服务器版本')}</button>
        </>}
      </div>
    </div>}
    {pending && <div className="customer-requirements__recovery">
      <p role="status">{t(working ? '正在处理需求请求……' : '需求保存结果尚未确认。请核对或按原请求重试。')}</p>
      {!working && <div className="customer-requirements__actions">
        <button type="button" disabled={reading} onClick={() => void resolveWrite(pending, true)}>{t('核对保存结果')}</button>
        <button type="button" disabled={reading} onClick={() => void resolveWrite(pending)}>{t('按原请求重试')}</button>
      </div>}
    </div>}
    {root && <footer className="customer-requirements__actions">
      <button type="button" disabled={disabled || conflict} onClick={() => save('save')}>{t('保存草稿')}</button>
      <button type="button" className="button-primary" disabled={disabled || conflict} onClick={() => save('confirm')}>{t('提交需求')}</button>
    </footer>}
  </section>
}

function ChoiceGroup({ choices, title, selected, onChange, disabled = false }: {
  choices: Choice[]
  title?: string
  selected: string[]
  onChange: (id: string, checked: boolean) => void
  disabled?: boolean
}) {
  const { t } = useI18n()
  return <div className="customer-requirements__group" role={title ? 'group' : undefined} aria-label={title && t(title)}>
    {title && <h3>{t(title)}</h3>}
    <div className="customer-requirements__choices">
      {choices.map(choice => <label className="customer-requirements__choice" key={choice.id}>
        <input type="checkbox" checked={selected.includes(choice.id)} disabled={disabled || !!choice.disabledReason}
          onChange={event => onChange(choice.id, event.target.checked)}/>
        <span className="customer-requirements__choice-text">
          <span>{t(choice.label)}</span>
          {choice.disabledReason && <small className="customer-requirements__choice-status">{t(choice.disabledReason)}</small>}
        </span>
      </label>)}
    </div>
  </div>
}
