import { describe, expect, it } from 'vitest'
import { isDatasetSource, sameSource } from '../analysis/datasetSource'
import { baseSource as original } from './batch07Fixtures'

describe('batch09 sources', () => {
 it('accepts v3 only with matching object and transform versions', () => {
  const source = {...original, schema_version:3, dataset_schema_version:3, transform_version:'excel_prepare_v3'}
  expect(isDatasetSource(source)).toBe(true)
  expect(isDatasetSource({...source, transform_version:'excel_prepare_v2'})).toBe(false)
  expect(sameSource(source as never, original)).toBe(false)
 })
})
