import { expect, test } from 'vitest'
import { comparisonResult } from './comparisonFixtures'
import { correlationResult } from './correlationFixtures'
import { modelingRocFixture } from './modelFixtures'
import { validStatisticsContext } from './statisticsContext'

test.each([['comparison', comparisonResult], ['correlation', correlationResult], ['roc', modelingRocFixture]])('%s accepts exact optional execution contract while retaining legacy reads', (_, result) => {
 const base = '/api/v1/projects/p1/files/f1'
 expect(validStatisticsContext(result as never, base)).toBe(true)
 expect(validStatisticsContext({ ...result, engine: { ...result.engine, execution_contract: 'fixed_statistics_v2' } } as never, base)).toBe(true)
 expect(validStatisticsContext({ ...result, engine: { ...result.engine, execution_contract: 'unknown' } } as never, base)).toBe(false)
 expect(validStatisticsContext({ ...result, engine: { ...result.engine, execution_contract: null } } as never, base)).toBe(false)
})
