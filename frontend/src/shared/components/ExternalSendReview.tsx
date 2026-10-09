import { useId, useState } from 'react'
import { useI18n } from '../i18n'
import type { ArtifactDisclosure, ExternalProcessingConfirmation } from '../api/artifactDisclosure'

type Props = { disclosure: ArtifactDisclosure; disabled: boolean; onCancel: () => void; onConfirm: (confirmation: ExternalProcessingConfirmation) => void }
export default function ExternalSendReview({ disclosure, disabled, onCancel, onConfirm }: Props) {
  const { t } = useI18n()
  const id = useId()
  const [labels, setLabels] = useState(() => Object.fromEntries(disclosure.labels.map(label => [label.key, label.value])))
  const groups = disclosure.labels.filter(label => label.key.startsWith('group:')).map(label => labels[label.key].trim())
  const invalid = disclosure.labels.some(label => (label.key !== 'unit' && !labels[label.key].trim())
    || [...labels[label.key]].length > 160 || /[\p{Cc}\p{Cf}\p{Cs}]/u.test(labels[label.key])) || new Set(groups).size !== groups.length
  function labelName(key: string) {
    if (key.startsWith('group:')) return t('分组 {number} 名称', { number: Number(key.slice(6)) + 1 })
    return t(({ numeric_name: '数值名称', unit: '单位', group_name: '分组字段名称', figure_title: '图表标题' } as Record<string, string>)[key])
  }
  return <form className="external-send-review" aria-labelledby={`${id}-title`} onSubmit={event => {
    event.preventDefault()
    if (!disabled && !invalid) onConfirm({ version: 1, confirmed: true, source_digest: disclosure.source_digest, labels: { ...labels } })
  }}>
    <h4 id={`${id}-title`}>{t('发送前检查')}</h4>
    <p>{t('有效记录：{valid_count}；排除记录：{excluded_count}；分组：{group_count}。', disclosure.summary)}</p>
    <p>{t(disclosure.task_type === 'boxplot' ? '将向 OpenAI 发送所选记录的真实数值、分组及以下绘图名称。' : '将向 OpenAI 发送统计汇总、以下名称及必要图表信息；不上传 Excel 文件或 PNG 图片。')}</p>
    <p className="muted">{t('请核对名称是否适合外发，可在此修改本次使用的文字。原文件、数值及历史成果不变；单位文字修改不会换算数值。')}</p>
    <div className="external-send-fields">{disclosure.labels.map((label, index) => <label key={label.key} htmlFor={`${id}-${index}`}>
      <span>{labelName(label.key)}</span>
      <input id={`${id}-${index}`} type="text" value={labels[label.key]} required={label.key !== 'unit'} maxLength={160} disabled={disabled}
        onChange={event => setLabels(previous => ({ ...previous, [label.key]: event.target.value }))} />
    </label>)}</div>
    {invalid && <p role="alert">{t('名称须填写且不超过 160 个字符，不含控制字符；各分组名称不得重复。单位可留空。')}</p>}
    <p className="muted">{t('OpenAI 按服务数据政策处理发送的资料。')} <a href="https://developers.openai.com/api/docs/guides/your-data" target="_blank" rel="noreferrer">{t('查看数据政策')}</a></p>
    <div className="analysis-actions"><button type="submit" disabled={disabled || invalid}>{t('确认发送并生成')}</button><button type="button" onClick={onCancel}>{t('取消')}</button></div>
  </form>
}
