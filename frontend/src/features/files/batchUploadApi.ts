import { fileRequest } from './fileLibraryApi';
import { isTask, type TaskView } from '../tasks/taskTypes';
export type BatchItem = {
    id: string;
    ordinal: number;
    filename: string;
    size_bytes: number;
    status: 'pending' | 'rejected' | 'queued' | 'parsing' | 'parsed' | 'failed';
    file_id: string | null;
    task: TaskView | null;
    error: {
        code: string;
        message: string;
        params?: Record<string, unknown>;
    } | null;
};
export type UploadBatch = {
    id: string;
    project_id: string;
    created_at: string;
    revision: number;
    items: BatchItem[];
};
export type BatchPage = {
    items: UploadBatch[];
    total: number;
    page: number;
    page_size: number;
};
export function validateSelection(files: File[]) {
    return files.length > 10 ? '每批最多选择 10 个文件。' : files.length === 0 ? '请选择 Excel、Word、PDF 或 PNG/JPEG 图片。' : null;
}
export function validateFile(file: File) {
    return !/^.+\.(xlsx|docx|pdf|png|jpe?g)$/i.test(file.name) ? '仅支持 .xlsx、.docx、.pdf、.png、.jpg 或 .jpeg 文件。' : file.size === 0 ? '文件为空。' : file.size > 10 * 1024 * 1024 ? '单文件不能超过 10 MiB。' : null;
}
export function mergeBatch<T extends {
    id: string;
    revision: number;
}>(incoming: T, current?: T): T {
    return current?.id === incoming.id && current.revision > incoming.revision ? current : incoming;
}
export async function uploadQueue<T>(items: T[], signal: AbortSignal, upload: (item: T) => Promise<void>) {
    let next = 0;
    await Promise.all([0, 1].map(async () => {
        while (!signal.aborted && next < items.length) {
            const item = items[next++];
            try {
                await upload(item);
            }
            catch { /* One failure must not stop independent items. */ }
        }
    }));
}
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
export function isBatch(value: unknown, projectId: string): value is UploadBatch {
    if (!record(value) || typeof value.id !== 'string' || value.project_id !== projectId || typeof value.created_at !== 'string' || !Number.isFinite(Date.parse(value.created_at)) || !Number.isSafeInteger(value.revision) || Number(value.revision) < 1 || !Array.isArray(value.items) || value.items.length < 1 || value.items.length > 10)
        return false;
    return value.items.every((item, index) => record(item) && typeof item.id === 'string' && Number.isSafeInteger(item.ordinal) && item.ordinal === index && typeof item.filename === 'string' && Number.isSafeInteger(item.size_bytes) && Number(item.size_bytes) >= 0 && ['pending', 'rejected', 'queued', 'parsing', 'parsed', 'failed'].includes(String(item.status)) && (item.file_id === null || typeof item.file_id === 'string') && (item.task === null || isTask(item.task, projectId) && item.task.task_type === 'parse_file') && (item.error === null || record(item.error) && typeof item.error.code === 'string')) && new Set(value.items.map(item => item.id)).size === value.items.length;
}
export async function batchRequest<T>(url: string, controller: AbortController, onUnavailable: () => void, valid: (v: unknown) => v is T, init?: RequestInit): Promise<T> {
    const timer = window.setTimeout(() => controller.abort(), 15000);
    try {
        const result = await fileRequest<unknown>(url, controller.signal, onUnavailable, init);
        if (!valid(result))
            throw new Error('批次状态读取失败，请重试。');
        return result;
    }
    finally {
        window.clearTimeout(timer);
    }
}
