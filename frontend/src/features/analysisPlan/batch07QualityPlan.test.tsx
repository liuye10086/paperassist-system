import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import AnalysisPlanReview from './AnalysisPlanReview'
import { reviewFixture } from './analysisPlanFixtures'
import { qualitySource, qualityVersion } from '../datasetPreparation/batch07Fixtures'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
test('new quality source shows upstream exclusions and still requires its own explicit plan review', async () => {
 const input = { ...reviewFixture.input_version, source: qualitySource }
 const review = { ...reviewFixture, source: qualitySource, input_version: input, task: { ...reviewFixture.task, input_version: input } }
 const fetch = vi.fn(async (url: string) => Response.json(url.includes('/prepared-dataset-versions/') ? qualityVersion : review)); vi.stubGlobal('fetch', fetch)
 render(<AnalysisPlanReview projectId="p1" taskId="t1" expectedSource={qualitySource} />)
 expect(await screen.findByText('原始区域 45 行 − 累计整理排除 2 行 = 当前整理保留 43 行。')).toBeTruthy()
 expect(screen.getByText('质量确认不替代分析计划确认。新版本须重新检查字段、类型、单位、有效记录和研究设计，并独立确认分析计划。')).toBeTruthy()
 expect(fetch.mock.calls.every(([url]) => !url.includes('/decisions'))).toBe(true)
 expect(document.body.textContent).not.toContain(qualitySource.dataset_sha256)
})
test('an older plan cannot confirm a different quality version', async () => {
 vi.stubGlobal('fetch', vi.fn(async () => Response.json(reviewFixture)))
 render(<AnalysisPlanReview projectId="p1" taskId="t1" expectedSource={qualitySource} />)
 expect(await screen.findByRole('alert')).toBeTruthy()
 expect(screen.queryByRole('button', { name: '确认并发布分析计划' })).toBeNull()
})
