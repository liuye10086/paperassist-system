import type { DatasetAnalysisSource } from '../analysis/datasetSource'

export type ProfileBinding = Pick<DatasetAnalysisSource, 'kind' | 'dataset_id' | 'structure_id' | 'dataset_version' | 'file_id' | 'sheet_index' | 'sheet_name' | 'source_sha256' | 'parser_version'> & { source?: DatasetAnalysisSource }
export const issueKinds = ['missing', 'outlier', 'mixed_type', 'error', 'formula', 'time_candidate', 'time_invalid', 'time_ambiguous', 'numeric_precision', 'duplicate'] as const
export type IssueKind = typeof issueKinds[number]
export type FieldProfile = {
 column: number; letter: string; name: string; unit: { status: 'confirmed' | 'unconfirmed'; value: string | null }
 type_counts: Record<string, number>; missing_count: number; non_missing_count: number; distinct_count: number
 numeric: null | { status: 'ok' | 'unavailable'; n: number; mean: number | null; std: number | null; min: number | null; max: number | null; q1: number | null; median: number | null; q3: number | null; iqr: number | null; lower_fence: string | null; upper_fence: string | null; outlier_count: number; warnings: string[] }
 categories: null | { distinct_count: number; top: { kind: 'text' | 'boolean'; value: string | boolean; count: number }[]; other_count: number }
 temporal: { kind: 'date' | 'datetime' | 'time' | 'duration'; count: number; min: string; max: string }[]
 time_candidates: { valid_count: number; invalid_count: number; ambiguous_count: number }; issue_counts: Record<string, number>
}
export type Profile = { schema_version: 1; rules_version: 'excel_profile_v1'; source: DatasetAnalysisSource; filename: string; sheet_name: string; data_range: string | null; record_count: number; blank_row_count: number; duplicate_groups: number; duplicate_rows: number; duplicate_extra_rows: number; fields: FieldProfile[] }
export type IssueItem = { row: number; column: number | null; coordinate: string | null; kind: string | null; value: string | boolean | null; group_first_row: number | null; group_size: number | null }
export type IssuePage = { source: DatasetAnalysisSource; rules_version: 'excel_profile_v1'; kind: IssueKind; column: number | null; page: number; page_size: 20; total: number; items: IssueItem[] }
export type LocationRows = { start_row: number; has_more: boolean; rows: { row: number; cells: { row: number; column: number; coordinate: string; kind: string; value: string | boolean | null }[] }[] }
