import { expect, test } from 'vitest'
import { isDatasetSource, sameSource } from '../analysis/datasetSource'
import { isTask } from '../tasks/taskTypes'
import { taskFixture } from '../tasks/taskFixtures'

const raw = { kind: 'dataset_version', schema_version: 1, dataset_id: 'raw', structure_id: 'structure', dataset_version: 1, file_id: 'file', source_sha256: 'a'.repeat(64), dataset_sha256: 'b'.repeat(64), dataset_size_bytes: 123, dataset_schema_version: 1, sheet_index: 0, sheet_name: 'Data', parser_version: 'excel-v1' } as const
const v1 = { ...raw, kind: 'prepared_dataset_version', dataset_id: 'prepared-1', parent_dataset_id: raw.dataset_id, parent_dataset_version: 1, transform_version: 'excel_prepare_v1' } as const
const v2 = { ...v1, dataset_id: 'prepared-2', schema_version: 2, dataset_schema_version: 2, transform_version: 'excel_prepare_v2' } as const

test('v2 prepared sources are distinct while v1 source validation remains exact', () => {
 expect(isDatasetSource(raw)).toBe(true)
 expect(isDatasetSource(v1)).toBe(true)
 expect(isDatasetSource(v2)).toBe(true)
 expect(sameSource(v2, { ...v2 })).toBe(true)
 expect(sameSource(v1, v2)).toBe(false)
 for (const invalid of [{ ...raw, schema_version: 2 }, { ...v1, dataset_schema_version: 2 }, { ...v2, transform_version: 'excel_prepare_v1' }, { ...v1, base_source: raw }, { ...v2, base_source: v1 }]) expect(isDatasetSource(invalid)).toBe(false)
})

test('quality tasks use frozen prepared sources and do not loosen v1 raw task validation', () => {
 const make = (source: unknown, workflow_version: string) => ({ ...taskFixture, task_type: 'prepare_dataset', input_version: { kind: 'dataset_preparation', source, workflow_version } })
 expect(isTask(make(v1, 'dataset_preparation_v2'), 'p1')).toBe(true)
 expect(isTask(make(v2, 'dataset_preparation_v2'), 'p1')).toBe(true)
 expect(isTask(make(raw, 'dataset_preparation_v1'), 'p1')).toBe(true)
 expect(isTask(make(v1, 'dataset_preparation_v1'), 'p1')).toBe(false)
 expect(isTask(make(raw, 'dataset_preparation_v2'), 'p1')).toBe(false)
})
