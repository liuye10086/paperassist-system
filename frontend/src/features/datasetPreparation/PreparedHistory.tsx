import { useEffect, useRef, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { datasetRequest, isStructure, type StructureVersion, type DatasetSummary } from '../datasets/datasetApi'
import { sameSource } from '../analysis/datasetSource'
import PreparationPanel from './PreparationPanel'
import { PreparationRulesView, PreparationSummaryView } from './PreparationReview'
import { columnLetter, fileBase, isPreparedVersion, preparationRequest, type PreparedPage, type PreparedRows, type PreparedVersion } from './preparationApi'
import ParsedEvidencePanel from '../parsedEvidence/ParsedEvidencePanel'
import { isQualityVersion, preparedStructure } from './qualityApi'
import PopulationFilterEditorRead from './PopulationFilterEditor'
import PopulationFilter,{FilterCounts,FilterImpacts} from './PopulationFilter'
import QualityPreparationPanel from './QualityPreparationPanel'
import QualityImpacts from './QualityImpacts'
import QualitySummary, { independentPlanMessage, QualityPolicyView } from './QualitySummary'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
type Props = { projectId: string; fileId: string; rawDataset?: DatasetSummary; active?: boolean; registerLeaveGuard?: RegisterLeaveGuard }
export default function PreparedHistory(props: Props) { return <History key={`${props.projectId}:${props.fileId}`} {...props} /> }
function History({ projectId, fileId, rawDataset, active: viewActive = true, registerLeaveGuard }: Props) {
 const { t, locale } = useI18n(); const base = fileBase(projectId, fileId)
 const [page, setPage] = useState(1); const [list, setList] = useState<PreparedPage | null>(null); const [selected, setSelected] = useState<PreparedVersion | null>(null)
 const [rows, setRows] = useState<PreparedRows | null>(null); const [start, setStart] = useState(1); const [refresh, setRefresh] = useState(0); const [error, setError] = useState(''); const [rowError, setRowError] = useState('')
 const [copies, setCopies] = useState<{ dataset: DatasetSummary; version: PreparedVersion }[]>([])
 const [filters,setFilters]=useState<PreparedVersion[]>([]); const [taskView,setTaskView]=useState('')
 const [qualities, setQualities] = useState<PreparedVersion[]>([]); const [previousStarts, setPreviousStarts] = useState<number[]>([])
 const choiceRequest = useRef<AbortController | null>(null); const mounted = useRef(false)
 useEffect(() => {
  mounted.current = true
  return () => { mounted.current = false; choiceRequest.current?.abort(); choiceRequest.current = null }
 }, [])
 useEffect(() => {
  if (!viewActive || taskView) return
  const controller = new AbortController(); let active = true
  preparationRequest(`${base}/prepared-dataset-versions?page=${page}&page_size=5`, controller, (v): v is PreparedPage => !!v && typeof v === 'object' && 'items' in v && Array.isArray(v.items) && v.items.every(item => isPreparedVersion(item, fileId)) && 'page' in v && v.page === page, '整理版本读取失败，请重试。').then(v => { if (active && !controller.signal.aborted) { setList(v); setError('') } }).catch(cause => { if (active) setError(safeError(cause, '整理版本读取失败，请重试。')) })
  return () => { active = false; controller.abort() }
 }, [base, fileId, page, refresh, viewActive, taskView])
 useEffect(() => {
  if (!selected || !viewActive || taskView !== 'detail') return
  const controller = new AbortController(); let active = true
  preparationRequest(`${base}/prepared-dataset-versions/${encodeURIComponent(selected.id)}/rows?start_row=${start}&limit=20`, controller, (v): v is PreparedRows => !!v && typeof v === 'object' && 'dataset' in v && isPreparedVersion(v.dataset, fileId) && sameSource(v.dataset.source, selected.source) && 'start_row' in v && v.start_row === start && 'rows' in v && Array.isArray(v.rows), '整理数据行读取失败，请重试。').then(v => { if (active && !controller.signal.aborted) { setRows(v); setRowError('') } }).catch(cause => { if (active) { setRows(null); setRowError(safeError(cause, '整理数据行读取失败，请重试。')) } })
  return () => { active = false; controller.abort() }
 }, [base, fileId, selected, start, refresh, viewActive, taskView])
 async function choose(version: Pick<PreparedVersion, 'id' | 'source'>, duplicate: boolean | 'quality' = false) {
  choiceRequest.current?.abort()
  const retainedKey = `${duplicate === 'quality' ? 'quality' : 'copy'}:${version.id}`
  if (duplicate && (duplicate === 'quality' ? qualities.some(v=>v.id===version.id) : copies.some(v=>v.version.id===version.id))) { setTaskView(retainedKey); return }
  const controller = new AbortController(); choiceRequest.current = controller
  const isCurrent = () => mounted.current && choiceRequest.current === controller && !controller.signal.aborted
  setError('')
  try {
   const detail = await preparationRequest(`${base}/prepared-dataset-versions/${encodeURIComponent(version.id)}`, controller, (v): v is PreparedVersion => isPreparedVersion(v, fileId) && sameSource(v.source, version.source), '整理版本读取失败，请重试。')
   if (!isCurrent()) return
   if (duplicate === 'quality') { setQualities(previous => [...previous, detail]); setTaskView(`quality:${detail.id}`) }
   else if (duplicate && detail.source.schema_version===1&&'header_row' in detail.recipe) {
    let raw = rawDataset?.id === detail.parent_dataset_id ? rawDataset : undefined
    if (!raw) { const structure = await datasetRequest(`${base}/structure-versions/${encodeURIComponent(detail.source.structure_id)}`, controller, (v): v is StructureVersion => isStructure(v, projectId, fileId) && v.id === detail.source.structure_id, () => {}); raw = structure.datasets.find(d => d.id === detail.parent_dataset_id) }
    if (!isCurrent()) return
    if (!raw) throw new Error('整理版本读取失败，请重试。')
    setCopies(previous => [...previous, { dataset: raw!, version: detail }]); setTaskView(`copy:${detail.id}`)
   } else { setTaskView('detail'); setSelected(detail); setRows(null); setPreviousStarts([]); setStart(Number(/\d+$/.exec(preparedStructure(detail).data_range.split(':')[0])?.[0] ?? 1)) }
  } catch (cause) { if (isCurrent()) setError(safeError(cause, '整理版本读取失败，请重试。')) }
  finally { if (choiceRequest.current === controller) choiceRequest.current = null }
 }
 return <section className="preparation-panel" aria-label={t('整理版本历史')}><h3>{t('整理版本历史')}</h3><button onClick={() => setRefresh(n => n + 1)}>{t('刷新整理版本')}</button>
 {error && <p role="alert" className="error-panel">{t(error)}</p>}
 {taskView && <button className="material-back" onClick={()=>setTaskView('')}>{t('返回整理版本列表')}</button>}
 <div hidden={Boolean(taskView)}>
 {list?.items.map(v => <article key={v.id}><p>{t('原始数据 v{raw} · 整理数据 v{prepared}', { raw: v.parent_dataset_version, prepared: v.version })} · {v.source.sheet_name} · {new Date(v.created_at).toLocaleString(locale)}</p><button onClick={() => void choose(v)}>{t('查看整理版本')}</button> {v.source.schema_version===1 && <button onClick={() => void choose(v, true)}>{t('复制规则到新任务')}</button>} <button onClick={()=>{setFilters(current=>current.some(item=>item.id===v.id)?current:[...current,v]);setTaskView(`filter:${v.id}`)}}>{t('按此版本筛选人群')}</button> <button onClick={() => void choose(v, 'quality')}>{t('按此版本处理质量问题')}</button></article>)}
 {list?.total === 0 && <p>{t('尚无整理版本。')}</p>}
 <div className="structure-pagination"><button disabled={page === 1} onClick={() => setPage(n => n - 1)}>{t('上一页整理版本')}</button><span>{t('第 {page} 页', { page })}</span><button disabled={!list || page * 5 >= list.total} onClick={() => setPage(n => n + 1)}>{t('下一页整理版本')}</button></div>
 </div>
 <div hidden={taskView !== 'detail'}>
 {selected && <><ParsedEvidencePanel projectId={projectId} fileId={fileId} versionId={selected.id} kind="prepared_dataset_version" onUnavailable={()=>{setSelected(null);setRows(null)}}/>{'operation' in selected&&selected.operation==='population_filter'?<><PopulationFilterEditorRead value={selected.recipe} onChange={()=>{}} disabled/><FilterCounts value={selected.summary}/><button onClick={()=>void choose({id:selected.base_source.dataset_id,source:selected.base_source})}>{t('查看直接父版本回执')}</button><FilterImpacts url={selected.impact_url} downloadUrl={selected.impact_download_url}/><p>{t('筛选后必须新建并独立确认计划；旧推荐仅保留溯源，不作为当前有效建议。')}</p></>:isQualityVersion(selected) ? <><QualityPolicyView recipe={selected.recipe} /><QualitySummary summary={selected.summary} baseVersion={selected.base_source.dataset_version} /><button onClick={() => void choose({ id: selected.base_source.dataset_id, source: selected.base_source })}>{t('查看直接父版本回执')}</button><QualityImpacts projectId={projectId} source={selected.base_source} url={selected.impact_url} downloadUrl={selected.impact_download_url} /><p>{t(independentPlanMessage)}</p></> : <><PreparationRulesView recipe={selected.recipe as import('./preparationApi').PreparationRecipe} /><PreparationSummaryView summary={selected.summary as import('./preparationApi').PreparationSummary} /><p>{t('旧版本未记录完整质量处理明细。')}</p></>}<ProjectDownloadLink href={selected.download_url} filename={`prepared-v${selected.version}.json`}>{t('下载完整 JSON')}</ProjectDownloadLink>
 {rowError && <p role="alert" className="error-panel">{t(rowError)}</p>}
 {rows && rows.dataset.id === selected.id && rows.start_row === start && <><div className="structure-table-scroll"><table><caption>{t('整理后的数据行')}</caption><thead><tr><th>{t('原始行')}</th>{preparedStructure(selected).fields.map(f => <th key={f.column}>{columnLetter(f.column)} · {f.name}</th>)}</tr></thead><tbody>{rows.rows.map(r => <tr key={r.row}><th>{r.row}</th>{preparedStructure(selected).fields.map(f => <td key={f.column}>{String(r.cells.find(c => c.column === f.column)?.value ?? t('空值'))}</td>)}</tr>)}</tbody></table></div><div className="structure-pagination"><button disabled={!previousStarts.length} onClick={() => { setStart(previousStarts[previousStarts.length - 1]); setPreviousStarts(previousStarts.slice(0, -1)) }}>{t('上一页原始行')}</button><button disabled={!rows.has_more} onClick={() => { setPreviousStarts([...previousStarts, start]); setStart(rows.next_start_row ?? start + 20) }}>{t('下一页原始行')}</button></div></>}
 </>}
 </div>
 {copies.map(copy => copy.version.source.schema_version===1&&'header_row' in copy.version.recipe && <div key={copy.version.id} hidden={taskView!==`copy:${copy.version.id}`}><PreparationPanel projectId={projectId} fileId={fileId} dataset={copy.dataset} initialRecipe={copy.version.recipe} viewActive={viewActive&&taskView===`copy:${copy.version.id}`} registerLeaveGuard={registerLeaveGuard} onCreated={() => setRefresh(n => n + 1)} /></div>)}
 {filters.map(filter=><div key={filter.id} hidden={taskView!==`filter:${filter.id}`}><PopulationFilter projectId={projectId} source={filter.source} viewActive={viewActive&&taskView===`filter:${filter.id}`} registerLeaveGuard={registerLeaveGuard} onCreated={()=>setRefresh(n=>n+1)}/></div>)}
 {qualities.map(quality=><div key={quality.id} hidden={taskView!==`quality:${quality.id}`}><QualityPreparationPanel projectId={projectId} source={quality.source} viewActive={viewActive&&taskView===`quality:${quality.id}`} registerLeaveGuard={registerLeaveGuard} onCreated={() => setRefresh(n => n + 1)} /></div>)}
 </section>
}
