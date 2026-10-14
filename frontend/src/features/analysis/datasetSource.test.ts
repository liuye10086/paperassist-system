import { isDatasetSource, sameSource, validOptionalSource } from './datasetSource'
import { expect, test } from 'vitest'
import { isArtifactDisclosure } from '../../shared/api/artifactDisclosure'
import { isTask } from '../tasks/taskTypes'
import { taskFixture } from '../tasks/taskFixtures'
export const source = { kind: 'dataset_version', schema_version: 1, dataset_id: 'd1', structure_id: 's1', dataset_version: 1, file_id: 'f1', source_sha256: 'a'.repeat(64), dataset_sha256: 'b'.repeat(64), dataset_size_bytes: 100, dataset_schema_version: 1, sheet_index: 0, sheet_name: '数据 & 表', parser_version: 'structure-v1' }
test('accepts dataset analysis task input with full frozen source', () => {
 expect(isTask({ ...taskFixture, input_version: { kind: 'dataset_analysis', setup_revision: 1, output_language: 'zh-CN', source } }, 'p1')).toBe(true)
})
test('accepts disclosure v2 with readable source and rejects internal identifiers', () => {
 const disclosure = { version: 2, provider: 'openai', task_type: 'boxplot', source_digest: 'digest', has_saved_result: false, summary: { valid_count: 1, excluded_count: 0, group_count: 0 }, labels: [{ key: 'numeric_name', value: 'Value' }, { key: 'unit', value: '' }], source: { filename: '研究.xlsx', sheet_name: '数据 & 表', dataset_version: 1 } }
 expect(isArtifactDisclosure(disclosure, 'boxplot')).toBe(true)
 expect(isArtifactDisclosure({ ...disclosure, source: { ...disclosure.source, dataset_id: 'private' } }, 'boxplot')).toBe(false)
})

test('validates complete source strictly and compares every frozen field', () => {
 expect(isDatasetSource(source)).toBe(true)
 for (const key of Object.keys(source)) {
  const incomplete = { ...source } as Record<string, unknown>; delete incomplete[key]
  expect(isDatasetSource(incomplete)).toBe(false)
  expect(sameSource(source as never, { ...source, [key]: 'different' } as never)).toBe(false)
 }
 expect(isDatasetSource({ ...source, object_key: 'private' })).toBe(false)
 expect(isDatasetSource({ ...source, dataset_version: 0 })).toBe(false)
 expect(isDatasetSource({ ...source, dataset_sha256: 'bad' })).toBe(false)
})

test('rejects contradictory original file hash on a dataset artifact', () => {
 expect(validOptionalSource({ source: source as never, source_sha256: 'c'.repeat(64) } as never, source as never)).toBe(false)
})

test('prepared sources retain raw origin and compare parent version', () => {
 const prepared = { ...source, kind: 'prepared_dataset_version', parent_dataset_id: 'raw1', parent_dataset_version: 3, transform_version: 'excel_prepare_v1' }
 expect(isDatasetSource(prepared)).toBe(true)
 expect(sameSource(prepared as never, { ...prepared, parent_dataset_version: 4 } as never)).toBe(false)
 expect(isDatasetSource({ ...prepared, transform_version: 'wrong' })).toBe(false)
 expect(isTask({ ...taskFixture, task_type: 'prepare_dataset', phase: 'plan', input_version: { kind: 'dataset_preparation', source, workflow_version: 'dataset_preparation_v1' } }, 'p1')).toBe(true)
})

test('disclosure v3 identifies prepared and parent raw versions without private ids', () => {
 const disclosure = { version: 3, provider: 'openai', task_type: 'boxplot', source_digest: 'digest', has_saved_result: false, summary: { valid_count: 1, excluded_count: 0, group_count: 0 }, labels: [{ key: 'numeric_name', value: 'Value' }, { key: 'unit', value: '' }], source: { filename: '研究.xlsx', sheet_name: '数据', dataset_version: 2, parent_dataset_version: 3, dataset_kind: 'prepared' } }
 expect(isArtifactDisclosure(disclosure, 'boxplot')).toBe(true)
 expect(isArtifactDisclosure({ ...disclosure, source: { ...disclosure.source, parent_dataset_id: 'secret' } }, 'boxplot')).toBe(false)
})
