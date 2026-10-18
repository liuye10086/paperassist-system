import { useEffect, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import type { PreparedDatasetAnalysisSource } from '../analysis/datasetSource'
import { sameSource } from '../analysis/datasetSource'
import { fileBase, isPreparedVersion, preparationRequest, type PreparedRows } from './preparationApi'
import { isImpactPage, type ImpactPage } from './qualityApi'

const operations = { manual_exclusion: '手选排除', cell_change: '单元格变化', duplicate_exclusion: '重复排除' } as const
export default function QualityImpacts(props: { projectId: string; source: PreparedDatasetAnalysisSource; url: string; downloadUrl: string; checkpointId?: string }) {
 return <Impacts key={`${props.url}:${props.checkpointId ?? ''}`} {...props} />
}
function Impacts({ projectId, source, url, downloadUrl, checkpointId }: { projectId: string; source: PreparedDatasetAnalysisSource; url: string; downloadUrl: string; checkpointId?: string }) {
 const { t } = useI18n(); const [page, setPage] = useState(1); const [operation, setOperation] = useState(''); const [reason, setReason] = useState(''); const [reasonDraft, setReasonDraft] = useState(''); const [result, setResult] = useState<ImpactPage | null>(null); const [error, setError] = useState(''); const [retry, setRetry] = useState(0); const [row, setRow] = useState<number | null>(null)
 useEffect(() => { const controller = new AbortController(); let active = true; const query = new URLSearchParams({ page: String(page), page_size: '20' }); if (operation) query.set('operation', operation); if (reason) query.set('reason', reason); if (checkpointId) query.set('checkpoint_id', checkpointId)
  preparationRequest(`${url}?${query}`, controller, (v): v is ImpactPage => isImpactPage(v, page), '完整质量回执读取失败，请重试。').then(v => { if (active) { setResult(v); setError('') } }).catch(cause => { if (active) { setResult(null); setError(safeError(cause, '完整质量回执读取失败，请重试。')) } }); return () => { active = false; controller.abort() }
 }, [url, checkpointId, page, operation, reason, retry])
 function reset() { setPage(1); setResult(null); setRow(null) }
 return <section className="quality-impacts" aria-label={t('完整质量影响')}><div className="analysis-field-grid"><label>{t('按操作筛选')}<select value={operation} onChange={e => { setOperation(e.target.value); reset() }}><option value="">{t('全部操作')}</option>{Object.entries(operations).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}</select></label><label>{t('按理由精确筛选')}<input value={reasonDraft} onChange={e => setReasonDraft(e.target.value)} /></label><button type="button" onClick={() => { setReason(reasonDraft); reset() }}>{t('应用理由筛选')}</button></div>
 {error && <p role="alert">{t(error)} <button type="button" onClick={() => setRetry(n => n + 1)}>{t('重试')}</button></p>}
 {result && result.page === page && <><p>{t('共 {total} 项影响；第 {page} 页，每页 20 项。', { total: result.total, page })}</p><div className="structure-table-scroll"><table><caption>{t('完整质量影响明细')}</caption><thead><tr><th>{t('原始位置')}</th><th>{t('操作')}</th><th>{t('理由')}</th><th>{t('整理前')}</th><th>{t('整理后')}</th><th>{t('最终状态')}</th></tr></thead><tbody>{result.items.map((item, i) => <tr key={`${item.row}:${item.column}:${item.operation}:${i}`}><th><button type="button" onClick={() => setRow(item.row)}>{item.coordinate ?? t('第 {row} 行', { row: item.row })}</button></th><td>{t(operations[item.operation])}{item.operations.length > 0 && <small>{item.operations.map(op => t(op === 'trim_text' ? '去除首尾空白' : '缺失标记')).join(' → ')}</small>}</td><td>{item.reason_origin === 'user' ? <>{t('用户声明')}：{item.reason}</> : t(item.reason === 'exact_duplicate' ? '全部字段精确重复' : '按已确认规则')}</td><td>{item.before ? <pre>{item.before.value === null ? t('空值（缺失）') : JSON.stringify(item.before.value)}</pre> : t('父版本 v{version} · 源行 {row}', { version: source.dataset_version, row: item.row })}</td><td>{item.after ? <pre>{item.after.value === null ? t('空值（缺失）') : JSON.stringify(item.after.value)}</pre> : item.retained_row !== null ? t('保留源行 {row}', { row: item.retained_row }) : t('全行排除')}</td><td>{t(item.final_retained ? '保留' : '排除')}</td></tr>)}</tbody></table></div><div className="structure-pagination"><button type="button" disabled={page === 1} onClick={() => { setPage(n => n - 1); setResult(null); setRow(null) }}>{t('上一页影响')}</button><button type="button" disabled={page * 20 >= result.total} onClick={() => { setPage(n => n + 1); setResult(null); setRow(null) }}>{t('下一页影响')}</button></div></>}
 <ProjectDownloadLink href={downloadUrl} filename="quality-receipt.json">{t('下载完整质量回执')}</ProjectDownloadLink>
 {row !== null && <RowLocation key={row} projectId={projectId} source={source} row={row} />}</section>
}
function RowLocation({ projectId, source, row }: { projectId: string; source: PreparedDatasetAnalysisSource; row: number }) {
 const { t } = useI18n(); const [result, setResult] = useState<PreparedRows | null>(null); const [error, setError] = useState('')
 useEffect(() => { const controller = new AbortController(); let active = true
  preparationRequest(`${fileBase(projectId, source.file_id)}/prepared-dataset-versions/${encodeURIComponent(source.dataset_id)}/rows?start_row=${row}&limit=20`, controller, (v): v is PreparedRows => !!v && typeof v === 'object' && 'dataset' in v && isPreparedVersion(v.dataset, source.file_id) && sameSource(v.dataset.source, source) && 'start_row' in v && v.start_row === row && 'rows' in v && Array.isArray(v.rows) && v.rows.some(r => r.row === row), '整理数据行读取失败，请重试。').then(v => { if (active) setResult(v) }).catch(cause => { if (active) setError(safeError(cause, '整理数据行读取失败，请重试。')) }); return () => { active = false; controller.abort() }
 }, [projectId, source, row])
 return <aside aria-label={t('父版本源行核对')}><p>{t('父版本 v{version} · 源行 {row}', { version: source.dataset_version, row })}</p>{error && <p role="alert">{t(error)}</p>}{result?.rows.find(item => item.row === row)?.cells.map(cell => <p key={cell.column}>{cell.coordinate}：{String(cell.value ?? t('空值'))}</p>)}</aside>
}
