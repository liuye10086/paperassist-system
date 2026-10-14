import { expect, test } from 'vitest'
import { isPlanReview } from './analysisPlanApi'
import { reviewFixture } from './analysisPlanFixtures'

test('validates a scoped plan review and rejects a crossed source or malformed issue', () => {
  expect(isPlanReview(reviewFixture, 'p1', 't1')).toBe(true)
  expect(isPlanReview({ ...reviewFixture, source: { ...reviewFixture.source, file_id: 'f2' } }, 'p1', 't1')).toBe(false)
  expect(isPlanReview({ ...reviewFixture, check: { ...reviewFixture.check, issues: [{ ...reviewFixture.check.issues[0], coordinates: ['C5', 'C6', 'C7', 'C8', 'C9', 'C10'] }] } }, 'p1', 't1')).toBe(false)
})
