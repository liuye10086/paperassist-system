import { expect, test } from 'vitest';
import { isVersion } from './documentApi';
const version = { id: 'v1', file_id: 'f', version: 1, task_id: 't1', status: 'succeeded', created_at: '2026-10-12', completed_at: '2026-10-12', parser_version: 'openxml-docx-v1', summary: { counts: { paragraphs: 1, tables: 0, cells: 0, images: 0 }, warnings: [] }, error: null, download_url: '/download', blocks_url: '/blocks' };
test('invalid successful summaries are rejected before a preview replaces existing content', () => {
    expect(isVersion(version, 'f')).toBe(true);
    expect(isVersion({ ...version, summary: { counts: null, warnings: [] } }, 'f')).toBe(false);
    expect(isVersion({ ...version, summary: { counts: { ...version.summary.counts, images: -1 }, warnings: [] } }, 'f')).toBe(false);
    expect(isVersion({ ...version, styles: [{ id: 's', name: 'style', properties: null }] }, 'f')).toBe(false);
});
test('explicit Word and OCR projections accept their own contracts and reject an unknown kind',()=>{
 expect(isVersion({...version,kind:'docx_document'},'f')).toBe(true)
 const ocr={...version,kind:'ocr_document',pages_url:'/pages',selected_pages:[3,12],source_pages:12,summary:{counts:{pages:2,text_blocks:1,images:2,pages_without_text:1},warnings:[]}}
 expect(isVersion(ocr,'f')).toBe(true)
 expect(isVersion({...ocr,kind:'unknown'},'f')).toBe(false)
 expect(isVersion({...ocr,selected_pages:[3,3]},'f')).toBe(false)
 expect(isVersion({...ocr,summary:{counts:{...ocr.summary.counts,images:-1},warnings:[]}},'f')).toBe(false)
})
test('block pages reject malformed nested table cells and preserve valid merged anchors', async () => {
    const { isBlockPage } = await import('./documentApi');
    const paragraph = { kind: 'paragraph', id: 'p1', source: { label: '段落 1' }, text: 'Cell content', style_id: null, heading_level: null, properties: {}, runs: [], image_ids: [] };
    const table = { kind: 'table', id: 't1', source: { label: '表格 1' }, rows: 2, columns: 2, style_id: null, properties: {}, cells: [{ row: 0, column: 0, row_span: 2, column_span: 2, source: { label: '单元格' }, blocks: [paragraph] }] };
    const page = { items: [table], total: 1, page: 1, page_size: 20 };
    expect(isBlockPage(page, 1)).toBe(true);
    expect(isBlockPage({ ...page, items: [{ ...table, cells: [{ ...table.cells[0], blocks: [{ ...paragraph, text: null }] }] }] }, 1)).toBe(false);
    expect(isBlockPage({ ...page, items: [{ ...table, cells: [{ ...table.cells[0], row_span: 3 }] }] }, 1)).toBe(false);
});
test('document reads time out even when a transport ignores abort', async () => {
    const { vi } = await import('vitest');
    const { documentRequest } = await import('./documentApi');
    vi.useFakeTimers();
    vi.stubGlobal('fetch', () => new Promise(() => { }));
    try {
        const pending = documentRequest('/api/v1/projects/p/files/f/document-versions', new AbortController().signal, () => { }, (v): v is object => typeof v === 'object');
        const rejected = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
        await vi.advanceTimersByTimeAsync(15000);
        await rejected;
    }
    finally {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    }
});
