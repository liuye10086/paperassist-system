import { useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import { intakeRequest, jsonRequest, projectBase } from './api'
import type { Content, Declaration, SampleRegistration } from './contracts'
import type { MaterialSource } from './MaterialReferences'

const fields = [
  ['id','样本标识'],['group_id','所属分组'],['donor','供体或个体'],['tissue','组织'],['section','切片'],
  ['batch','批次'],['time','时间'],['dose','剂量'],['sex','性别'],['age','年龄'],
]
type Preview = {samples: SampleRegistration['samples']; conflicts: {row:number; message:string}[]}
type Props = {
  projectId: string; sources: MaterialSource[]; value: Content; disabled: boolean
  onChange: (content: Content) => void
}

export default function SampleTableMapping({projectId, sources, value, disabled, onChange}: Props) {
  const {t} = useI18n()
  const [text, setText] = useState('')
  const [fileId, setFileId] = useState('')
  const [sheet, setSheet] = useState('0')
  const [columns, setColumns] = useState<Record<string,string>>({id:'id', group_id:'group_id'})
  const [experiment, setExperiment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<{request:string; result:Preview} | null>(null)
  const groups = (value.groups ?? []) as SampleRegistration['groups']
  const experiments = (value.experiments ?? []) as Record<string, unknown>[]
  const experimentIds = new Set([...experiments.map(e => String(e.id)), ...groups.map(g => String(g.experiment_id))].filter(Boolean))
  const format = text.split(/\r?\n/,1)[0].includes('\t') ? 'tsv' : 'csv'
  const headers = text.split(/\r?\n/,1)[0].split(format === 'tsv' ? '\t' : ',')
  const mapping = {
    ...Object.fromEntries(fields.filter(([key]) => !fileId && headers.includes(key)).map(([key]) => [key,key])),
    ...Object.fromEntries(Object.entries(columns).filter(([,column]) => column.trim())),
  }
  const groupIds = groups.filter(g => g.experiment_id === experiment).map(g => g.id)
  const body = {
    ...(fileId ? {file_id:fileId, sheet:/^[0-9]+$/.test(sheet) ? Number(sheet) : sheet} : {format, text}),
    mapping, experiment_id:experiment, group_ids:groupIds,
  }
  const request = JSON.stringify(body)
  const shown = preview?.request === request ? preview.result : null
  async function check() {
    setBusy(true)
    setError('')
    setPreview(null)
    try {
      const result = await intakeRequest<Preview>(`${projectBase(projectId)}/design-table-previews`,jsonRequest(body))
      setPreview({request,result})
    } catch (cause) { setError(safeError(cause,'样本表字段、列数或样本标识有冲突，请核对。')) }
    finally { setBusy(false) }
  }
  function accept(result: Preview) {
    const retained = ((value.samples ?? []) as SampleRegistration['samples']).filter(sample => sample.experiment_id !== experiment)
    const ids = new Set(retained.map(sample => sample.id))
    if (result.samples.some(sample => ids.has(sample.id))) {
      setError('样本表字段、列数或样本标识有冲突，请核对。')
      return
    }
    onChange({...value,samples:[...retained,...result.samples]})
    setPreview(null)
  }
  return <section className="questionnaire-section"><h3>{t('样本表映射')}</h3>
    <p>{t('粘贴 CSV 或 TSV 样本表，列名使用 id、group_id、donor、tissue、section、batch、time、dose、sex、age；先预览再加入草稿。')}</p>
    <label>{t('所属实验')}<select disabled={disabled} value={experiment} onChange={e=>setExperiment(e.target.value)}>
      <option value="">{t('请选择')}</option>{[...experimentIds].map(id => <option key={id} value={id}>{id}</option>)}</select></label>
    <label>{t('样本表来源')}<select disabled={disabled} value={fileId} onChange={e=>setFileId(e.target.value)}>
      <option value="">{t('粘贴 CSV 或 TSV')}</option>{sources.filter(s=>s.kind==='file' && /\.(xlsx|csv|tsv)$/i.test(s.name))
        .map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
    {fileId && <label>{t('工作表名称或序号（从 0 开始）')}<input disabled={disabled} value={sheet} onChange={e=>setSheet(e.target.value)}/></label>}
    <section className="questionnaire-section sample-field-mapping"><h3>{t('样本字段映射')}</h3>
      {fields.map(([key,label])=><label key={key}>{t(label)}<input disabled={disabled} value={columns[key] ?? ''}
        placeholder={t('表头名称，留空表示不映射')} onChange={e=>setColumns({...columns,[key]:e.target.value})}/></label>)}</section>
    {!fileId && <label>{t('样本表文本')}<textarea rows={6} disabled={disabled} value={text} onChange={e=>setText(e.target.value)}/></label>}
    <button type="button" disabled={disabled || busy || !groupIds.length || (!text && !fileId)} onClick={()=>void check()}>{t('预览样本表映射')}</button>
    {!groupIds.length && <p>{t('请先在样本分组中登记该实验的分组，再映射样本表。')}</p>}
    {error && <p role="alert">{t(error)}</p>}
    {shown && <><p>{t('预览样本 {count} 条',{count:shown.samples.length})}</p>
      <p>{t('映射预览仅显示前 20 条；加入草稿会采用全部已核对样本。')}</p>
      <div className="bio-table-scroll"><table><thead><tr>{['样本标识','所属实验','所属分组','供体或个体'].map(label=><th key={label}>{t(label)}</th>)}</tr></thead>
        <tbody>{shown.samples.slice(0,20).map((sample,index)=><tr key={index}><td>{String(sample.id)}</td><td>{String(sample.experiment_id)}</td>
          <td>{String(sample.group_id)}</td><td>{(sample.donor as Declaration)?.value ?? t('待确认')}</td></tr>)}</tbody></table></div>
      {shown.conflicts.map((c,i)=><p key={i}>{c.row} · {t(c.message)}</p>)}
      <button type="button" disabled={disabled || shown.conflicts.length > 0} onClick={()=>accept(shown)}>{t('将预览样本加入草稿')}</button></>}
  </section>
}
