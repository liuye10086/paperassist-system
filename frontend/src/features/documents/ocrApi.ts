export type OcrPolygon = [number, number][]
export type OcrText = {
 kind: 'ocr_text'; id: string; text: string; score: number; review_status: 'unreviewed'; polygon: OcrPolygon
 source: { page_number: number; polygon: OcrPolygon; coordinate_system: 'pdf_points_bottom_left' | 'image_pixels_top_left'; label: string }
}
export type OcrPage = {
 page_number: number; width: number; height: number; preview_image_id: string; rotation: number
 source_width: number; source_height: number; source_coordinate_system: 'pdf_points_bottom_left' | 'image_pixels_top_left'
 pixel_to_source: number[]; transforms: string[]; text_status: 'text' | 'no_text'; text_blocks: OcrText[]
 warnings: {code:string;message:string;count:number}[]
}
export type OcrPageResponse = {items: OcrPage[]; total: number; page: number; page_size: 1}
const record = (v: unknown): v is Record<string,unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
const number = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const positive = (v: unknown): v is number => number(v) && v > 0
const integer = (v: unknown): v is number => number(v) && Number.isSafeInteger(v) && v >= 0
const physicalPage = (v: unknown) => integer(v) && v >= 1 && v <= 100
const polygon = (v: unknown) => Array.isArray(v) && v.length === 4 && v.every(p => Array.isArray(p) && p.length === 2 && p.every(number))
const coordinates = (v: unknown) => v === 'pdf_points_bottom_left' || v === 'image_pixels_top_left'
export function isOcrPageResponse(v: unknown, page: number): v is OcrPageResponse {
 return record(v) && v.page === page && v.page_size === 1 && integer(v.total) && v.total >= 1 && v.total <= 10 && page <= v.total && Array.isArray(v.items) && v.items.length === 1 && v.items.every(p => record(p) && physicalPage(p.page_number) && integer(p.width) && positive(p.width) && integer(p.height) && positive(p.height) && typeof p.preview_image_id === 'string' && [0,90,180,270].includes(Number(p.rotation)) && positive(p.source_width) && positive(p.source_height) && coordinates(p.source_coordinate_system) && Array.isArray(p.pixel_to_source) && p.pixel_to_source.length === 6 && p.pixel_to_source.every(number) && Array.isArray(p.transforms) && p.transforms.every(x => typeof x === 'string') && ['text','no_text'].includes(String(p.text_status)) && Array.isArray(p.text_blocks) && p.text_blocks.length <= 20000 && p.text_blocks.every(b => record(b) && b.kind === 'ocr_text' && typeof b.id === 'string' && typeof b.text === 'string' && number(b.score) && b.score >= 0 && b.score <= 1 && b.review_status === 'unreviewed' && polygon(b.polygon) && record(b.source) && b.source.page_number === p.page_number && polygon(b.source.polygon) && coordinates(b.source.coordinate_system) && typeof b.source.label === 'string') && Array.isArray(p.warnings) && p.warnings.every(w => record(w) && typeof w.code === 'string' && typeof w.message === 'string' && integer(w.count)))
}
/** Physical pages are explicit, unique and bounded. Ranges are only entry shorthand. */
export function parseOcrPageSelection(input: string): number[] | null {
 const tokens = input.trim().split(/[\s,，;；]+/).filter(Boolean)
 if (!tokens.length) return null
 const pages: number[] = []
 for (const token of tokens) {
  const match = /^(\d+)(?:[-–—](\d+))?$/.exec(token)
  if (!match) return null
  const start = Number(match[1]), end = match[2] ? Number(match[2]) : start
  if (!physicalPage(start) || !physicalPage(end) || end < start || end - start >= 10) return null
  for (let page = start; page <= end; page++) pages.push(page)
  if (pages.length > 10) return null
 }
 return new Set(pages).size === pages.length ? pages.sort((a,b)=>a-b) : null
}
