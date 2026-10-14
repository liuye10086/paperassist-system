import { expect, it } from 'vitest';
import { isDataset, isRows, isStructure, isStructurePage } from './datasetApi';
import { dataset, page, rowPage, version } from './datasetFixtures';
it('rejects crossed identity and malformed raw cells', () => {
    expect(isStructure({ ...version, file_id: 'other' }, 'p1', 'f1')).toBe(false);
    expect(isRows({ ...rowPage(), dataset: { ...dataset, id: 'other' } }, dataset, 1)).toBe(false);
    expect(isRows({ ...rowPage(), rows: [{ row: 1, cells: [{ ...rowPage().rows[0].cells[0], value: Number('9007199254740993') }] }] }, dataset, 1)).toBe(false);
    expect(isRows({ ...rowPage(), rows: [{ row: 1, cells: [{ ...rowPage().rows[0].cells[0], formula: {} }] }] }, dataset, 1)).toBe(false);
});
it('rejects invalid epoch, duplicate versions and duplicate coordinates', () => {
    expect(isDataset({ ...dataset, epoch: 'unknown' }, 'f1')).toBe(false);
    expect(isStructurePage({ ...page, items: [version, version], total: 2 }, 'p1', 'f1', 1)).toBe(false);
    const r = rowPage().rows[0];
    expect(isRows({ ...rowPage(), rows: [r, r] }, dataset, 1)).toBe(false);
});
it('accepts an API-shaped shared formula follower with null text on rows 21 through 31', () => {
    const summary = { ...dataset, column_count: 3, stored_range: 'A1:C31', content_range: 'A1:C31' };
    const response = { ...rowPage(21), dataset: summary };
    const follower = { row: 31, column: 3, coordinate: 'C31', kind: 'formula', value: '=', raw_type: 'n', raw_value: '31', number_format: 'General', formula: { text: null, attributes: { t: 'shared', si: '0' }, cache_state: 'present', cached_type: 'n', cached_value: '31', cache_validity: 'unverified' } };
    const rows = response.rows.map(row => row.row === 31 ? { ...row, cells: [...row.cells, follower] } : row);
    expect(isRows({ ...response, rows }, summary, 21)).toBe(true);
    for (const text of [undefined, 31, {}]) {
        const invalidRows = rows.map(row => row.row === 31 ? { ...row, cells: [{ ...follower, formula: { ...follower.formula, text } }] } : row);
        expect(isRows({ ...response, rows: invalidRows }, summary, 21)).toBe(false);
    }
});
