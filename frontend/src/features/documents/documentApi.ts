import { fileRequest } from '../files/fileLibraryApi';
export type Source = {
    label: string;
};
export type Paragraph = {
    kind: 'paragraph';
    id: string;
    source: Source;
    text: string;
    style_id: string | null;
    heading_level: number | null;
    properties: Record<string, string>;
    runs: {
        text: string;
        style_id: string | null;
        properties: Record<string, string>;
    }[];
    image_ids: string[];
};
export type Table = {
    kind: 'table';
    id: string;
    source: Source;
    rows: number;
    columns: number;
    style_id: string | null;
    properties: Record<string, string>;
    cells: {
        row: number;
        column: number;
        row_span: number;
        column_span: number;
        source: Source;
        blocks: Block[];
    }[];
};
export type Block = Paragraph | Table;
export type Style = {
    id: string;
    name: string;
    type: string;
    based_on: string | null;
    properties: Record<string, string>;
};
export type ImageMetadata = {
    id: string;
    mime: string;
    size_bytes: number;
    inline_preview: boolean;
    download_url: string;
};
export type DocumentVersion = {
    kind?: 'docx_document' | 'pdf_document' | 'ocr_document';
    selected_pages?: number[];
    source_pages?: number | null;
    source_type?: 'pdf' | 'png' | 'jpeg';
    pages_url?: string | null;
    id: string;
    file_id: string;
    version: number;
    task_id: string;
    status: 'queued' | 'running' | 'succeeded' | 'failed';
    created_at: string;
    completed_at: string | null;
    parser_version: string;
    summary: null | {
        counts: {
            paragraphs?: number;
            pages?: number;
            text_blocks?: number;
            pages_without_text?: number;
            tables?: number;
            cells?: number;
            images?: number;
        };
        warnings: {
            code: string;
            message: string;
            count: number;
        }[];
    };
    error: null | {
        code: string;
        message: string;
    };
    download_url: string | null;
    blocks_url?: string | null;
    styles?: Style[];
    sections?: {
        source: Source;
        properties: Record<string, string>;
    }[];
    images?: ImageMetadata[];
};
export type DocumentPage = {
    items: DocumentVersion[];
    total: number;
    page: number;
    page_size: 5;
    latest_version: number;
};
export type BlockPage = {
    items: Block[];
    total: number;
    page: number;
    page_size: 20;
};
export const documentBase = (projectId: string, fileId: string) => `/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}/document-versions`;
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string';
const integer = (v: unknown) => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0;
const properties = (v: unknown) => record(v) && Object.values(v).every(text);
const source = (v: unknown) => record(v) && text(v.label);
export function isVersion(v: unknown, fileId: string): v is DocumentVersion {
    if (!record(v) || !(v.kind === undefined || ['docx_document','pdf_document','ocr_document'].includes(String(v.kind))) || !text(v.id) || !v.id || v.file_id !== fileId || !integer(v.version) || Number(v.version) < 1 || !['queued', 'running', 'succeeded', 'failed'].includes(String(v.status)) || !text(v.task_id) || !text(v.parser_version) || !text(v.created_at) || !Number.isFinite(Date.parse(v.created_at)) || !(v.completed_at === null || text(v.completed_at)) || !(v.error === null || record(v.error) && text(v.error.code) && text(v.error.message)) || !(v.download_url === null || text(v.download_url)) || !(['pdf_document','ocr_document'].includes(String(v.kind)) ? v.pages_url === null || text(v.pages_url) : v.blocks_url === null || text(v.blocks_url)))
        return false;
    if (v.summary !== null && (!record(v.summary) || !record(v.summary.counts) || !(v.kind === 'ocr_document' ? ['pages','text_blocks','images','pages_without_text'] : v.kind === 'pdf_document' ? ['pages', 'text_blocks', 'tables', 'cells', 'pages_without_text'] : ['paragraphs', 'tables', 'cells', 'images']).every(key => integer((v.summary as {
        counts: Record<string, unknown>;
    }).counts[key])) || !Array.isArray(v.summary.warnings) || !v.summary.warnings.every(w => record(w) && text(w.code) && text(w.message) && integer(w.count))))
        return false;
    if (v.status === 'succeeded' && !v.summary)
        return false;
    if (v.kind === 'ocr_document' && (!Array.isArray(v.selected_pages) || v.selected_pages.length < 1 || v.selected_pages.length > 10 || !v.selected_pages.every(p => integer(p) && Number(p)>=1 && Number(p)<=100) || new Set(v.selected_pages).size !== v.selected_pages.length)) return false;
    if (v.source_pages !== undefined && v.source_pages !== null && (!integer(v.source_pages) || Number(v.source_pages)<1 || Number(v.source_pages)>100)) return false;
    if (v.styles !== undefined && (!Array.isArray(v.styles) || !v.styles.every(s => record(s) && text(s.id) && text(s.name) && text(s.type) && (s.based_on === null || text(s.based_on)) && properties(s.properties))))
        return false;
    if (v.sections !== undefined && (!Array.isArray(v.sections) || !v.sections.every(s => record(s) && source(s.source) && properties(s.properties))))
        return false;
    if (v.images !== undefined && (!Array.isArray(v.images) || !v.images.every(i => record(i) && text(i.id) && text(i.mime) && integer(i.size_bytes) && typeof i.inline_preview === 'boolean' && text(i.download_url))))
        return false;
    return true;
}
export async function documentRequest<T>(url: string, signal: AbortSignal, onUnavailable: () => void, valid: (x: unknown) => x is T, init?: RequestInit): Promise<T> {
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (signal.aborted)
        abort();
    else
        signal.addEventListener('abort', abort, { once: true });
    const timer = window.setTimeout(abort, 15000);
    try {
        const result = await fileRequest<unknown>(url, controller.signal, onUnavailable, init);
        if (!valid(result))
            throw new Error('文档版本读取失败，请重试。');
        return result;
    }
    finally {
        window.clearTimeout(timer);
        signal.removeEventListener('abort', abort);
    }
}
function isBlock(value: unknown, depth = 0): value is Block {
    if (depth > 20 || !record(value) || !text(value.id) || !source(value.source) || !(value.style_id === null || text(value.style_id)) || !properties(value.properties))
        return false;
    if (value.kind === 'paragraph')
        return text(value.text) && (value.heading_level === null || integer(value.heading_level)) && Array.isArray(value.image_ids) && value.image_ids.every(text) && Array.isArray(value.runs) && value.runs.every(run => record(run) && text(run.text) && (run.style_id === null || text(run.style_id)) && properties(run.properties));
    if (value.kind !== 'table' || !integer(value.rows) || !integer(value.columns) || !Array.isArray(value.cells))
        return false;
    return value.cells.every(cell => record(cell) && integer(cell.row) && integer(cell.column) && integer(cell.row_span) && Number(cell.row_span) > 0 && integer(cell.column_span) && Number(cell.column_span) > 0 && Number(cell.row) + Number(cell.row_span) <= Number(value.rows) && Number(cell.column) + Number(cell.column_span) <= Number(value.columns) && source(cell.source) && Array.isArray(cell.blocks) && cell.blocks.every(block => isBlock(block, depth + 1)));
}
export function isBlockPage(v: unknown, page: number): v is BlockPage {
    return record(v) && Array.isArray(v.items) && v.items.length <= 20 && v.items.every(b => isBlock(b)) && v.page === page && v.page_size === 20 && integer(v.total) && Number(v.total) >= v.items.length;
}
