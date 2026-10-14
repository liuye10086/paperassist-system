import { expect, test } from 'vitest'
import { source, binding, profile, issue, rowResponse, preparedSource } from './profileFixtures'
import { isProfile, isIssuePage, isLocationRows } from './profileApi'

test('validates the selected source and rejects every stale identity member', () => {
 expect(isProfile(profile, binding)).toBe(true)
 for (const [key, value] of Object.entries({ kind: 'prepared_dataset_version', dataset_id: 'other', structure_id: 'other', dataset_version: 2, file_id: 'other', source_sha256: 'c'.repeat(64), dataset_sha256: 'c'.repeat(64), dataset_size_bytes: 101, sheet_index: 1, sheet_name: 'Other', parser_version: 'other' })) expect(isProfile({ ...profile, source: { ...source, [key]: value } }, binding), key).toBe(false)
})
test('rejects non-finite metrics, unknown warning codes and mismatched issue query', () => {
 const field = profile.fields[0]
 for (const change of [{ mean: Infinity }, { std: NaN }, { warnings: ['server_stacktrace'] }]) expect(isProfile({ ...profile, fields: [{ ...field, numeric: { ...field.numeric, ...change } }] }, binding)).toBe(false)
 const page = { source, rules_version: 'excel_profile_v1', kind: 'outlier', column: 3, page: 1, page_size: 20, total: 1, items: [issue] }
 expect(isIssuePage(page, source, 'outlier', 3, 1)).toBe(true)
 for (const change of [{ source: { ...source, dataset_sha256: 'c'.repeat(64) } }, { kind: 'missing' }, { column: 4 }, { page: 2 }, { page_size: 5 }, { items: [{ ...issue, coordinate: 'C28' }] }]) expect(isIssuePage({ ...page, ...change }, source, 'outlier', 3, 1)).toBe(false)
})
test('rejects incomplete prepared row pages and inconsistent original coordinates or page metadata', () => {
 const page = rowResponse(25, true)
 expect(isLocationRows(page, preparedSource, 25, 27, profile.fields)).toBe(true)
 for (const change of [{ rows: page.rows.slice(0, 3) }, { total_rows: 999 }, { has_more: false }, { start_row: 21 }, { dataset: { ...page.dataset, source: { ...preparedSource, dataset_sha256: 'c'.repeat(64) } } }, { rows: page.rows.map((row, i) => i === 2 ? { ...row, cells: [{ ...row.cells[0], coordinate: 'C99' }] } : row) }]) expect(isLocationRows({ ...page, ...change }, preparedSource, 25, 27, profile.fields)).toBe(false)
})
