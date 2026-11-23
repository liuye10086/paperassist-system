import { useI18n } from '../../shared/i18n'
import { analysisTypes, deliveryChoices, type Choice } from '../customer/customerRequirementChoices'
import { WorkspaceIcon } from '../projects/WorkspaceShell'

type ScopeEntry = { id: string; title: string }

function ScopeRow({ label, items, parentTitle }: { label: string; items: ScopeEntry[]; parentTitle?: string }) {
  const { t } = useI18n()
  if (!items.length) return null
  const prefix = parentTitle && parentTitle + ' · '
  return <div className="submitted-scope-row">
    <span>{t(label)}</span>
    <ul aria-label={t(label)}>{items.map(({ id, title }) =>
      <li key={id}>{prefix && title.startsWith(prefix) ? title.slice(prefix.length) : title}</li>
    )}</ul>
  </div>
}

export default function SubmittedScope({ scope }: { scope: ScopeEntry[] }) {
  const { t } = useI18n()
  const remaining = new Map(scope.map(item => [item.id, item]))
  function takeSelected(choices: Choice[]) {
    return choices.flatMap(choice => {
      const item = remaining.get(choice.id)
      if (!item) return []
      remaining.delete(choice.id)
      return [item]
    })
  }
  const groups = analysisTypes.map(({ type, analyses, figures }) => {
    const [selectedType] = takeSelected([type])
    return { id: type.id, title: selectedType?.title ?? t(type.label), selectedType,
      analyses: takeSelected(analyses), figures: takeSelected(figures) }
  }).filter(group => group.selectedType || group.analyses.length || group.figures.length)
  const deliveries = takeSelected(deliveryChoices)

  return <section className="submitted-scope">
    <h2>{t('研究范围')}</h2>
    {groups.map(group => <div className="submitted-scope-type" role="group" aria-label={group.title} key={group.id}>
      <h3><WorkspaceIcon name="chart"/>{group.title}</h3>
      <ScopeRow label="个性化分析" items={group.analyses} parentTitle={group.title}/>
      <ScopeRow label="所需图件" items={group.figures} parentTitle={group.title}/>
    </div>)}
    <ScopeRow label="其他研究范围" items={[...remaining.values()]}/>
    <ScopeRow label="项目交付" items={deliveries}/>
    {!scope.length && <p>{t('暂无已选研究范围。')}</p>}
  </section>
}
