export type PdfSource = { page_number: number; bbox: number[]; label: string }
export type PdfText = { kind: 'text'; id: string; text: string; source: PdfSource }
export type PdfTable = { kind: 'table'; id: string; source: PdfSource; rows: number; columns: number; candidate: true; cells: { row: number; column: number; text: string | null; bbox: number[] | null }[] }
export type PdfPage = { page_number: number; width: number; height: number; rotation: number; bbox: number[]; text_status: 'text' | 'no_extractable_text'; text_blocks: PdfText[]; tables: PdfTable[]; warnings: {code:string;message:string;count:number}[] }
export type PdfPageResponse = { items: PdfPage[]; total: number; page: number; page_size: 1 }
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
const text = (v: unknown) => typeof v === 'string'
const integer = (v: unknown) => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0
const bbox = (v: unknown) => Array.isArray(v) && v.length === 4 && v.every(x => typeof x === 'number' && Number.isFinite(x))
const source = (v: unknown) => record(v) && integer(v.page_number) && Number(v.page_number)>0 && bbox(v.bbox) && text(v.label)
export function isPdfPageResponse(v: unknown, page: number): v is PdfPageResponse {
 return record(v) && v.page === page && v.page_size === 1 && integer(v.total) && Array.isArray(v.items) && v.items.length <= 1 && v.items.every(p => record(p) && p.page_number === page && typeof p.width === 'number' && typeof p.height === 'number' && integer(p.rotation) && bbox(p.bbox) && ['text','no_extractable_text'].includes(String(p.text_status)) && Array.isArray(p.text_blocks) && p.text_blocks.every(b => record(b) && b.kind === 'text' && text(b.id) && text(b.text) && source(b.source)) && Array.isArray(p.tables) && p.tables.every(t => record(t) && t.kind === 'table' && text(t.id) && source(t.source) && integer(t.rows) && integer(t.columns) && t.candidate === true && Array.isArray(t.cells) && t.cells.every(c => record(c) && integer(c.row) && Number(c.row)>0 && Number(c.row)<=Number(t.rows) && integer(c.column) && Number(c.column)>0 && Number(c.column)<=Number(t.columns) && (c.text === null || text(c.text)) && (c.bbox === null || bbox(c.bbox)))) && Array.isArray(p.warnings) && p.warnings.every(w => record(w) && text(w.code) && text(w.message) && integer(w.count)))
}
