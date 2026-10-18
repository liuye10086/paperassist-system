import {validExternalText} from '../../features/analysisPlan/recommendationApi'
import { useId, useState } from 'react'
import { useI18n } from '../i18n'
import type { ArtifactDisclosure, ExternalProcessingConfirmation } from '../api/artifactDisclosure'

type Props = { disclosure: ArtifactDisclosure; disabled: boolean; onCancel: () => void; onConfirm: (confirmation: ExternalProcessingConfirmation) => void }
export default function ExternalSendReview({ disclosure, disabled, onCancel, onConfirm }: Props) {
  const { t } = useI18n()
  const id = useId()
  const [labels, setLabels] = useState(() => Object.fromEntries(disclosure.labels.map(label => [label.key, label.value])))
  const groups = disclosure.labels.filter(label => label.key.startsWith('group:')).map(label => labels[label.key].trim())
  const fields=disclosure.labels.filter(l=>l.key.startsWith('field:')).map(l=>labels[l.key].trim())
  const invalid = disclosure.labels.some(l=>disclosure.version>=4?!validExternalText(labels[l.key],l.key==='research_summary'?'summary':l.key==='unit'||l.key.startsWith('unit:')?'unit':'name'):(l.key!=='unit'&&!labels[l.key].trim())||[...labels[l.key]].length>160||/[\p{Cc}\p{Cf}\p{Cs}]/u.test(labels[l.key])) || new Set(groups).size!==groups.length || new Set(fields).size!==fields.length
  function labelName(key: string) {
    if(key.startsWith('effect:'))return t('效应项 {number} 名称',{number:Number(key.slice(7))})
    if(key==='research_summary') return t('本次外发研究摘要')
    if(key.startsWith('field:')) return t('确认外发字段 {column}',{column:key.slice(6)})
    if(key.startsWith('unit:')) return t('字段 {column} 单位',{column:key.slice(5)})
    if (key.startsWith('group:')) return t('分组 {number} 名称', { number: Number(key.slice(6)) + 1 })
    return t(({ numeric_name: '数值名称', unit: '单位', group_name: '分组字段名称', figure_title: '图表标题' } as Record<string, string>)[key])
  }
  return <form className="external-send-review" aria-labelledby={`${id}-title`} onSubmit={event => {
    event.preventDefault()
    if (!disabled && !invalid) onConfirm({ version: disclosure.version, confirmed: true, source_digest: disclosure.source_digest, labels: { ...labels } })
  }}>
    {disclosure.source && <p>{disclosure.source.dataset_kind==='prepared' ? t('来源：{filename}；工作表：{sheet}；原始数据 v{raw} · 整理数据 v{prepared}。', { filename: disclosure.source.filename, sheet: disclosure.source.sheet_name, raw: disclosure.source.parent_dataset_version ?? 0, prepared: disclosure.source.dataset_version }) : t('来源：{filename}；工作表：{sheet}；原始数据版本 v{version}。', { filename: disclosure.source.filename, sheet: disclosure.source.sheet_name, version: disclosure.source.dataset_version })}</p>}
    <h4 id={`${id}-title`}>{t('发送前检查')}</h4>
    <p>{t('有效记录：{valid_count}；排除记录：{excluded_count}；分组：{group_count}。', {valid_count:disclosure.summary.valid_count,excluded_count:disclosure.summary.excluded_count,group_count:disclosure.summary.group_count})}</p>
    {disclosure.version===5&&<p>{t(disclosure.summary.design==='paired'?'纳入 {count} 个完整对；排除 {excluded} 行。':'纳入 {count} 条独立观察；排除 {excluded} 行。',{count:disclosure.summary.valid_count,excluded:disclosure.summary.excluded_count})}</p>}
    {disclosure.version===4&&disclosure.task_type==='boxplot'&&disclosure.summary.figure_kind!=='boxplot'&&<p>{t('外发所选 {count} 个字段的 {n} 条共同完整记录，用于独立复算系数与绘图。',{count:disclosure.summary.variable_count??0,n:disclosure.summary.valid_count})}</p>}
    {disclosure.version===6&&<p>{t(disclosure.task_type==='explanation'?'将发送已核验模型事实、图表资料和确认摘要；不发送原始逐行数据。':disclosure.summary.verification_scope==='local_effect_projection'?'将发送本地系数与区间及确认名称；只核对来源与绘图，不独立重算回归。':'将发送必要匿名结局、评分或随访记录与确认编码，独立核对曲线；不发送 ID。')}</p>}
    {disclosure.version!==6&&<p>{t(disclosure.version===5?disclosure.task_type==='explanation'?'将向 OpenAI 发送已核验的比较统计事实、图表元数据和本次确认摘要；不发送原始逐行数值或配对 ID。':'只外发纳入组的必要数值与确认标签；配对连接采用匿名顺序，不发送 ID 名称或值。':disclosure.task_type === 'boxplot' ? disclosure.summary.figure_kind&&disclosure.summary.figure_kind!=='boxplot'?'将发送已选字段的共同完整数值、确认标签和单位，用于生成相关图表。':'将向 OpenAI 发送所选记录的真实数值、分组及以下绘图名称。' : '将向 OpenAI 发送统计汇总、以下名称及必要图表信息；不上传 Excel 文件或 PNG 图片。')}</p>}
    <p className="muted">{t('请核对名称是否适合外发，可在此修改本次使用的文字。原文件、数值及历史成果不变；单位文字修改不会换算数值。')}</p>
    <div className="external-send-fields">{disclosure.labels.map((label, index) => <label key={label.key} htmlFor={`${id}-${index}`}>
      <span>{labelName(label.key)}</span>
      {label.key==='research_summary'?<textarea id={`${id}-${index}`} value={labels[label.key]} maxLength={4000} rows={4} disabled={disabled} onChange={e=>setLabels(previous=>({...previous,[label.key]:e.target.value}))}/>:<input id={`${id}-${index}`} type="text" value={labels[label.key]} required={label.key !== 'unit'&&!label.key.startsWith('unit:')} maxLength={disclosure.version>=4&&(label.key==='unit'||label.key.startsWith('unit:'))?80:160} disabled={disabled}
        onChange={event => setLabels(previous => ({ ...previous, [label.key]: event.target.value }))} />}
    </label>)}</div>
    {disclosure.version>=4&&disclosure.task_type==='explanation'&&<p className="muted">{t('摘要默认留空；请自行输入并核对可外发文字，不自动发送原研究资料。')}</p>}
    {invalid && <p role="alert">{t('名称须填写且不超过 160 个字符，不含控制字符；各分组名称不得重复。单位可留空。')}</p>}
    <p className="muted">{t('OpenAI 按服务数据政策处理发送的资料。')} <a href="https://developers.openai.com/api/docs/guides/your-data" target="_blank" rel="noreferrer">{t('查看数据政策')}</a></p>
    <div className="analysis-actions"><button type="submit" disabled={disabled || invalid}>{t('确认发送并生成')}</button><button type="button" onClick={onCancel}>{t('取消')}</button></div>
  </form>
}
