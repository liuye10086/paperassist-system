import { useCallback, useEffect, useRef, useState } from 'react';
import { useI18n, apiError } from '../../shared/i18n';
import { onApiSessionChanged } from '../../shared/api/client';
import { useDocumentVisible } from '../tasks/useDocumentVisible';
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink';
import { batchRequest, isBatch, mergeBatch, uploadQueue, validateFile, validateSelection, type UploadBatch, type BatchPage } from './batchUploadApi';
import './batchUpload.css';
const statusLabels = { pending: '等待上传', rejected: '上传被拒绝', queued: '已保存，等待解析', parsing: '文件解析中', parsed: '解析完成', failed: '解析失败' };
export default function BatchUpload({ projectId, active, onUnavailable, onChanged }: {
    projectId: string;
    active: boolean;
    onUnavailable: () => void;
    onChanged: () => void;
}) {
    const { t } = useI18n();
    const visible = useDocumentVisible();
    const [loadError, setLoadError] = useState('');
    const [selection, setSelection] = useState<File[]>([]);
    const [batches, setBatches] = useState<UploadBatch[]>([]);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [local, setLocal] = useState<Record<string, string>>({});
    const [refresh, setRefresh] = useState(0);
    const [page, setPage] = useState(1);
    const [total, setTotal] = useState(0);
    const mounted = useRef(true);
    const controllers = useRef(new Set<AbortController>());
    const files = useRef(new Map<string, File>());
    const snapshots = useRef(new Map<string, UploadBatch>());
    const registration = useRef<{
        key: string;
        items: {
            client_id: string;
            filename: string;
            size_bytes: number;
        }[];
    } | null>(null);
    const running = useRef(false);
    const base = `/api/v1/projects/${encodeURIComponent(projectId)}/file-batches`;
    const changed = useRef(onChanged);
    changed.current = onChanged;
    const stop = useCallback(() => {
        mounted.current = false;
        controllers.current.forEach(c => c.abort());
        controllers.current.clear();
        files.current.clear();
        snapshots.current.clear();
        registration.current = null;
        setSelection([]);
        setBatches([]);
        setLocal({});
        setBusy(false);
    }, []);
    useEffect(() => {
        mounted.current = true;
        const pending = controllers.current;
        const selected = files.current;
        const unsubscribe = onApiSessionChanged(stop);
        return () => {
            unsubscribe();
            mounted.current = false;
            pending.forEach(c => c.abort());
            selected.clear();
        };
    }, [stop]);
    async function request<T>(url: string, valid: (v: unknown) => v is T, init?: RequestInit) {
        const controller = new AbortController();
        controllers.current.add(controller);
        try {
            return await batchRequest(url, controller, onUnavailable, valid, init);
        }
        finally {
            controllers.current.delete(controller);
        }
    }
    function accept(batch: UploadBatch) {
        if (!mounted.current)
            return batch;
        const previous = snapshots.current.get(batch.id);
        const merged = mergeBatch(batch, previous);
        snapshots.current.set(batch.id, merged);
        setLocal(current => {
            const next = { ...current };
            merged.items.forEach(item => {
                if (item.status !== 'pending') {
                    delete next[item.id];
                    files.current.delete(item.id);
                }
            });
            return next;
        });
        // Detail reads only update visible entries; a page response owns membership.
        setBatches(current => current.map(b => b.id === batch.id ? merged : b));
        if ((!previous || merged.revision > previous.revision) && merged.items.some(i => i.file_id))
            changed.current();
        return merged;
    }
    async function reread(batchId: string) {
        const value = await request(`${base}/${encodeURIComponent(batchId)}`, (v): v is UploadBatch => isBatch(v, projectId));
        accept(value);
        return snapshots.current.get(batchId) ?? value;
    }
    useEffect(() => {
        if (!active || !visible || !mounted.current)
            return;
        let alive = true;
        let timer = 0;
        const pending = controllers.current;
        const controller = new AbortController();
        controllers.current.add(controller);
        async function load() {
            try {
                const result = await batchRequest(`${base}?page=${page}&page_size=5`, controller, onUnavailable, (v): v is BatchPage => {
                    const p = v as BatchPage;
                    return !!p && Array.isArray(p.items) && p.items.every(b => isBatch(b, projectId)) && p.page === page && p.page_size === 5 && Number.isSafeInteger(p.total) && p.total >= 0;
                });
                if (!alive || controller.signal.aborted)
                    return;
                setTotal(result.total);
                const currentPage = result.items.map(accept);
                setBatches(currentPage);
                setLoadError('');
                if (currentPage.some(b => b.items.some(i => ['pending', 'queued', 'parsing'].includes(i.status))))
                    timer = window.setTimeout(() => void load(), 5000);
            }
            catch {
                if (alive && !controller.signal.aborted)
                    setLoadError('批次状态读取失败，请重试。');
            }
        }
        void load();
        return () => {
            alive = false;
            controller.abort();
            pending.delete(controller);
            window.clearTimeout(timer);
        };
        // Revisions guard snapshots. Each page has one sequential poll.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [base, projectId, active, visible, page, refresh, onUnavailable]);
    async function send(batch: UploadBatch, itemId: string) {
        const file = files.current.get(itemId);
        if (!file || !mounted.current)
            return;
        setLocal(s => ({ ...s, [itemId]: '正在上传' }));
        try {
            const form = new FormData();
            form.append('file', file);
            await request(`${base}/${encodeURIComponent(batch.id)}/items/${encodeURIComponent(itemId)}`, (v): v is UploadBatch['items'][number] => {
                const i = v as UploadBatch['items'][number];
                return !!i && i.id === itemId && i.filename === file.name && ['pending', 'rejected', 'queued', 'parsing', 'parsed', 'failed'].includes(i.status);
            }, { method: 'POST', body: form });
            if (!mounted.current)
                return;
            // Item receipts have no batch revision and cannot replace a confirmed snapshot.
            await reread(batch.id);
            setLocal(s => ({ ...s, [itemId]: '' }));
        }
        catch {
            if (!mounted.current)
                return;
            const confirmed = snapshots.current.get(batch.id)?.items.find(i => i.id === itemId);
            if (confirmed && confirmed.status !== 'pending') {
                setLocal(s => ({ ...s, [itemId]: '' }));
                setLoadError('批次状态读取失败，请重试。');
            } else setLocal(s => ({ ...s, [itemId]: '接收结果待确认' }));
            try {
                const latest = await reread(batch.id);
                if (latest.items.find(i => i.id === itemId)?.status !== 'pending')
                    setLocal(s => ({ ...s, [itemId]: '' }));
                else
                    setLocal(s => ({ ...s, [itemId]: '上传未保存，可重新上传' }));
            }
            catch { /* Keep unknown outcome and require an explicit reread before retry. */ }
        }
    }
    async function start() {
        if (running.current || !mounted.current)
            return;
        const invalid = validateSelection(selection);
        if (invalid) {
            setError(invalid);
            return;
        }
        running.current = true;
        setBusy(true);
        setError('');
        if (!registration.current) {
            registration.current = { key: crypto.randomUUID(), items: selection.map(file => {
                    const client_id = crypto.randomUUID();
                    files.current.set(client_id, file);
                    return { client_id, filename: file.name, size_bytes: file.size };
                }) };
        }
        try {
            const registered = await request(base, (v): v is UploadBatch => isBatch(v, projectId), { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': registration.current.key }, body: JSON.stringify({ items: registration.current.items }) });
            if (!mounted.current)
                return;
            const confirmed = accept(registered);
            // A new batch belongs to page one. Resume polling before uploads finish.
            setBatches(current => page === 1 ? [confirmed, ...current.filter(b => b.id !== confirmed.id)].slice(0, 5) : [confirmed]);
            setPage(1);
            setRefresh(v => v + 1);
            const controller = new AbortController();
            controllers.current.add(controller);
            try {
                await uploadQueue(registered.items.filter(i => i.status === 'pending'), controller.signal, i => send(registered, i.id));
            }
            finally {
                controllers.current.delete(controller);
            }
            if (mounted.current) {
                registration.current = null;
                setSelection([]);
                setRefresh(v => v + 1);
            }
        }
        catch {
            if (mounted.current)
                setError('登记结果待确认，请使用原选择重试。');
        }
        finally {
            running.current = false;
            if (mounted.current)
                setBusy(false);
        }
    }
    async function retry(batch: UploadBatch, itemId: string) {
        if (running.current)
            return;
        running.current = true;
        setBusy(true);
        try {
            const latest = await reread(batch.id);
            if (latest.items.find(i => i.id === itemId)?.status === 'pending')
                await send(latest, itemId);
        }
        catch {
            if (mounted.current)
                setError('批次状态读取失败，请重试。');
        }
        finally {
            running.current = false;
            if (mounted.current)
                setBusy(false);
        }
    }
    return <section className="batch-upload" aria-label={t('批量上传 Excel / Word / PDF / 图片')}><h2>{t('批量上传 Excel / Word / PDF / 图片')}</h2><p>{t('支持 .xlsx / .docx / .pdf / .png / .jpg / .jpeg，每文件最多 10 MiB，每批最多 10 项，同时上传 2 项。')}</p><label>{t('批量选择 Excel / Word / PDF / 图片 文件')}<input type="file" accept=".xlsx,.docx,.pdf,.png,.jpg,.jpeg" multiple disabled={busy} onChange={e => {
            setSelection(Array.from(e.target.files ?? []));
            registration.current = null;
            setError('');
        }}/></label>
 {selection.length > 0 && <ul>{selection.map((f, i) => <li key={i}>{f.name} · {f.size} {t('字节')}{validateFile(f) && <span className="file-failed"> {t(validateFile(f)!)}</span>}</li>)}</ul>}<button type="button" className="button-primary" disabled={busy || !selection.length || selection.length > 10} onClick={() => void start()}>{t(busy ? '正在上传' : '开始上传')}</button><button type="button" onClick={() => setRefresh(v => v + 1)}>{t('重新读取批次')}</button>{selection.length > 10 && <p role="alert">{t('每批最多选择 10 个文件。')}</p>}{error && <p role="alert">{t(error)}</p>}{loadError && <p role="alert">{t(loadError)}</p>}
 {batches.filter(b => snapshots.current.has(b.id)).map(batch => <article key={batch.id}><h3>{t('上传批次')} · {new Date(batch.created_at).toLocaleString()}</h3><p role="status">{t('已解析 {count} / {total}', { count: batch.items.filter(i => i.status === 'parsed').length, total: batch.items.length })}</p><ul>{batch.items.map(item => <li key={item.id}><strong>{item.filename}</strong> · {t(local[item.id] || statusLabels[item.status])}{item.error && <p>{t(apiError(item.error, '文件处理失败，请重试。'))}</p>}{item.file_id && <ProjectDownloadLink href={`/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(item.file_id)}/download`} filename={item.filename}>{t('下载原文件')}</ProjectDownloadLink>}{item.status === 'pending' && <>{!files.current.has(item.id) && <label>{t('重新选择同一文件')}<input type="file" accept=".xlsx,.docx,.pdf,.png,.jpg,.jpeg" onChange={e => {
                            const f = e.target.files?.[0];
                            if (!f || f.name !== item.filename || f.size !== item.size_bytes) {
                                setError('请选择名称和大小一致的原文件。');
                                return;
                            }
                            files.current.set(item.id, f);
                            setLocal(s => ({ ...s, [item.id]: '' }));
                        }}/></label>}<button type="button" disabled={busy || !files.current.has(item.id) || local[item.id] === '正在上传'} onClick={() => void retry(batch, item.id)}>{t('核对后上传')}</button></>}</li>)}</ul></article>)}
 {total > 5 && <div><button disabled={page === 1} onClick={() => {
                setBatches([]);
                setPage(v => v - 1);
            }}>{t('上一页')}</button><span>{page}</span><button disabled={page * 5 >= total} onClick={() => {
                setBatches([]);
                setPage(v => v + 1);
            }}>{t('下一页')}</button></div>}<p className="muted">{t('离开项目会停止本地传输；服务端已接收的解析任务继续处理。')}</p></section>;
}
