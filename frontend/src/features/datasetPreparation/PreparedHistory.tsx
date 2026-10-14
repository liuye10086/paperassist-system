import { useEffect, useRef, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { datasetRequest, isStructure, type StructureVersion, type DatasetSummary } from '../datasets/datasetApi'
import { sameSource } from '../analysis/datasetSource'
import PreparationPanel from './PreparationPanel'
import { PreparationRulesView, PreparationSummaryView } from './PreparationReview'
import { columnLetter, fileBase, isPreparedVersion, preparationRequest, type PreparedPage, type PreparedRows, type PreparedVersion } from './preparationApi'
import ParsedEvidencePanel from '../parsedEvidence/ParsedEvidencePanel'
type Props = { projectId: string; fileId: string; rawDataset?: DatasetSummary }
export default function PreparedHistory(props: Props) { return <History key={`${props.projectId}:${props.fileId}`} {...props} /> }
function History({ projectId, fileId, rawDataset }: Props) {
 const { t, locale } = useI18n(); const base = fileBase(projectId, fileId)
 const [page, setPage] = useState(1); const [list, setList] = useState<PreparedPage | null>(null); const [selected, setSelected] = useState<PreparedVersion | null>(null)
 const [rows, setRows] = useState<PreparedRows | null>(null); const [start, setStart] = useState(1); const [refresh, setRefresh] = useState(0); const [error, setError] = useState(''); const [rowError, setRowError] = useState('')
 const [copy, setCopy] = useState<{ dataset: DatasetSummary; version: PreparedVersion; instance: number } | null>(null)
 const choiceRequest = useRef<AbortController | null>(null); const mounted = useRef(false)
 useEffect(() => {
  mounted.current = true
  return () => { mounted.current = false; choiceRequest.current?.abort(); choiceRequest.current = null }
 }, [])
 useEffect(() => {
  const controller = new AbortController(); let active = true
  preparationRequest(`${base}/prepared-dataset-versions?page=${page}&page_size=5`, controller, (v): v is PreparedPage => !!v && typeof v === 'object' && 'items' in v && Array.isArray(v.items) && v.items.every(item => isPreparedVersion(item, fileId)) && 'page' in v && v.page === page, '整理版本读取失败，请重试。').then(v => { if (active && !controller.signal.aborted) { setList(v); setError('') } }).catch(cause => { if (active) setError(safeError(cause, '整理版本读取失败，请重试。')) })
  return () => { active = false; controller.abort() }
 }, [base, fileId, page, refresh])
 useEffect(() => {
  if (!selected) return
  const controller = new AbortController(); let active = true
  preparationRequest(`${base}/prepared-dataset-versions/${encodeURIComponent(selected.id)}/rows?start_row=${start}&limit=20`, controller, (v): v is PreparedRows => !!v && typeof v === 'object' && 'dataset' in v && isPreparedVersion(v.dataset, fileId) && sameSource(v.dataset.source, selected.source) && 'start_row' in v && v.start_row === start && 'rows' in v && Array.isArray(v.rows), '整理数据行读取失败，请重试。').then(v => { if (active && !controller.signal.aborted) { setRows(v); setRowError('') } }).catch(cause => { if (active) { setRows(null); setRowError(safeError(cause, '整理数据行读取失败，请重试。')) } })
  return () => { active = false; controller.abort() }
 }, [base, fileId, selected, start, refresh])
 async function choose(version: PreparedVersion, duplicate = false) {
  choiceRequest.current?.abort()
  const controller = new AbortController(); choiceRequest.current = controller
  const isCurrent = () => mounted.current && choiceRequest.current === controller && !controller.signal.aborted
  setError('')
  try {
   const detail = await preparationRequest(`${base}/prepared-dataset-versions/${encodeURIComponent(version.id)}`, controller, (v): v is PreparedVersion => isPreparedVersion(v, fileId) && sameSource(v.source, version.source), '整理版本读取失败，请重试。')
   if (!isCurrent()) return
   if (duplicate) {
    let raw = rawDataset?.id === detail.parent_dataset_id ? rawDataset : undefined
    if (!raw) { const structure = await datasetRequest(`${base}/structure-versions/${encodeURIComponent(detail.source.structure_id)}`, controller, (v): v is StructureVersion => isStructure(v, projectId, fileId) && v.id === detail.source.structure_id, () => {}); raw = structure.datasets.find(d => d.id === detail.parent_dataset_id) }
    if (!isCurrent()) return
    if (!raw) throw new Error('整理版本读取失败，请重试。')
    setCopy(previous => ({ dataset: raw, version: detail, instance: (previous?.instance ?? 0) + 1 }))
   } else { setSelected(detail); setRows(null); setStart(Number(/\d+$/.exec(detail.recipe.data_range.split(':')[0])?.[0] ?? 1)) }
  } catch (cause) { if (isCurrent()) setError(safeError(cause, '整理版本读取失败，请重试。')) }
  finally { if (choiceRequest.current === controller) choiceRequest.current = null }
 }
 return <section className="preparation-panel" aria-label={t('整理版本历史')}><h3>{t('整理版本历史')}</h3><button onClick={() => setRefresh(n => n + 1)}>{t('刷新整理版本')}</button>
 {error && <p role="alert" className="error-panel">{t(error)}</p>}
 {list?.items.map(v => <article key={v.id}><p>{t('原始数据 v{raw} · 整理数据 v{prepared}', { raw: v.parent_dataset_version, prepared: v.version })} · {v.source.sheet_name} · {new Date(v.created_at).toLocaleString(locale)}</p><button onClick={() => void choose(v)}>{t('查看整理版本')}</button> <button onClick={() => void choose(v, true)}>{t('复制规则到新任务')}</button></article>)}
 {list?.total === 0 && <p>{t('尚无整理版本。')}</p>}
 <div className="structure-pagination"><button disabled={page === 1} onClick={() => setPage(n => n - 1)}>{t('上一页整理版本')}</button><span>{t('第 {page} 页', { page })}</span><button disabled={!list || page * 5 >= list.total} onClick={() => setPage(n => n + 1)}>{t('下一页整理版本')}</button></div>
 {selected && <><ParsedEvidencePanel projectId={projectId} fileId={fileId} versionId={selected.id} kind="prepared_dataset_version" onUnavailable={()=>{setSelected(null);setRows(null)}}/><PreparationRulesView recipe={selected.recipe} /><PreparationSummaryView summary={selected.summary} /><ProjectDownloadLink href={selected.download_url} filename={`prepared-v${selected.version}.json`}>{t('下载完整 JSON')}</ProjectDownloadLink>
 {rowError && <p role="alert" className="error-panel">{t(rowError)}</p>}
 {rows && rows.dataset.id === selected.id && rows.start_row === start && <><div className="structure-table-scroll"><table><caption>{t('整理后的数据行')}</caption><thead><tr><th>{t('原始行')}</th>{selected.recipe.fields.map(f => <th key={f.column}>{columnLetter(f.column)} · {f.name}</th>)}</tr></thead><tbody>{rows.rows.map(r => <tr key={r.row}><th>{r.row}</th>{selected.recipe.fields.map(f => <td key={f.column}>{String(r.cells.find(c => c.column === f.column)?.value ?? t('空值'))}</td>)}</tr>)}</tbody></table></div><div className="structure-pagination"><button disabled={start <= Number(/\d+$/.exec(selected.recipe.data_range.split(':')[0])?.[0] ?? 1)} onClick={() => setStart(n => n - 20)}>{t('上一页原始行')}</button><button disabled={!rows.has_more} onClick={() => setStart(n => n + 20)}>{t('下一页原始行')}</button></div></>}
 </>}
 {copy && <PreparationPanel key={copy.instance} projectId={projectId} fileId={fileId} dataset={copy.dataset} initialRecipe={copy.version.recipe} onCreated={() => setRefresh(n => n + 1)} />}
 </section>
}
