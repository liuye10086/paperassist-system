import PreparationPanel from '../datasetPreparation/PreparationPanel';
import PreparedHistory from '../datasetPreparation/PreparedHistory';
import { useEffect, useRef, useState } from 'react';
import { onApiSessionChanged } from '../../shared/api/client';
import { apiError, safeError, useI18n } from '../../shared/i18n';
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink';
import { useDocumentVisible } from '../tasks/useDocumentVisible';
import { statusNames } from '../tasks/taskTypes';
import { datasetRequest, DatasetRequestError, isRows, isStructure, isStructurePage, type DatasetSummary, type RowPage, type StructureCell, type StructurePage, type StructureVersion } from './datasetApi';
import './structureVersions.css';
import ParsedEvidencePanel from '../parsedEvidence/ParsedEvidencePanel';
import FileImpactReview from '../files/FileImpactReview';
import useLifecycleSubmission from '../files/useLifecycleSubmission';
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard';
type Props = {
    projectId: string;
    fileId: string;
    filename: string;
    active: boolean;
    onUnavailable: () => void;
    registerLeaveGuard?: RegisterLeaveGuard;
};
const live = (v: StructureVersion) => ['queued', 'running'].includes(v.task.status);
function letter(column: number) { let result = ''; for (let n = column; n > 0; n = Math.floor((n - 1) / 26))
    result = String.fromCharCode(65 + (n - 1) % 26) + result; return result; }
export default function StructureVersions(props: Props) { return <Panel key={JSON.stringify([props.projectId,props.fileId])} {...props}/>; }
function Panel({ projectId, fileId, filename, active, onUnavailable, registerLeaveGuard }: Props) {
    const { t, locale } = useI18n();
    const visible = useDocumentVisible();
    const [preparing, setPreparing] = useState<DatasetSummary[]>([]);
    const [preparingId, setPreparingId] = useState('');
    const [view, setView] = useState<'structure' | 'prepare' | 'history'>('structure');
    const [history, setHistory] = useState(false);
    const [page, setPage] = useState(1);
    const [list, setList] = useState<StructurePage | null>(null);
    const [selected, setSelected] = useState<StructureVersion | null>(null);
    const [sheet, setSheet] = useState(0);
    const [start, setStart] = useState(1);
    const [rows, setRows] = useState<RowPage | null>(null);
    const [cell, setCell] = useState<StructureCell | null>(null);
    const [loading, setLoading] = useState(true);
    const [review, setReview] = useState(false);
    const [error, setError] = useState('');
    const [rowError, setRowError] = useState('');
    const [sourceUnavailable, setSourceUnavailable] = useState(false);
    const [notice, setNotice] = useState('');
    const [refresh, setRefresh] = useState(0);
    const [valid, setValid] = useState(true);
    const selectedId = useRef<string | null>(null);
    const post = useRef<AbortController | null>(null);
    const requests = useRef(new Set<AbortController>());
    const rowRequest = useRef<AbortController | null>(null);
    const rowGeneration = useRef(0);
    const mounted = useRef(true);
    const [pending, setPending] = useState(false);
    const base = `/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}`;
    const clear = () => { submission.invalidate();setPreparing([]);setHistory(false);setReview(false);requests.current.forEach(c => c.abort()); post.current?.abort(); setValid(false); setList(null); setSelected(null); setRows(null); setCell(null); setError(''); setRowError(''); };
    const unavailable = useRef(onUnavailable);
    useEffect(() => { unavailable.current = onUnavailable; }, [onUnavailable]);
    useEffect(() => { mounted.current = true; const tracked = requests.current; const unsubscribe = onApiSessionChanged(clear); return () => { mounted.current = false; unsubscribe(); tracked.forEach(c => c.abort()); post.current?.abort(); }; }, []);
    function lost() { clear(); unavailable.current(); }
    function downloadRejected(status: number, body: unknown) {
        const code = body && typeof body === 'object' && 'detail' in body
            && body.detail && typeof body.detail === 'object' && 'code' in body.detail
            ? body.detail.code : null;
        if ([401, 403].includes(status) || ([404, 410].includes(status) && ['project_not_found', 'file_not_found'].includes(String(code)))) {
            lost();
        } else if ([404, 410].includes(status) && code === 'dataset_missing') {
            rowGeneration.current++;
            rowRequest.current?.abort();
            setRows(null);
            setCell(null);
            setSourceUnavailable(true);
            setRowError(apiError(body, '原始行读取失败，请重试。'));
        }
    }
    useEffect(() => {
        if (!active || view !== 'structure' || !visible || !valid)
            return;
        let current = true;
        let timer = 0;
        const controller = new AbortController();
        const tracked = requests.current;
        tracked.add(controller);
        async function load() {
            setLoading(true);
            try {
                const value = await datasetRequest(`${base}/structure-versions?page=${page}&page_size=5`, controller, (v): v is StructurePage => isStructurePage(v, projectId, fileId, page), lost);
                if (!current || controller.signal.aborted)
                    return;
                setList(value);
                const latest = page === 1 ? value : await datasetRequest(`${base}/structure-versions?page=1&page_size=5`, controller, (v): v is StructurePage => isStructurePage(v, projectId, fileId, 1), lost);
                if (!current || controller.signal.aborted)
                    return;
                setPending(latest.items.some(live));
                const choice = value.items.find(v => v.id === selectedId.current);
                if (choice) {
                    setSelected(choice);
                }
                else if (!selectedId.current && value.items.length) {
                    selectedId.current = value.items[0].id;
                    setSelected(value.items[0]);
                }
                else if (selectedId.current) {
                    const id = selectedId.current;
                    const detail = await datasetRequest(`${base}/structure-versions/${encodeURIComponent(id)}`, controller, (v): v is StructureVersion => isStructure(v, projectId, fileId) && v.id === id, lost);
                    if (current && !controller.signal.aborted && selectedId.current === id)
                        setSelected(detail);
                }
                if (current && !controller.signal.aborted && latest.items.some(live))
                    timer = window.setTimeout(() => void load(), 5000);
            }
            catch (cause) {
                if (current)
                    setError(safeError(cause, '结构版本请求失败，请重试。'));
            }
            finally {
                if (current)
                    setLoading(false);
            }
        }
        void load();
        return () => { current = false; controller.abort(); tracked.delete(controller); window.clearTimeout(timer); };
    }, [base, projectId, fileId, page, refresh, active, view, visible, valid]);
    const dataset = selected?.datasets[sheet];
    const visibleRows = !sourceUnavailable && !rowError && rows?.dataset.id === dataset?.id && rows?.start_row === start ? rows : null;
    useEffect(() => {
        if (!dataset || !active || view !== 'structure' || !visible || !valid)
            return;
        let current = true;
        const controller = new AbortController();
        rowRequest.current = controller;
        const generation = rowGeneration.current;
        const tracked = requests.current;
        tracked.add(controller);
        void datasetRequest(`${base}/dataset-versions/${encodeURIComponent(dataset.id)}/rows?start_row=${start}&limit=20`, controller, (v): v is RowPage => isRows(v, dataset, start), lost)
            .then(value => { if (current && !controller.signal.aborted) {
            setRows(value);
            setSourceUnavailable(false);
            setRowError('');
        } })
            .catch(cause => { if (current && generation === rowGeneration.current) {
            setRows(null);
            setCell(null);
            if (cause instanceof DatasetRequestError && [404, 410].includes(cause.status))
                setSourceUnavailable(true);
            setRowError(safeError(cause, '原始行读取失败，请重试。'));
        } });
        return () => { current = false; controller.abort(); tracked.delete(controller); if (rowRequest.current === controller) rowRequest.current = null; };
        // The immutable dataset ID, rather than refreshed summary identity, controls row reads.
        // oxlint-disable-next-line react-hooks/exhaustive-deps
    }, [base, dataset?.id, start, active, view, visible, valid, refresh]);
    function choose(v: StructureVersion) { selectedId.current = v.id; setSelected(v); setSheet(0); setStart(1); setRows(null); setRowError(''); setSourceUnavailable(false); setCell(null); }
    function generate() { if (list && !loading && valid && !pending && !submission.unknown && !submission.busy) setReview(true); }
    const submission = useLifecycleSubmission<StructureVersion>((r, signal) => {
        const controller = new AbortController();
        const abort = () => controller.abort(); signal.addEventListener('abort', abort, { once: true });
        if (signal.aborted) controller.abort();
        const request=JSON.parse(r.body);
        return datasetRequest(r.url, controller, (v): v is StructureVersion => isStructure(v, projectId, fileId)&&v.version===request.expected_latest_version+1, lost, {method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':r.key},body:r.body}).finally(()=>signal.removeEventListener('abort',abort));
    }, result => {setReview(false);setNotice('结构生成任务已建立。');if(!selectedId.current)choose(result);setPage(1);setRefresh(n=>n+1)},()=>{setReview(false);setRefresh(n=>n+1)});
    const busy=submission.busy, unknown=submission.unknown;
    return <section className="structure-versions" aria-label={t('原始结构与版本')} aria-busy={loading || busy}>
  <h3>{t('原始结构与版本')}</h3>
  <nav className="material-task-nav" aria-label={t('数据材料任务')}>
    <button aria-pressed={view === 'structure'} onClick={() => setView('structure')}>{t('原始结构')}</button>
    <button aria-pressed={view === 'history'} onClick={() => { setHistory(true); setView('history') }}>{t('整理版本历史')}</button>
  </nav>
  {view !== 'structure' && <button className="material-back" onClick={() => setView('structure')}>{t('返回原始结构')}</button>}
  {history && valid && <div hidden={view !== 'history'}><PreparedHistory projectId={projectId} fileId={fileId} rawDataset={dataset} active={active && view === 'history'} registerLeaveGuard={registerLeaveGuard} /></div>}
  {valid && !sourceUnavailable && preparing.map(source => <div key={source.id} hidden={view !== 'prepare' || preparingId !== source.id}><PreparationPanel projectId={projectId} fileId={fileId} dataset={source} viewActive={active && view === 'prepare' && preparingId === source.id} registerLeaveGuard={registerLeaveGuard} /></div>)}
  <div hidden={view !== 'structure'}>
  <p className="muted">{t('原始结构只读；新分析需在字段配置中明确选择数据版本。完整输出上限为 4 MiB；超过额度整次失败，不保存截断版本。')}</p>
  <div className="structure-actions"><button className="button-primary" disabled={!list || loading || busy || pending || !valid || !submission.valid || unknown} onClick={() => void generate()}>{t(list?.latest_version ? '生成新版本' : '生成结构版本')}</button>
   <button disabled={loading || busy || !valid} onClick={() => { setLoading(true); setError(''); setRefresh(n => n + 1); }}>{t('重新读取版本')}</button>
   {unknown && <button disabled={loading || busy || !valid || !submission.valid} onClick={() => void submission.submit()}>{t('使用同一请求确认生成结果')}</button>}</div>
  {review && active && valid && <FileImpactReview projectId={projectId} fileId={fileId} action="reparse" operation={t(list?.latest_version?'生成新版本':'生成结构版本')} observedVersion={list?.latest_version} onUnavailable={lost} onCancel={()=>setReview(false)} confirmDisabled={busy||unknown||pending||loading||!submission.valid} onConfirm={v=>void submission.submit({url:`${base}/structure-versions`,body:JSON.stringify({expected_latest_version:list?.latest_version,expected_assessment_revision:v.assessment_revision})})}/>}
  {submission.error&&<p role="alert" className="error-panel">{t(submission.error)}</p>}
  {error && <p className="error-panel" role="alert">{t(error)}</p>}{notice && <p role="status">{t(notice)}</p>}{!valid && <p role="alert">{t('结构来源不可用，请重新选择文件。')}</p>}
  {list && valid && <><ul className="structure-version-list">{list.items.map(v => <li key={v.id}><button aria-pressed={selected?.id === v.id} onClick={() => choose(v)}>{t('结构版本 {version}', { version: v.version })} · {t(statusNames[v.task.status])}</button><time dateTime={v.created_at}>{new Date(v.created_at).toLocaleString(locale)}</time>{v.task.error_code && <span>{t(apiError({ code: v.task.error_code }, '结构提取失败。'))}</span>}</li>)}</ul>
   {!list.total && <p>{t('尚未生成结构版本。')}</p>}<div className="structure-pagination"><button disabled={page === 1 || loading} onClick={() => setPage(n => n - 1)}>{t('上一页版本')}</button><span>{t('版本页 {page}', { page })}</span><button disabled={page * 5 >= list.total || loading} onClick={() => setPage(n => n + 1)}>{t('下一页版本')}</button></div></>}
  {selected && valid && <><h4>{t('结构版本 {version}', { version: selected.version })}</h4><p>{t(statusNames[selected.task.status])}</p>
   {!!selected.datasets.length && <><label>{t('工作表')} <select aria-label={t('结构工作表')} value={sheet} onChange={event => { setSheet(Number(event.target.value)); setStart(1); setRows(null); setRowError(''); setSourceUnavailable(false); setCell(null); }}>{selected.datasets.map((d, i) => <option key={d.id} value={i}>{d.sheet_name}</option>)}</select></label>
    {dataset && <>{active&&view==='structure'&&!sourceUnavailable&&<ParsedEvidencePanel projectId={projectId} fileId={fileId} versionId={dataset.id} kind="dataset_version" onUnavailable={lost}/>}<button disabled={sourceUnavailable} onClick={() => { setPreparing(current => current.some(d => d.id === dataset.id) ? current : [...current, dataset]); setPreparingId(dataset.id); setView('prepare') }}>{t('整理数据')}</button>
     <DatasetFacts dataset={dataset}/>{!sourceUnavailable && <ProjectDownloadLink href={`${base}/dataset-versions/${encodeURIComponent(dataset.id)}/download`} filename={`structure-v${dataset.version}-sheet${dataset.sheet_index + 1}.json`} onHttpError={downloadRejected}>{t('下载完整 JSON')}</ProjectDownloadLink>}
     {rowError && <p role="alert">{t(rowError)}</p>}{!rows && !rowError && <p role="status">{t('正在读取原始行……')}</p>}
     {visibleRows && <><div className="structure-table-scroll"><table><caption>{filename} · {dataset.sheet_name} · {t('原始数据版本 {version}', { version: dataset.version })}</caption><thead><tr><th>{t('原始行')}</th>{Array.from({ length: dataset.column_count }, (_, i) => <th key={i}>{letter(i + 1)}</th>)}</tr></thead><tbody>{visibleRows.rows.map(r => <tr key={r.row}><th scope="row">{r.row}</th>{Array.from({ length: dataset.column_count }, (_, i) => { const c = r.cells.find(v => v.column === i + 1); return <td key={i}><button aria-label={t('查看单元格 {coordinate} 来源', { coordinate: `${letter(i + 1)}${r.row}` })} onClick={() => setCell(c ?? { row: r.row, column: i + 1, coordinate: `${letter(i + 1)}${r.row}`, kind: 'blank', value: null, raw_type: null, raw_value: null, number_format: '', formula: null })}>{c?.value === null || c?.value === undefined ? t('空值') : String(c.value) === '' ? t('空字符串') : String(c.value)}</button></td>; })}</tr>)}</tbody></table></div><div className="structure-pagination"><button disabled={start === 1} onClick={() => { setCell(null); setStart(n => Math.max(1, n - 20)); }}>{t('上一页原始行')}</button><span>{t('原始行 {start}–{end} / {total}', { start: dataset.row_count ? start : 0, end: Math.min(start + 19, dataset.row_count), total: dataset.row_count })}</span><button disabled={!visibleRows.has_more} onClick={() => { setCell(null); setStart(n => n + 20); }}>{t('下一页原始行')}</button></div></>}
     {cell && <CellDetails cell={cell} dataset={dataset} filename={filename} stored={!!rows?.rows.find(r => r.row === cell.row)?.cells.some(c => c.column === cell.column)} onClose={() => setCell(null)}/>}</>}
   </>}
  </>}
  </div>
 </section>;
}
function DatasetFacts({ dataset: d }: {
    dataset: DatasetSummary;
}) { const { t } = useI18n(); return <><dl className="structure-facts"><div><dt>{t('存储范围')}</dt><dd>{d.stored_range ?? t('无')}</dd></div><div><dt>{t('内容范围')}</dt><dd>{d.content_range ?? t('无')}</dd></div><div><dt>{t('非空行数')}</dt><dd>{d.nonempty_row_count}</dd></div><div><dt>{t('排除首行后的非空行数')}</dt><dd>{d.nonempty_data_row_count}</dd></div><div><dt>{t('工作表状态')}</dt><dd>{d.state}</dd></div><div><dt>{t('合并范围')}</dt><dd>{d.merged_ranges.join(' · ') || t('无')}</dd></div></dl><p className="muted">{t('非空行数不是研究样本量。首行仅为候选显示名，读取类型不是科学字段定义，单位未确认。')}</p><ul className="structure-fields">{d.fields.map(f => <li key={f.column}>{f.letter} · {f.header_value === null ? t('空值') : String(f.header_value)} · {f.observed_types.map(kind => t(`读取类型：${kind}`)).join(' / ')} · {t('单位未确认')}</li>)}</ul>{d.warnings.length > 0 && <ul className="warning-panel">{d.warnings.map((w, i) => <li key={i}>{t(warningLabels[w] ?? '原始结构包含需人工核对的情况。')}</li>)}</ul>}</>; }
const warningLabels: Record<string, string> = { structure_hidden_sheet: '包含隐藏工作表。', structure_blank_headers: '首行包含空名称。', structure_duplicate_headers: '首行包含重复名称。', structure_merged_cells: '包含合并单元格，未填补覆盖格。', structure_formula_unverified: '公式缓存有效性未确认，未执行公式。', structure_empty_sheet: '空工作表。', structure_first_row_candidate: '首行仅作候选显示名。', structure_whitespace_values: '保留了空白字符串。', structure_precision_preserved: '数值词法原值以文本保留。' };
function CellDetails({ cell: c, dataset: d, filename, stored, onClose }: {
    cell: StructureCell;
    dataset: DatasetSummary;
    filename: string;
    stored: boolean;
    onClose: () => void;
}) { const { t } = useI18n(); return <section className="structure-cell-details" aria-label={t('单元格来源')}><h4>{t('单元格来源')}</h4><button onClick={onClose}>{t('关闭来源详情')}</button><dl><div><dt>{t('来源文件')}</dt><dd>{filename}</dd></div><div><dt>{t('结构版本')}</dt><dd>{d.version}</dd></div><div><dt>{t('工作表')}</dt><dd>{d.sheet_name} ({d.sheet_index + 1})</dd></div><div><dt>{t('原始位置')}</dt><dd>{c.coordinate} · {t('行 {row}，列 {column}', { row: c.row, column: c.column })}</dd></div><div><dt>{t('读取类型')}</dt><dd>{t(`读取类型：${c.kind}`)}</dd></div><div><dt>{t('原值')}</dt><dd><pre>{c.value === null ? t('空值') : JSON.stringify(c.value)}</pre></dd></div><div><dt>{t('存储证据')}</dt><dd>{t(stored ? '有存储单元格' : '未存储单元格，按原位置显示空值')}</dd></div><div><dt>{t('XML 原始类型')}</dt><dd>{c.raw_type ?? t('无')}</dd></div><div><dt>{t('XML 原始值')}</dt><dd><pre>{c.raw_value === null ? t('无') : JSON.stringify(c.raw_value)}</pre></dd></div><div><dt>{t('数字格式')}</dt><dd>{c.number_format || t('无')}</dd></div>{['date', 'datetime', 'time', 'duration'].includes(c.kind) && <div><dt>{t('日期系统')}</dt><dd>{d.epoch}</dd></div>}</dl>{c.formula && <><h4>{t('公式与缓存')}</h4><pre>{c.formula.text ?? t('无独立公式文本')}</pre><pre>{JSON.stringify(c.formula.attributes)}</pre><p>{t('缓存状态：{state}', { state: t(c.formula.cache_state) })}</p><p>{t('缓存类型：{type}', { type: c.formula.cached_type ?? t('无') })}</p><pre>{c.formula.cached_value === null ? t('无') : JSON.stringify(c.formula.cached_value)}</pre><p>{t('公式缓存有效性未确认，未执行公式。')}</p></>}</section>; }
