import { lifecycleResponse } from '../files/lifecycleFixtures'
import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DocumentImage from './DocumentImage';
import DocumentVersions from './DocumentVersions';
const base = '/api/v1/projects/p/files/f/document-versions';
const version = { id: 'v1', file_id: 'f', version: 1, task_id: 't1', status: 'succeeded', created_at: '2026-10-12', completed_at: '2026-10-12', parser_version: 'openxml-docx-v1', summary: { counts: { paragraphs: 1, tables: 0, cells: 0, images: 0 }, warnings: [] }, error: null, download_url: base + '/v1/download', blocks_url: base + '/v1/blocks', styles: [], sections: [], images: [] };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
test('only PNG and JPEG may inline; all other MIME types explain download availability', () => {
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    render(<DocumentImage image={{ id: 'svg', mime: 'image/svg+xml', size_bytes: 10, inline_preview: true, download_url: 'https://external' }} url={base + '/v1/images/svg'} onUnavailable={() => { }}/>);
    expect(screen.getByText('此图片格式仅提供下载。')).toBeTruthy();
    expect(fetch).not.toHaveBeenCalled();
});
test('version reads preserve current content on error, keep original order and hide technical source IDs', async () => {
    const user = userEvent.setup();
    let broken = false;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
        if (url.includes('?page=') && !url.includes('/blocks'))
            return Response.json({ items: [version, { ...version, id: 'v2', version: 2, status: 'failed', error: { code: 'unknown', message: 'secret' } }], total: 2, page: 1, page_size: 5, latest_version: 2 });
        if (url.includes('/blocks'))
            return broken ? Response.json({ detail: { code: 'unknown' } }, { status: 500 }) : Response.json({ items: [{ kind: 'paragraph', id: 'technical-id', source: { label: '正文段落 1', part: 'word/document.xml', path: '/private/path' }, text: '<script>https://external.test</script>', heading_level: 1, style_id: null, properties: {}, runs: [], image_ids: [] }], total: 1, page: 1, page_size: 20 });
        return Response.json(version);
    }));
    render(<DocumentVersions projectId="p" fileId="f" filename="paper.docx" active onUnavailable={() => { }}/>);
    await user.click(await screen.findByRole('button', { name: 'Word 版本 v1 · 已完成' }));
    expect(await screen.findByText('<script>https://external.test</script>')).toBeTruthy();
    expect(screen.queryByText('technical-id')).toBeNull();
    expect(screen.queryByText('/private/path')).toBeNull();
    expect(document.querySelector('script')).toBeNull();
    expect(document.querySelector('a[href="https://external.test"]')).toBeNull();
    broken = true;
    await user.click(screen.getByRole('button', { name: '刷新 Word 版本' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText('<script>https://external.test</script>')).toBeTruthy();
});
test('known version conflict refreshes the latest revision and allows a new idempotent submission', async () => {
    const user = userEvent.setup();
    const posted: {
        key: string | null;
        version: number;
    }[] = [];
    let latest = 1;
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
        const impact = lifecycleResponse(_url); if (impact) return impact;
        if (init?.method === 'POST') {
            posted.push({ key: new Headers(init.headers).get('Idempotency-Key'), version: JSON.parse(init.body as string).expected_latest_version });
            if (posted.length === 1) {
                latest = 2;
                return Response.json({ detail: { code: 'document_version_conflict' } }, { status: 409 });
            }
            return Response.json({ ...version, id: 'v3', version: 3, status: 'queued' });
        }
        return Response.json({ items: [version], total: 1, page: 1, page_size: 5, latest_version: latest });
    }));
    render(<DocumentVersions projectId="p" fileId="f" filename="paper.docx" active onUnavailable={() => { }}/>);
    await screen.findByRole('button', { name: 'Word 版本 v1 · 已完成' });
    await user.click(screen.getByRole('button', { name: '重新解析 Word' }));
    await user.click(await screen.findByRole('button', {name:'确认并开始重解析'}));
    await screen.findByRole('alert');
    await user.click(screen.getByRole('button', { name: '刷新 Word 版本' }));
    await user.click(screen.getByRole('button', { name: '重新解析 Word' }));
    await user.click(await screen.findByRole('button', {name:'确认并开始重解析'}));
    expect(posted).toHaveLength(2);
    expect(posted[1].version).toBe(2);
    expect(posted[1].key).not.toBe(posted[0].key);
});
test('explicit properties display readable style names without leaking style IDs', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.includes('/blocks') ? Response.json({ items: [{ kind: 'paragraph', id: 'b1', source: { label: '正文段落 1' }, text: 'Safe paragraph', heading_level: null, style_id: 'secret-style-id', properties: { 'pStyle.val': 'secret-style-id', 'b.val': '1' }, runs: [], image_ids: [] }], total: 1, page: 1, page_size: 20 }) : url.includes('?') ? Response.json({ items: [version], total: 1, page: 1, page_size: 5, latest_version: 1 }) : Response.json({ ...version, styles: [{ id: 'secret-style-id', name: 'Readable style', type: 'paragraph', based_on: null, properties: { 'style.styleId': 'secret-style-id', 'rPr.b.val': 'true' } }] })));
    render(<DocumentVersions projectId="p" fileId="f" filename="paper.docx" active onUnavailable={() => { }}/>);
    await user.click(await screen.findByRole('button', { name: 'Word 版本 v1 · 已完成' }));
    await screen.findByText('Safe paragraph');
    expect(screen.queryAllByText('secret-style-id')).toHaveLength(0);
    expect(screen.getByText('段落样式：Readable style')).toBeTruthy();
    expect(screen.getAllByText('加粗')).toHaveLength(2);
});
test('switching file scope clears document content and ignores an old detail response', async () => {
    const user = userEvent.setup();
    let resolve!: (v: Response) => void;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/v1') ? new Promise<Response>(r => { resolve = r; }) : Response.json({ items: url.includes('/other/') ? [] : [version], total: url.includes('/other/') ? 0 : 1, page: 1, page_size: 5, latest_version: 1 })));
    const unavailable = () => { };
    const view = render(<DocumentVersions projectId="p" fileId="f" filename="paper.docx" active onUnavailable={unavailable}/>);
    await user.click(await screen.findByRole('button', { name: 'Word 版本 v1 · 已完成' }));
    view.rerender(<DocumentVersions projectId="p" fileId="other" filename="other.docx" active onUnavailable={unavailable}/>);
    resolve(Response.json(version));
    await new Promise(r => setTimeout(r, 20));
    expect(screen.queryByRole('heading', { name: 'Word 版本 v1' })).toBeNull();
});
test('authenticated image blobs are scoped to the selected version and URLs are revoked on switch and unmount', async () => {
    const { act, waitFor } = await import('@testing-library/react');
    const create = vi.fn(() => `blob:image-${create.mock.calls.length}`);
    const revoke = vi.fn();
    const NativeURL = URL;
    vi.stubGlobal('URL', class extends NativeURL {
        static createObjectURL = create;
        static revokeObjectURL = revoke;
    });
    let oldResolve!: (response: Response) => void;
    const fetch = vi.fn(async (url: string) => url.endsWith('/old') ? new Promise<Response>(r => { oldResolve = r; }) : new Response('png', { headers: { 'Content-Type': 'image/png' } }));
    vi.stubGlobal('fetch', fetch);
    const image = { id: 'i', mime: 'image/png', size_bytes: 3, inline_preview: true, download_url: 'https://external.test/track' };
    const unavailable = () => { };
    const view = render(<DocumentImage image={image} url={base + '/v1/images/old'} onUnavailable={unavailable}/>);
    view.rerender(<DocumentImage image={image} url={base + '/v2/images/new'} onUnavailable={unavailable}/>);
    expect(await screen.findByRole('img')).toBeTruthy();
    expect(screen.getByRole('img').getAttribute('src')).toBe('blob:image-1');
    expect(fetch.mock.calls.every(([url]) => url.startsWith('/api/v1/projects/'))).toBe(true);
    expect((fetch.mock.calls[1] as unknown as [
        string,
        RequestInit
    ])[1].credentials).toBe('same-origin');
    await act(async () => oldResolve(new Response('old', { headers: { 'Content-Type': 'image/png' } })));
    expect(create).toHaveBeenCalledTimes(1);
    view.rerender(<DocumentImage image={image} url={base + '/v3/images/third'} onUnavailable={unavailable}/>);
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
    expect(revoke).toHaveBeenCalledWith('blob:image-1');
    view.unmount();
    expect(revoke).toHaveBeenCalledWith('blob:image-2');
});
test('choosing a new version preserves the previous successful content until both metadata and blocks are available', async () => {
    const user = userEvent.setup();
    let next = false;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
        if (url.includes('/v2/blocks'))
            return Response.json({ detail: { code: 'unknown' } }, { status: 500 });
        if (url.includes('/blocks'))
            return Response.json({ items: [{ kind: 'paragraph', id: 'p', source: { label: '正文段落 1' }, text: 'Original content', style_id: null, heading_level: null, properties: {}, runs: [], image_ids: [] }], total: 1, page: 1, page_size: 20 });
        if (url.endsWith('/v2'))
            return Response.json({ ...version, id: 'v2', version: 2 });
        if (url.endsWith('/v1'))
            return Response.json(version);
        return Response.json({ items: [version, { ...version, id: 'v2', version: 2 }], total: 2, page: 1, page_size: 5, latest_version: 2 });
    }));
    render(<DocumentVersions projectId="p" fileId="f" filename="paper.docx" active onUnavailable={() => { }}/>);
    await user.click(await screen.findByRole('button', { name: 'Word 版本 v1 · 已完成' }));
    await screen.findByText('Original content');
    next = true;
    await user.click(screen.getByRole('button', { name: 'Word 版本 v2 · 已完成' }));
    await screen.findByRole('alert');
    expect(next).toBe(true);
    expect(screen.getByText('Original content')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Word 版本 v1' })).toBeTruthy();
});
test('table row pages keep merged anchors and readable cell coordinates without copying covered cells', async () => {
    const { default: DocumentBlock } = await import('./DocumentBlock');
    const user = userEvent.setup();
    const paragraph = (id: string, text: string) => ({ kind: 'paragraph' as const, id, source: { label: '正文段落 1' }, text, style_id: null, heading_level: null, properties: {}, runs: [], image_ids: [] });
    const table = { kind: 'table' as const, id: 'table', source: { label: '正文表格 1' }, rows: 21, columns: 2, style_id: null, properties: {}, cells: [{ row: 0, column: 0, row_span: 21, column_span: 1, source: { label: '正文表格 1，第 1 行第 1 列' }, blocks: [paragraph('merged', 'Merged cell')] }, ...Array.from({ length: 21 }, (_, row) => ({ row, column: 1, row_span: 1, column_span: 1, source: { label: `正文表格 1，第 ${row + 1} 行第 2 列` }, blocks: [paragraph(`row-${row}`, `Data row ${row + 1}`)] }))] };
    render(<DocumentBlock block={table} version={version as never} base={base} onUnavailable={() => { }}/>);
    expect(screen.getByRole('table').querySelectorAll('tr')).toHaveLength(20);
    expect(screen.getAllByText('Merged cell')).toHaveLength(1);
    expect(screen.queryByText('Data row 21')).toBeNull();
    expect(screen.getByText('Merged cell').closest('td')!.rowSpan).toBe(20);
    await user.click(screen.getByRole('button', { name: '下一页表格行' }));
    expect(screen.getByRole('table').querySelectorAll('tr')).toHaveLength(1);
    expect(screen.getByText('Data row 21')).toBeTruthy();
    expect(screen.getAllByText('Merged cell')).toHaveLength(1);
    expect(screen.getByText('正文表格 1，第 21 行第 2 列')).toBeTruthy();
});
test('a failed embedded image can retry independently and clears its error without replacing document content', async()=>{
 const user=userEvent.setup();const create=vi.fn(()=> 'blob:retried');const revoke=vi.fn();const NativeURL=URL;vi.stubGlobal('URL',class extends NativeURL {static createObjectURL=create;static revokeObjectURL=revoke})
 let imageCalls=0
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
 if(url.includes('/images/'))return ++imageCalls===1?new Response('',{status:500}):new Response('png',{headers:{'Content-Type':'image/png'}})
 if(url.includes('/blocks'))return Response.json({items:[{kind:'paragraph',id:'p',source:{label:'正文段落 1'},text:'Keep this content',style_id:null,heading_level:null,properties:{},runs:[],image_ids:['i']}],total:1,page:1,page_size:20})
 if(url.includes('?'))return Response.json({items:[version],total:1,page:1,page_size:5,latest_version:1})
 return Response.json({...version,images:[{id:'i',mime:'image/png',inline_preview:true,size_bytes:3,download_url:base+'/v1/images/i'}]})
 }))
 const view=render(<DocumentVersions projectId="p" fileId="f" filename="paper.docx" active onUnavailable={()=>{}}/> )
 await user.click(await screen.findByRole('button',{name:'Word 版本 v1 · 已完成'}));await screen.findByRole('alert')
 await user.click(screen.getByRole('button',{name:'重新读取图片'}));await screen.findByRole('img')
 expect(imageCalls).toBe(2);expect(screen.queryByRole('alert')).toBeNull();expect(screen.getByText('Keep this content')).toBeTruthy();expect(screen.getByRole('heading',{name:'Word 版本 v1'})).toBeTruthy()
 view.unmount();expect(revoke).toHaveBeenCalledWith('blob:retried')
})
test('omitted grid positions keep their columns and do not duplicate merged coverage',async()=>{
 const {default:DocumentBlock}=await import('./DocumentBlock')
 const cell=(row:number,column:number,row_span=1,column_span=1)=>({row,column,row_span,column_span,source:{label:`正文表格 1，第 ${row+1} 行第 ${column+1} 列`},blocks:[]})
 const table={kind:'table' as const,id:'sparse',source:{label:'正文表格 1'},rows:3,columns:3,style_id:null,properties:{},cells:[cell(0,0,2,1),cell(0,1,1,2),cell(1,2),cell(2,1)]}
 render(<DocumentBlock block={table} version={version as never} base={base} onUnavailable={()=>{}}/>)
 const rows=screen.getByRole('table').querySelectorAll('tr')
 expect(rows[1].querySelectorAll('td')).toHaveLength(2)
 expect(rows[1].querySelectorAll('td')[0].getAttribute('data-document-empty')).toBe('true')
 expect(rows[1].querySelectorAll('td')[1].textContent).toContain('第 2 行第 3 列')
 expect(rows[2].querySelectorAll('td')).toHaveLength(3)
 expect(screen.getAllByText('正文表格 1，第 1 行第 1 列')).toHaveLength(1)
})
