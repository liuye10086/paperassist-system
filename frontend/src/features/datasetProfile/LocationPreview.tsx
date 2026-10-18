import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../../shared/i18n'
import { isLocationRows, profileRequest } from './profileApi'
import { type IssueItem, type LocationRows, type Profile } from './profileTypes'
import { typeLabels } from './profileLabels'

export default function LocationPreview({ base, profile, item }: { base: string; profile: Profile; item: IssueItem }) {
 const { t } = useI18n(); const [rows, setRows] = useState<LocationRows | null>(null); const [error, setError] = useState(false); const [attempt, setAttempt] = useState(0)
 const targetCell = useRef<HTMLTableCellElement>(null)
 const firstRow = profile.source.kind === 'prepared_dataset_version' ? Number(/\d+$/.exec(profile.data_range?.split(':')[0] ?? '')?.[0] ?? 1) : 1
 const start = profile.source.kind === 'prepared_dataset_version' && profile.source.schema_version === 2 ? item.row : firstRow + Math.floor((item.row - firstRow) / 20) * 20
 useEffect(() => {
  const controller = new AbortController(); let active = true
  const endpoint = profile.source.kind === 'prepared_dataset_version' ? 'prepared-dataset-versions' : 'dataset-versions'
  profileRequest(`${base}/${endpoint}/${encodeURIComponent(profile.source.dataset_id)}/rows?start_row=${start}&limit=20`, controller, (v): v is LocationRows => isLocationRows(v, profile.source, start, item.row, profile.fields))
   .then(value => { if (active && !controller.signal.aborted) setRows(value) }).catch(() => { if (active) setError(true) })
  return () => { active = false; controller.abort() }
 }, [base, profile, item.row, start, attempt])
 useEffect(() => {
  if (rows && !error) targetCell.current?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
 }, [rows, error, item.row, item.column])
 return <div className="profile-location" aria-live="polite">
  <p>{t('定位：{position}；每次读取 20 行。', { position: item.coordinate ?? t('第 {row} 行', { row: item.row }) })}</p>
  {error ? <p role="alert">{t('数据行读取失败，请重试。')} <button type="button" onClick={() => { setError(false); setRows(null); setAttempt(n => n + 1) }}>{t('重试位置读取')}</button></p> : !rows ? <p role="status">{t('正在读取对应数据行……')}</p> : <div className="profile-table-scroll" tabIndex={0} role="region" aria-label={t('位置核对，可横向滚动')}>
   <table><caption>{t('位置核对（保留 Excel 原始坐标）')}</caption><thead><tr><th>{t('原始行')}</th>{profile.fields.map(field => <th key={field.column}>{field.letter} · {field.name}</th>)}</tr></thead><tbody>{rows.rows.map(row => <tr key={row.row} className={row.row === item.row ? 'profile-row-selected' : ''}><th scope="row">{row.row}</th>{profile.fields.map((field, index) => { const cell = row.cells.find(c => c.column === field.column); return <td key={field.column} ref={row.row === item.row && (item.column === null ? index === 0 : item.column === field.column) ? targetCell : undefined} data-coordinate={`${field.letter}${row.row}`} className={row.row === item.row && (item.column === null || item.column === field.column) ? 'profile-cell-selected' : ''}><span>{cell?.value === null || !cell ? t('空值') : typeof cell.value === 'boolean' ? t(cell.value ? '真' : '假') : cell.value}</span>{cell && <small>{t(typeLabels[cell.kind] ?? '其他类型')}</small>}</td> })}</tr>)}</tbody></table>
  </div>}
 </div>
}
