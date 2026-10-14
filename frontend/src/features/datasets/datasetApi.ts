import { apiFetch } from '../../shared/api/client';
import { apiError } from '../../shared/i18n';
import { isTask, type TaskView } from '../tasks/taskTypes';
export type StructureCell = {
    row: number;
    column: number;
    coordinate: string;
    kind: string;
    value: string | boolean | null;
    raw_type: string | null;
    raw_value: string | null;
    number_format: string;
    formula: null | {
        text: string | null;
        attributes: Record<string, string>;
        cache_state: string;
        cached_type: string | null;
        cached_value: string | null;
        cache_validity: 'unverified';
    };
};
export type DatasetSummary = {
    id: string;
    file_id: string;
    structure_id: string;
    version: number;
    parent_id: string | null;
    created_at: string;
    epoch: '1900' | '1904';
    sheet_index: number;
    sheet_name: string;
    state: string;
    row_count: number;
    column_count: number;
    nonempty_row_count: number;
    nonempty_data_row_count: number;
    stored_range: string | null;
    content_range: string | null;
    merged_ranges: string[];
    fields: {
        column: number;
        letter: string;
        header_value: string | boolean | null;
        observed_types: string[];
        unit: {
            status: 'unconfirmed';
            value: null;
        };
    }[];
    warnings: string[];
};
export type StructureVersion = {
    id: string;
    file_id: string;
    version: number;
    parent_id: string | null;
    created_at: string;
    completed_at: string | null;
    task: TaskView;
    datasets: DatasetSummary[];
};
export type StructurePage = {
    items: StructureVersion[];
    total: number;
    page: number;
    page_size: 5;
    latest_version: number;
};
export type RowPage = {
    dataset: DatasetSummary;
    start_row: number;
    limit: 20;
    total_rows: number;
    has_more: boolean;
    rows: {
        row: number;
        cells: StructureCell[];
    }[];
};
export class DatasetRequestError extends Error {
    status: number;
    constructor(message: string, status: number) { super(message); this.status = status; }
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const integer = (v: unknown, min = 0): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= min;
const text = (v: unknown): v is string => typeof v === 'string';
const nullableText = (v: unknown) => v === null || text(v);
const date = (v: unknown) => text(v) && Number.isFinite(Date.parse(v));
const kinds = ['blank', 'text', 'number', 'boolean', 'date', 'datetime', 'time', 'duration', 'error', 'formula'];
const value = (v: unknown) => v === null || text(v) || typeof v === 'boolean';
function columnLetter(column: number) {
    let result = '';
    for (let n = column; n > 0; n = Math.floor((n - 1) / 26))
        result = String.fromCharCode(65 + (n - 1) % 26) + result;
    return result;
}
export function isDataset(v: unknown, file: string, structure?: string): v is DatasetSummary {
    if (!object(v) || !text(v.id) || !v.id || v.file_id !== file || !text(v.structure_id) || (structure && v.structure_id !== structure)
        || !integer(v.version, 1) || !nullableText(v.parent_id) || !date(v.created_at) || !['1900', '1904'].includes(String(v.epoch))
        || !integer(v.sheet_index) || v.sheet_index >= 50 || !text(v.sheet_name) || !['visible', 'hidden', 'veryHidden'].includes(String(v.state))
        || !integer(v.row_count) || v.row_count > 100000 || !integer(v.column_count) || v.column_count > 256
        || !integer(v.nonempty_row_count) || v.nonempty_row_count > v.row_count || !integer(v.nonempty_data_row_count) || v.nonempty_data_row_count > v.nonempty_row_count
        || !nullableText(v.stored_range) || !nullableText(v.content_range) || !Array.isArray(v.merged_ranges) || !v.merged_ranges.every(text)
        || !Array.isArray(v.fields) || v.fields.length > v.column_count || !Array.isArray(v.warnings) || !v.warnings.every(text))
        return false;
    return v.fields.every(f => object(f) && integer(f.column, 1) && f.column <= Number(v.column_count)
        && f.letter === columnLetter(f.column) && value(f.header_value) && Array.isArray(f.observed_types)
        && f.observed_types.every(k => kinds.includes(String(k))) && object(f.unit) && f.unit.status === 'unconfirmed' && f.unit.value === null)
        && new Set(v.fields.map(f => f.column)).size === v.fields.length;
}
export function isStructure(v: unknown, project: string, file: string): v is StructureVersion {
    return object(v) && text(v.id) && !!v.id && v.file_id === file && integer(v.version, 1) && nullableText(v.parent_id)
        && date(v.created_at) && (v.completed_at === null || date(v.completed_at))
        && isTask(v.task, project) && v.task.task_type === 'extract_dataset' && v.task.input_version.kind === 'excel_structure'
        && v.task.input_version.structure_id === v.id && Array.isArray(v.datasets) && v.datasets.length <= 50
        && v.datasets.every(d => isDataset(d, file, String(v.id)) && d.version === v.version)
        && new Set(v.datasets.map(d => d.id)).size === v.datasets.length
        && new Set(v.datasets.map(d => d.sheet_index)).size === v.datasets.length
        && (v.task.status === 'succeeded' || v.datasets.length === 0);
}
export function isStructurePage(v: unknown, project: string, file: string, page: number): v is StructurePage {
    return object(v) && v.page === page && v.page_size === 5 && integer(v.total) && integer(v.latest_version)
        && Array.isArray(v.items) && v.items.length <= 5 && v.items.length <= v.total
        && v.items.every(x => isStructure(x, project, file) && x.version <= Number(v.latest_version))
        && new Set(v.items.map(x => x.id)).size === v.items.length && new Set(v.items.map(x => x.version)).size === v.items.length;
}
function isCell(c: unknown, row: number, columns: number): c is StructureCell {
    if (!object(c) || c.row !== row || !integer(c.column, 1) || c.column > columns
        || c.coordinate !== `${columnLetter(c.column)}${row}` || !kinds.includes(String(c.kind)) || !value(c.value)
        || !nullableText(c.raw_type) || !nullableText(c.raw_value) || !text(c.number_format))
        return false;
    if (c.kind !== 'formula')
        return c.formula === null;
    const f = c.formula;
    return object(f) && nullableText(f.text) && object(f.attributes) && Object.values(f.attributes).every(text)
        && ['missing', 'empty', 'present'].includes(String(f.cache_state)) && nullableText(f.cached_type) && nullableText(f.cached_value) && f.cache_validity === 'unverified';
}
export function isRows(v: unknown, d: DatasetSummary, start: number): v is RowPage {
    if (!object(v) || !isDataset(v.dataset, d.file_id, d.structure_id) || v.dataset.id !== d.id || v.dataset.version !== d.version
        || v.start_row !== start || v.limit !== 20 || v.total_rows !== d.row_count || typeof v.has_more !== 'boolean'
        || !Array.isArray(v.rows) || v.rows.length !== Math.max(0, Math.min(20, d.row_count - start + 1))
        || v.has_more !== (start + 19 < d.row_count))
        return false;
    return v.rows.every((r, index) => object(r) && r.row === start + index && Array.isArray(r.cells)
        && r.cells.length <= d.column_count && r.cells.every(c => isCell(c, start + index, d.column_count))
        && new Set(r.cells.map(c => c.column)).size === r.cells.length);
}
export async function datasetRequest<T>(url: string, controller: AbortController, valid: (v: unknown) => v is T, onUnavailable: () => void, init?: RequestInit): Promise<T> {
    let timer = 0;
    let abort: () => void = () => { };
    try {
        return await Promise.race([(async () => { const response = await apiFetch(url, { ...init, signal: controller.signal }); const value: unknown = await response.json().catch(() => null); if (controller.signal.aborted)
                throw new DOMException('aborted', 'AbortError'); if ([401, 403].includes(response.status) || (response.status === 404 && object(value) && object(value.detail) && ['project_not_found', 'file_not_found'].includes(String(value.detail.code)))) {
                onUnavailable();
                throw new DatasetRequestError('结构来源不可用，请重新选择文件。', response.status);
            } if (!response.ok)
                throw new DatasetRequestError(apiError(value, '结构版本请求失败，请重试。'), response.status); if (!valid(value))
                throw new Error('结构版本请求失败，请重试。'); return value; })(), new Promise<never>((_, reject) => { abort = () => reject(new DOMException('aborted', 'AbortError')); controller.signal.addEventListener('abort', abort, { once: true }); timer = window.setTimeout(() => { controller.abort(); }, 15000); if (controller.signal.aborted)
                abort(); })]);
    }
    finally {
        window.clearTimeout(timer);
        controller.signal.removeEventListener('abort', abort);
    }
}
