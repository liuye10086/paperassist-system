import { expect, test } from 'vitest'
import { isLocationRows } from '../datasetProfile/profileApi'
import { qualitySource, qualityVersion } from './batch07Fixtures'

test('sparse prepared locations preserve source coordinates and active counts', () => {
 const response = { dataset: { ...qualityVersion, summary: { ...qualityVersion.summary, retained_record_count: 3, manual_excluded_row_count: 41, cumulative_excluded_row_count: 42, impact_count: 85, after_quality: { ...qualityVersion.summary.after_quality, record_count: 3 } } }, start_row: 2, limit: 20, total_rows: 3, has_more: false, next_start_row: null, rows: [2, 22, 46].map(row => ({ row, cells: [{ row, column: 1, coordinate: `A${row}`, kind: 'number', value: '1' }] })) }
 expect(isLocationRows(response, qualitySource, 2, 22, [{ column: 1 }] as never)).toBe(true)
 expect(isLocationRows({ ...response, rows: [...response.rows].reverse() }, qualitySource, 2, 22, [{ column: 1 }] as never)).toBe(false)
 expect(isLocationRows({ ...response, total_rows: 45 }, qualitySource, 2, 22, [{ column: 1 }] as never)).toBe(false)
 expect(isLocationRows({ ...response, rows: response.rows.filter(r => r.row !== 22) }, qualitySource, 2, 22, [{ column: 1 }] as never)).toBe(false)
 expect(isLocationRows({ ...response, rows: [response.rows[0], response.rows[1], { row: 47, cells: [] }] }, qualitySource, 2, 22, [{ column: 1 }] as never)).toBe(false)
})
