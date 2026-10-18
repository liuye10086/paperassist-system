import { expect, test } from 'vitest'
import fixture from './batch07BackendFixture.json'
import { isPreparedVersion } from './preparationApi'
import { isImpactPage, isQualityCounts, isQualityImpact, isQualityRecipe, isQualityReview, isQualitySheet, isQualitySummary, isQualityVersionData } from './qualityApi'
import { isDatasetSource } from '../analysis/datasetSource'

test('real isolated backend responses satisfy the frozen frontend contract', () => {
 expect(isDatasetSource(fixture.defaults.source)).toBe(true)
 expect(isQualityRecipe(fixture.defaults.recipe)).toBe(true)
 expect(isQualityCounts(fixture.defaults.summary)).toBe(true)
 expect(isQualitySheet(fixture.defaults.sheet)).toBe(true)
 expect(isQualityReview(fixture.review, fixture.review.task.project_id, fixture.review.task.id)).toBe(true)
 expect(isQualityVersionData(fixture.published, fixture.published.file_id)).toBe(true)
 expect(isPreparedVersion(fixture.rows.dataset, fixture.published.file_id)).toBe(true)
 expect(isImpactPage(fixture.impacts, 1)).toBe(true)
})

test('v2 quality contracts reject impossible counts, unsupported rules, and mismatched coordinates', () => {
 expect(isQualitySummary({ ...fixture.published.summary, retained_record_count: 999 })).toBe(false)
 expect(isQualityRecipe({ ...fixture.defaults.recipe, imputation: 'mean' })).toBe(false)
 const cell = fixture.impacts.items.find(item => item.operation === 'cell_change')!
 expect(isQualityImpact({ ...cell, coordinate: 'A99999' })).toBe(false)
 expect(isQualityReview({ ...fixture.review, root_source: { ...fixture.review.root_source, dataset_version: 9 } })).toBe(false)
 expect(isQualityVersionData({ ...fixture.published, base_source: { ...fixture.published.base_source, dataset_version: fixture.published.version + 1 } }, fixture.published.file_id)).toBe(false)
})
