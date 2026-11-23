import { useState, type ReactNode } from 'react'
import { useI18n } from '../../shared/i18n'
import { analysisTypes } from '../customer/customerRequirementChoices'
import type { Content, Declaration, Version } from './contracts'

type Experiment = { id: string; data_type: string }
type Group = { id: string; name: string; experiment_id: string }
type Sample = { id: string; group_id: string }
type Comparison = { id: string; experiment_id: string; group_id: string; reference_group_id: string }
type Design = Content & {
  experiments?: Experiment[]; groups?: Group[]; samples?: Sample[]; comparisons?: Comparison[]
  observation?: { biological_replicate?: Declaration }
}

export function guidedDesignIssue(design: Design) {
  if (design.experiments?.some(exp => !exp.data_type?.trim())) return '请先填写每项实验的数据类型。'
  const groups = new Map(design.groups?.map(group => [group.id, group.experiment_id]))
  if (design.comparisons?.some(row => !row.group_id || row.group_id === row.reference_group_id ||
    groups.get(row.group_id) !== row.experiment_id || groups.get(row.reference_group_id) !== row.experiment_id))
    return '请为每项比较选择同一实验中的两个不同分组，或移除暂时不用的比较。'
  return ''
}

export function hasGuidedDesignFields(design: Design) {
  return Boolean(design.experiments?.length || design.groups?.length || design.comparisons?.length || design.observation?.biological_replicate?.value)
}

export default function AssignedDesignGuide({ value, requirement, onChange, disabled, materialRequest, onSampleDetails }: {
  value: Design; onChange: (content: Content) => void; disabled: boolean
  requirement: Version|null; materialRequest?: ReactNode; onSampleDetails: () => void
}) {
  const { t } = useI18n()
  const { experiments = [], groups = [], samples = [], comparisons = [], observation = {} } = value
  const [page, setPage] = useState(1)
  const pages = Math.max(1, Math.ceil(groups.length / 5))
  const currentPage = Math.min(page, pages)
  const groupSamples = new Map<string, string[]>()
  for (const sample of samples) {
    const names = groupSamples.get(sample.group_id)
    if (names) names.push(sample.id)
    else groupSamples.set(sample.group_id, [sample.id])
  }
  const experimentsByGroup = new Map(groups.map(group => [group.id, group.experiment_id]))
  const counts = new Map<string, number>()
  const names = new Set<string>()
  const duplicates = new Set<string>()
  for (const group of groups) {
    counts.set(group.experiment_id, (counts.get(group.experiment_id) ?? 0) + 1)
    if (names.has(group.name)) duplicates.add(group.name)
    names.add(group.name)
  }
  const groupLabel = (g: Group) => duplicates.has(g.name) ? g.name + ' · ' + g.id : g.name
  const scope = requirement?.operation === 'confirm' && Array.isArray(requirement.content.scope_items) ? requirement.content.scope_items : []
  const suggestions = analysisTypes.filter(({type}) => scope.some(item => item?.id === type.id && item.status !== 'not_included'))
  const eligibleGroups = groups.filter(group => (counts.get(group.experiment_id) ?? 0) >= 2)
  const setDataType = (index: number, data_type: string) => onChange({...value,
    experiments:experiments.map((item, i) => i === index ? {...item, data_type} : item)})
  const emptyPair: Comparison = { id: '', experiment_id: '', group_id: '', reference_group_id: '' }
  function updatePair(index: number, row: Comparison) {
    const next = [...comparisons]
    next[index] = { ...row, id: row.id || crypto.randomUUID() }
    onChange({ ...value, comparisons: next })
  }
  const replicate = observation.biological_replicate
  return <div className="assigned-design-guide">
    <section>
      <div className="design-guide-heading"><h3>{t('核对样本与分组')}</h3>
        {samples.length > 0 && <button type="button" className="button-quiet" onClick={onSampleDetails}>{t('查看样本明细')}</button>}
      </div>
      {groups.length > 0 && <>
        <p>{t('{groups} 个分组，{samples} 个样本', {groups:groups.length, samples:samples.length})}</p>
        <table className="design-guide-groups"><thead><tr><th>{t('分组名称')}</th><th>{t('样本数')}</th><th>{t('样本标识')}</th></tr></thead>
          <tbody>{groups.slice((currentPage - 1) * 5, currentPage * 5).map(group => {
            const ids = groupSamples.get(group.id) ?? []
            return <tr key={group.id}><th scope="row">{groupLabel(group)}</th><td>{ids.length}</td>
              <td>{ids.slice(0, 3).join(' / ') || '—'}{ids.length > 3 && t('，另有 {count} 个', {count:ids.length - 3})}</td></tr>
          })}</tbody></table>
        {pages > 1 && <nav aria-label={t('样本分组')} className="intake-pagination">
          <button type="button" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>{t('上一页')}</button>
          <span>{currentPage} / {pages}</span>
          <button type="button" disabled={currentPage === pages} onClick={() => setPage(currentPage + 1)}>{t('下一页')}</button>
        </nav>}
      </>}
      {(!groups.length || !samples.length) && <div className="design-guide-missing">
        <strong>{t(groups.length ? '已有分组，还缺样本名单。' : '还没有样本分组。')}</strong>
        <p>{t('做组间比较前，请客户提供样本表，每行写明样本名称和所属分组，例如「A1，对照组」。')}</p>
        {materialRequest}
      </div>}
      {!groups.length && <p>{t('如果只是先核对输入文件，可以直接进入上方第 3 步「执行分析」。')}</p>}
    </section>
    {experiments.length > 0 && <section>
      <h3>{t('确认数据类型')}</h3><p>{t('按实际收到的数据填写，例如「单细胞 RNA 测序」或「Bulk RNA-seq」。')}</p>
      <div className="design-guide-inputs">{experiments.map((exp, index) => {
        const related = groups.filter(group => group.experiment_id === exp.id)
        return <div className="design-guide-type" key={exp.id}><label>{experiments.length === 1 ? t('数据类型') : t('数据类型（{experiment}）', {experiment:exp.id})}
          {experiments.length > 1 && related.length > 0 && <small>{related.map(group => group.name).join(' / ')}</small>}
          <input maxLength={200} required disabled={disabled} value={exp.data_type ?? ''} onChange={e => setDataType(index,e.target.value)}/>
        </label>{!exp.data_type && suggestions.map(({type}) => <button type="button" disabled={disabled} key={type.id}
          onClick={() => setDataType(index,t(type.label))}>{t('使用客户所选的「{type}」',{type:t(type.label)})}</button>)}</div>
      })}</div>
    </section>}
    {(groups.length > 0 || comparisons.length > 0) && <section>
      <h3>{t('设置组间比较')}</h3>
      <p>{t(eligibleGroups.length ? '需要比较两组时，先选要研究的组，再选用来作对照的组。只做聚类或画图时可以留空。' : '组间比较需要同一实验的两个不同分组。当前可以先保存已有资料。')}</p>
      {(comparisons.length ? comparisons : eligibleGroups.length ? [emptyPair] : []).map((row, index) =>
        <div className="design-guide-pair" key={index}>
          <label>{t('比较组')}<select disabled={disabled} value={row.group_id} onChange={e => {
            const id = e.target.value
            const experiment = experimentsByGroup.get(id) ?? ''
            updatePair(index, {...row, group_id:id, experiment_id:experiment,
              reference_group_id:row.reference_group_id !== id && experimentsByGroup.get(row.reference_group_id) === experiment ? row.reference_group_id : ''})
          }}><option value="">{t('选择比较组')}</option>
            {eligibleGroups.map(g => <option key={g.id} value={g.id}>{groupLabel(g)}</option>)}
          </select></label>
          <label>{t('对照组')}<select disabled={disabled || !row.group_id} value={row.reference_group_id}
            onChange={e => updatePair(index, {...row, reference_group_id:e.target.value})}>
            <option value="">{t('选择对照组')}</option>
            {groups.filter(g => g.experiment_id === row.experiment_id && g.id !== row.group_id).map(g =>
              <option key={g.id} value={g.id}>{groupLabel(g)}</option>)}
          </select></label>
          {row.id && <button type="button" className="button-quiet" disabled={disabled}
            onClick={() => onChange({...value, comparisons:comparisons.filter((_, i) => index !== i)})}>{t('移除比较')}</button>}
        </div>)}
      {eligibleGroups.length > 0 && comparisons.length > 0 && comparisons.length < 100 && comparisons.every(row => row.group_id && row.reference_group_id) &&
        <button type="button" disabled={disabled} onClick={() => updatePair(comparisons.length, emptyPair)}>{t('再添加一项比较')}</button>}
    </section>}
    {(experiments.length > 0 || groups.length > 0 || replicate?.value) && <section>
      <h3>{t('说明独立重复')}</h3>
      <label>{t('哪些样本来自不同个体或独立培养？')}<textarea rows={2} maxLength={4000} disabled={disabled}
        placeholder={t(replicate?.state === 'not_applicable' ? '不适用' : '例如，每只果蝇作为一个独立重复。不确定时可以留空。')}
        value={replicate?.value ?? ''} onChange={e => {
          const text = e.target.value
          onChange({...value, observation:{...observation, biological_replicate:{state:text.trim() ? 'known' : 'pending', value:text.trim() ? text : null}}})
        }}/></label>
    </section>}
  </div>
}
