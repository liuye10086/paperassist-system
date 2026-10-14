import { lifecycleResponse } from '../files/lifecycleFixtures'
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import StructureVersions from './StructureVersions';
afterEach(() => { vi.unstubAllGlobals(); });
it('explicitly generates structure and rereads an unknown response without automatic POST replay', async () => {
    const fetch = vi.fn(async (_url: string, init?: RequestInit) => { const impact=lifecycleResponse(_url,'f1');if(impact)return impact; if (init?.method === 'POST')
        throw new TypeError('network'); return new Response(JSON.stringify({ items: [], total: 0, page: 1, page_size: 5, latest_version: 0 })); });
    vi.stubGlobal('fetch', fetch);
    render(<StructureVersions projectId="p1" fileId="f1" filename="data.xlsx" active onUnavailable={() => { }}/>);
    await waitFor(() => expect(screen.getByRole('button', { name: '生成结构版本' }).hasAttribute('disabled')).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '生成结构版本' }));
    await waitFor(()=>expect(screen.getByRole('button',{name:'确认并开始重解析'}).hasAttribute('disabled')).toBe(false));fireEvent.click(screen.getByRole('button',{name:'确认并开始重解析'}));
    await screen.findByText('提交结果尚未确认，请使用同一请求确认结果。');
    await waitFor(() => expect(fetch.mock.calls.filter(call => call[1]?.method !== 'POST').length).toBeGreaterThan(1));
    expect(fetch.mock.calls.filter(call => call[1]?.method === 'POST')).toHaveLength(1);
    expect(screen.getByText(/4 MiB/)).toBeTruthy();
});
import { cleanup } from '@testing-library/react';
import { dataset, page, rowPage, version } from './datasetFixtures';
import { setApiSession } from '../../shared/api/client';
afterEach(cleanup);
it('unknown generation remains replayable after reread discovers the active task created by that request',async()=>{
 let submitted=false;const posts:RequestInit[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{const impact=lifecycleResponse(url,'f1');if(impact)return impact;if(init?.method==='POST'){posts.push(init);if(posts.length===1){submitted=true;throw new TypeError('lost response')}return Response.json(version)}return Response.json(url.includes('/rows?')?rowPage():{items:submitted?[{...version,completed_at:null,datasets:[],task:{...version.task,status:'queued',display_status:'queued'}}]:[],total:submitted?1:0,page:1,page_size:5,latest_version:submitted?1:0})}))
 render(<StructureVersions projectId="p1" fileId="f1" filename="data.xlsx" active onUnavailable={()=>{}}/>);await waitFor(()=>expect(screen.getByRole('button',{name:'生成结构版本'}).hasAttribute('disabled')).toBe(false));fireEvent.click(screen.getByRole('button',{name:'生成结构版本'}));await waitFor(()=>expect(screen.getByRole('button',{name:'确认并开始重解析'}).hasAttribute('disabled')).toBe(false));fireEvent.click(screen.getByRole('button',{name:'确认并开始重解析'}));await screen.findByText('提交结果尚未确认，请使用同一请求确认结果。');fireEvent.click(screen.getByRole('button',{name:'重新读取版本'}));await screen.findByRole('button',{name:'结构版本 1 · 待执行'})
 await waitFor(()=>expect(screen.getByRole('button',{name:'使用同一请求确认生成结果'}).hasAttribute('disabled')).toBe(false));fireEvent.click(screen.getByRole('button',{name:'使用同一请求确认生成结果'}));await screen.findByText('结构生成任务已建立。');expect(posts[1].body).toBe(posts[0].body);expect(new Headers(posts[1].headers).get('Idempotency-Key')).toBe(new Headers(posts[0].headers).get('Idempotency-Key'))
})
it('reads rows 21 through 31 and displays shared follower evidence without inventing formula text', async () => {
    const summary = { ...dataset, column_count: 3, stored_range: 'A1:C31', content_range: 'A1:C31' };
    const follower = { row: 31, column: 3, coordinate: 'C31', kind: 'formula', value: '=', raw_type: 'n', raw_value: '31', number_format: 'General', formula: { text: null, attributes: { t: 'shared', si: '0' }, cache_state: 'present', cached_type: 'n', cached_value: '31', cache_validity: 'unverified' } };
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
        if (!url.includes('/rows?')) return Response.json({ ...page, items: [{ ...version, datasets: [summary] }] });
        const response = rowPage(url.includes('start_row=21') ? 21 : 1);
        return Response.json({ ...response, dataset: summary, rows: response.rows.map(row => row.row === 31 ? { ...row, cells: [...row.cells, follower] } : row) });
    }));
    render(<StructureVersions projectId="p1" fileId="f1" filename="data.xlsx" active onUnavailable={() => { }}/>);
    await screen.findByRole('button', { name: '查看单元格 A1 来源' });
    fireEvent.click(screen.getByRole('button', { name: '下一页原始行' }));
    await screen.findByRole('button', { name: '查看单元格 A21 来源' });
    fireEvent.click(await screen.findByRole('button', { name: '查看单元格 C31 来源' }));
    expect(screen.getByText('无独立公式文本')).toBeTruthy();
    expect(screen.getByText('{"t":"shared","si":"0"}')).toBeTruthy();
    expect(screen.getAllByText('"31"')).toHaveLength(2);
    expect(screen.getByText('公式缓存有效性未确认，未执行公式。')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
});
it('closes stored cell evidence when paging original rows', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(url.includes('/rows?') ? rowPage(url.includes('start_row=21') ? 21 : 1) : page)));
    render(<StructureVersions projectId="p1" fileId="f1" filename="data.xlsx" active onUnavailable={() => { }}/ >);
    fireEvent.click(await screen.findByRole('button', { name: '查看单元格 A1 来源' }));
    expect(screen.getByText('有存储单元格')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '下一页原始行' }));
    await screen.findByRole('button', { name: '查看单元格 A31 来源' });
    expect(screen.queryByRole('region', { name: '单元格来源' })).toBeNull();
});
it.each([[403, 'forbidden'], [404, 'file_not_found'], [404, 'project_not_found'], [401, 'unauthorized']])('clears structure source after download HTTP %s %s', async (status, code) => {
    const unavailable = vi.fn();
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/download') ? Response.json({ detail: { code } }, { status: Number(status) }) : Response.json(url.includes('/rows?') ? rowPage() : page)));
    render(<StructureVersions projectId="p1" fileId="f1" filename="data.xlsx" active onUnavailable={unavailable}/>);
    fireEvent.click(await screen.findByRole('button', { name: '查看单元格 A1 来源' }));
    fireEvent.click(screen.getByRole('link', { name: '下载完整 JSON' }));
    await waitFor(() => expect(screen.queryByRole('link', { name: '下载完整 JSON' })).toBeNull());
    expect(screen.queryByRole('region', { name: '单元格来源' })).toBeNull();
    expect(screen.queryByRole('button', { name: '结构版本 1 · 已完成' })).toBeNull();
});
it.each([404, 410])('clears only dataset rows and download after dataset_missing HTTP %s', async status => {
    const unavailable = vi.fn();
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/download') ? Response.json({ detail: { code: 'dataset_missing' } }, { status }) : Response.json(url.includes('/rows?') ? rowPage() : page)));
    render(<><p>旧文件用途草稿</p><StructureVersions projectId="p1" fileId="f1" filename="data.xlsx" active onUnavailable={unavailable}/></>);
    fireEvent.click(await screen.findByRole('button', { name: '查看单元格 A1 来源' }));
    fireEvent.click(screen.getByRole('link', { name: '下载完整 JSON' }));
    await waitFor(() => expect(screen.queryByRole('link', { name: '下载完整 JSON' })).toBeNull());
    expect(screen.queryByRole('button', { name: '查看单元格 A1 来源' })).toBeNull();
    expect(screen.queryByRole('region', { name: '单元格来源' })).toBeNull();
    expect(screen.getByRole('button', { name: '结构版本 1 · 已完成' })).toBeTruthy();
    expect(screen.getByText('旧文件用途草稿')).toBeTruthy();
    expect(unavailable).not.toHaveBeenCalled();
});
it('preserves original row numbers and sparse cell sources across twenty-row pages', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(url.includes('/rows?') ? rowPage(url.includes('start_row=21') ? 21 : 1) : page)));
    render(<StructureVersions projectId="p1" fileId="f1" filename="data.xlsx" active onUnavailable={() => { }}/>);
    await screen.findByRole('button', { name: '查看单元格 B1 来源' });
    fireEvent.click(screen.getByRole('button', { name: '查看单元格 B1 来源' }));
    expect(screen.getByText('未存储单元格，按原位置显示空值')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '下一页原始行' }));
    await screen.findByRole('button', { name: '查看单元格 A31 来源' });
    fireEvent.click(screen.getByRole('button', { name: '查看单元格 A31 来源' }));
    expect(screen.getAllByText('"9007199254740993"').length).toBe(2);
    expect(screen.getByRole('link', { name: '下载完整 JSON' }).getAttribute('href')).toContain('/dataset-versions/d1/download');
});
it('keeps an old successful version readable when the newest version failed', async () => {
    const failed = { ...version, id: 's2', version: 2, datasets: [], task: { ...version.task, status: 'failed', error_code: 'excel_output_limit', input_version: { ...version.task.input_version, structure_id: 's2' } } };
    vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(url.includes('/rows?') ? rowPage() : { ...page, items: [failed, version], total: 2, latest_version: 2 })));
    render(<StructureVersions projectId="p1" fileId="f1" filename="data.xlsx" active onUnavailable={() => { }}/>);
    fireEvent.click(await screen.findByRole('button', { name: '结构版本 1 · 已完成' }));
    await screen.findByRole('button', { name: '查看单元格 A1 来源' });
    fireEvent.click(screen.getByRole('button', { name: '重新读取版本' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '结构版本 1 · 已完成' }).getAttribute('aria-pressed')).toBe('true'));
    expect(screen.getByRole('link', { name: '下载完整 JSON' })).toBeTruthy();
});
it('clears source and ignores delayed rows after session change', async () => {
    let resolve!: (response: Response) => void;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.includes('/rows?') ? await new Promise<Response>(done => { resolve = done; }) : Response.json(page)));
    render(<StructureVersions projectId="p1" fileId="f1" filename="data.xlsx" active onUnavailable={() => { }}/>);
    await screen.findByRole('link', { name: '下载完整 JSON' });
    setApiSession('next');
    await waitFor(() => expect(screen.queryByRole('link', { name: '下载完整 JSON' })).toBeNull());
    resolve(Response.json(rowPage()));
    await waitFor(() => expect(screen.queryByRole('button', { name: '查看单元格 A1 来源' })).toBeNull());
});
it('rereads version conflict before allowing another request', async () => {
    let posts = 0;
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => { const impact=lifecycleResponse(_url,'f1');if(impact)return impact; if (init?.method === 'POST') {
        posts++;
        return Response.json({ detail: { code: 'structure_version_conflict' } }, { status: 409 });
    } return Response.json({ items: [], total: 0, page: 1, page_size: 5, latest_version: 0 }); }));
    render(<StructureVersions projectId="p1" fileId="f1" filename="data.xlsx" active onUnavailable={() => { }}/>);
    await waitFor(() => expect(screen.getByRole('button', { name: '生成结构版本' }).hasAttribute('disabled')).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '生成结构版本' }));
    await waitFor(()=>expect(screen.getByRole('button',{name:'确认并开始重解析'}).hasAttribute('disabled')).toBe(false));fireEvent.click(screen.getByRole('button',{name:'确认并开始重解析'}));
    await screen.findByRole('alert');
    await waitFor(() => expect(screen.getByRole('button', { name: '生成结构版本' }).hasAttribute('disabled')).toBe(false));
    expect(posts).toBe(1);
});
import { act } from '@testing-library/react';
it('preserves the idempotency key and expected version for explicit confirmation after reread', async () => {
    const posts: RequestInit[] = [];
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => { const impact=lifecycleResponse(_url,'f1');if(impact)return impact; if (init?.method === 'POST') {
        posts.push(init);
        if (posts.length === 1)
            throw new TypeError('lost');
        return Response.json(version);
    } return Response.json({ items: [], total: 0, page: 1, page_size: 5, latest_version: 0 }); }));
    render(<StructureVersions projectId="p1" fileId="f1" filename="data.xlsx" active onUnavailable={() => { }}/>);
    await waitFor(() => expect(screen.getByRole('button', { name: '生成结构版本' }).hasAttribute('disabled')).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '生成结构版本' }));
    await waitFor(()=>expect(screen.getByRole('button',{name:'确认并开始重解析'}).hasAttribute('disabled')).toBe(false));fireEvent.click(screen.getByRole('button',{name:'确认并开始重解析'}));
    await waitFor(() => expect(screen.getByRole('button', { name: '使用同一请求确认生成结果' }).hasAttribute('disabled')).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '使用同一请求确认生成结果' }));
    await screen.findByText('结构生成任务已建立。');
    expect(posts[1].body).toBe(posts[0].body);
    expect(new Headers(posts[1].headers).get('Idempotency-Key')).toBe(new Headers(posts[0].headers).get('Idempotency-Key'));
});
it('times out a stalled read after fifteen seconds and permits a read-only retry', async () => {
    vi.useFakeTimers();
    try {
        const fetch = vi.fn(() => new Promise<Response>(() => { }));
        vi.stubGlobal('fetch', fetch);
        render(<StructureVersions projectId="p1" fileId="f1" filename="data.xlsx" active onUnavailable={() => { }}/>);
        await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
        expect(screen.getByRole('alert').textContent).toBe('结构版本请求失败，请重试。');
        expect((fetch.mock.calls[0] as unknown as [
            string,
            RequestInit
        ])[1].signal?.aborted).toBe(true);
        fireEvent.click(screen.getByRole('button', { name: '重新读取版本' }));
        expect(fetch).toHaveBeenCalledTimes(2);
    }
    finally {
        vi.useRealTimers();
    }
});
it('polls with no overlapping reads, pauses while hidden, and keeps the chosen old version', async () => {
    vi.useFakeTimers();
    try {
        let reading = 0;
        let maxReading = 0;
        const running = { ...version, id: 's2', version: 2, datasets: [], task: { ...version.task, status: 'running', input_version: { ...version.task.input_version, structure_id: 's2' } } };
        vi.stubGlobal('fetch', vi.fn(async (url: string) => { reading++; maxReading = Math.max(maxReading, reading); await Promise.resolve(); reading--; return Response.json(url.includes('/rows?') ? rowPage() : { ...page, items: [running, version], total: 2, latest_version: 2 }); }));
        render(<StructureVersions projectId="p1" fileId="f1" filename="data.xlsx" active onUnavailable={() => { }}/>);
        await act(async () => { await vi.advanceTimersByTimeAsync(0); });
        fireEvent.click(screen.getByRole('button', { name: '结构版本 1 · 已完成' }));
        await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
        expect(screen.getByRole('button', { name: '结构版本 1 · 已完成' }).getAttribute('aria-pressed')).toBe('true');
        const fetch = vi.mocked(globalThis.fetch);
        const before = fetch.mock.calls.length;
        Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
        fireEvent(document, new Event('visibilitychange'));
        await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
        expect(fetch.mock.calls.length).toBe(before);
        expect(maxReading).toBe(1);
    }
    finally {
        Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
        vi.useRealTimers();
    }
});
it('ignores a late project response after switching to a different project', async () => {
    let done!: (response: Response) => void;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.includes('/p1/') ? await new Promise<Response>(resolve => { done = resolve; }) : Response.json({ items: [], total: 0, page: 1, page_size: 5, latest_version: 0 })));
    const view = render(<StructureVersions projectId="p1" fileId="f1" filename="data.xlsx" active onUnavailable={() => { }}/>);
    view.rerender(<StructureVersions projectId="p2" fileId="f2" filename="other.xlsx" active onUnavailable={() => { }}/>);
    await screen.findByText('尚未生成结构版本。');
    await act(async () => { done(Response.json(page)); });
    expect(screen.queryByText('结构版本 1 · 已完成')).toBeNull();
});
it('a missing dataset clears its cells but preserves other file content and does not revoke the project', async () => {
    const unavailable = vi.fn();
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.includes('/rows?') ? Response.json({ detail: { code: 'dataset_missing' } }, { status: 404 }) : Response.json(page)));
    render(<StructureVersions projectId="p1" fileId="f1" filename="data.xlsx" active onUnavailable={unavailable}/>);
    await screen.findByText('原始数据版本不存在或无权访问。');
    expect(unavailable).not.toHaveBeenCalled();
    expect(screen.queryByRole('link', { name: '下载完整 JSON' })).toBeNull();
    expect(screen.getByRole('button', { name: '结构版本 1 · 已完成' })).toBeTruthy();
});
