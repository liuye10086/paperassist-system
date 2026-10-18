import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import StatisticsResults from './StatisticsResults'
import { reviewFixture } from '../analysisPlan/analysisPlanFixtures'
import { v3Plan } from '../analysisPlan/batch02Fixtures'
import { qualitySource, qualityVersion } from '../datasetPreparation/batch07Fixtures'
import { setLocale } from '../../shared/i18n'
import CorrelationResults from './CorrelationResults'
import { correlationResult } from './correlationFixtures'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); setLocale('zh-CN') })
test('correlation counts refer to the active prepared version, not the original rectangle', () => {
 render(<CorrelationResults result={{ ...correlationResult, source: qualitySource } as never} />)
 expect(screen.getByText('当前整理保留 4 行；共同完整记录 n = 4；本分析排除 0 行。')).toBeTruthy()
 expect(document.body.textContent).not.toContain('原整理区域')
})
test('quality result separates preparation exclusions from analysis exclusions and removes false no-deduplication claims', async () => {
 const selection = reviewFixture.selection
 const plan = { ...v3Plan, source: qualitySource, selection }
 const result = { schema_version: 3, analysis_context: { plan, method: { id: 'descriptive', parameters: selection, observation_basis: 'rows' }, rounding: { display_significant_digits: 6, stored_values: 'full_precision' }, not_computed: { p_value: { value: null, reason: 'not_applicable_descriptive' }, effect_size: { value: null, reason: 'not_applicable_descriptive' }, confidence_interval: { value: null, reason: 'not_applicable_descriptive' } } }, id: 'run2', filename: 'synthetic.xlsx', source: qualitySource, source_sha256: qualitySource.source_sha256, setup_revision: 2, selection, check: { ready: true, row_count: 43, valid_count: 4, excluded_count: 39, issues: [], warnings: [], groups: [] }, numeric_name: 'Measure', group_name: null, engine: { id: 'descriptive', python_version: '3' }, started_at: qualityVersion.created_at, completed_at: qualityVersion.created_at, overall: { n: 4, mean: 5, std: 2, min: 3, q1: 4, median: 5, q3: 6, max: 8, iqr: 2, warnings: [] }, groups: [] }
 vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(url.endsWith('/analysis-result') ? { current_revision: 2, is_current: true, result } : url.includes('/prepared-dataset-versions/') ? qualityVersion : url.endsWith('/figure-workbench') ? { configurations: [], fields: [], available_kinds: [], language: 'en' } : { current_revision: 2, is_current: true, figure: null, job: null })))
 render(<StatisticsResults base="/api/v1/projects/p1/files/f1" savedRevision={2} savedSource={qualitySource} fieldsMatch disabled={false} onBusyChange={() => {}} />)
 await screen.findByRole('table', { name: '描述统计结果' })
 expect(screen.getByText('当前整理保留 43 行 − 本分析排除 39 行 = 本分析有效 4 行。')).toBeTruthy()
 expect(document.body.textContent).not.toContain('未去重、未剔除离群值')
 expect(await screen.findAllByText('原始区域 45 行 − 累计整理排除 2 行 = 当前整理保留 43 行。')).toHaveLength(2)
})
