export type RawDatasetAnalysisSource = { kind: 'dataset_version'; schema_version: 1; dataset_id: string; structure_id: string; dataset_version: number; file_id: string; source_sha256: string; dataset_sha256: string; dataset_size_bytes: number; dataset_schema_version: 1; sheet_index: number; sheet_name: string; parser_version: string }
export type PreparedDatasetAnalysisSourceV1 = Omit<RawDatasetAnalysisSource, 'kind'> & { kind: 'prepared_dataset_version'; parent_dataset_id: string; parent_dataset_version: number; transform_version: 'excel_prepare_v1' }
export type PreparedDatasetAnalysisSourceV2 = Omit<PreparedDatasetAnalysisSourceV1, 'schema_version' | 'dataset_schema_version' | 'transform_version'> & { schema_version: 2; dataset_schema_version: 2; transform_version: 'excel_prepare_v2' }
export type PreparedDatasetAnalysisSourceV3 = Omit<PreparedDatasetAnalysisSourceV2, 'schema_version' | 'dataset_schema_version' | 'transform_version'> & { schema_version: 3; dataset_schema_version: 3; transform_version: 'excel_prepare_v3' }
export type PreparedDatasetAnalysisSource = PreparedDatasetAnalysisSourceV1 | PreparedDatasetAnalysisSourceV2 | PreparedDatasetAnalysisSourceV3
export type DatasetAnalysisSource = RawDatasetAnalysisSource | PreparedDatasetAnalysisSource
const keys = ['kind', 'schema_version', 'dataset_id', 'structure_id', 'dataset_version', 'file_id', 'source_sha256', 'dataset_sha256', 'dataset_size_bytes', 'dataset_schema_version', 'sheet_index', 'sheet_name', 'parser_version'] as const
export function isDatasetSource(value: unknown): value is DatasetAnalysisSource {
 if (!value || typeof value !== 'object' || Array.isArray(value)) return false
 const v = value as Record<string, unknown>
 const integer = (n: unknown, min: number) => typeof n === 'number' && Number.isSafeInteger(n) && n >= min
 const prepared = v.kind === 'prepared_dataset_version'
 const supported = prepared ? [1, 2, 3].includes(Number(v.schema_version)) && v.dataset_schema_version === v.schema_version && v.transform_version === `excel_prepare_v${v.schema_version}` : v.schema_version === 1 && v.dataset_schema_version === 1
 return Object.keys(v).length === keys.length + (prepared ? 3 : 0) && keys.every(k => Object.hasOwn(v, k)) && (v.kind === 'dataset_version' || prepared && typeof v.parent_dataset_id === 'string' && !!v.parent_dataset_id && integer(v.parent_dataset_version, 1)) && supported
  && ['dataset_id', 'structure_id', 'file_id', 'sheet_name', 'parser_version'].every(k => typeof v[k] === 'string' && (v[k] as string).length > 0)
  && ['source_sha256', 'dataset_sha256'].every(k => typeof v[k] === 'string' && /^[a-f0-9]{64}$/.test(v[k] as string))
  && integer(v.dataset_version, 1) && integer(v.dataset_size_bytes, 1) && integer(v.sheet_index, 0)
}
export function sameSource(a: DatasetAnalysisSource | null | undefined, b: DatasetAnalysisSource | null | undefined) {
 return a == null && b == null || isDatasetSource(a) && isDatasetSource(b) && keys.every(k => a[k] === b[k]) && (a.kind !== 'prepared_dataset_version' || b.kind === 'prepared_dataset_version' && a.parent_dataset_id === b.parent_dataset_id && a.parent_dataset_version === b.parent_dataset_version && a.transform_version === b.transform_version)
}
export function validOptionalSource(value: { source?: DatasetAnalysisSource; source_sha256?: string }, expected?: DatasetAnalysisSource) {
 return (!Object.hasOwn(value, 'source') || isDatasetSource(value.source) && value.source_sha256 === value.source.source_sha256) && sameSource(value.source, expected)
}

export function validAnalysisTaskSource(task: unknown, source: DatasetAnalysisSource | undefined, revision: number, language: 'zh-CN'|'en'='zh-CN') {
 if (!task || typeof task !== 'object' || Array.isArray(task)) return false
 const input = (task as { input_version?: unknown }).input_version
 if (!source) return !input || typeof input === 'object' && !Array.isArray(input) && !('source' in input) && !('kind' in input)
 if (!input || typeof input !== 'object' || Array.isArray(input)) return false
 const value = input as Record<string, unknown>
 return Object.keys(value).length === 4 && value.kind === 'dataset_analysis' && value.setup_revision === revision && value.output_language === language && sameSource(value.source as DatasetAnalysisSource, source)
}
