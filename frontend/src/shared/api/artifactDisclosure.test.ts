import { expect, it } from 'vitest'
import { isArtifactDisclosure } from './artifactDisclosure'

const value = { version: 1, provider: 'openai', task_type: 'boxplot', source_digest: 'local-only', has_saved_result: false,
  summary: { valid_count: 4, excluded_count: 1, group_count: 2 }, labels: [{ key: 'numeric_name', value: '量值' }, { key: 'unit', value: '' }, { key: 'group_name', value: '分组' }, { key: 'group:0', value: 'A' }, { key: 'group:1', value: 'B' }] }
it('accepts grouped and ungrouped disclosures for the matching task only', () => {
  expect(isArtifactDisclosure(value, 'boxplot')).toBe(true)
  expect(isArtifactDisclosure({ ...value, labels: value.labels.slice(0, 2) }, 'boxplot')).toBe(true)
  expect(isArtifactDisclosure(value, 'explanation')).toBe(false)
  expect(isArtifactDisclosure({ ...value, task_type: 'explanation', labels: [...value.labels, { key: 'figure_title', value: '图表' }] }, 'explanation')).toBe(true)
})
it.each([null, {}, { ...value, source_digest: null }, { ...value, provider: 'unknown' }, { ...value, version: 2 }, { ...value, has_saved_result: null },
  { ...value, summary: { ...value.summary, valid_count: -1 } }, { ...value, labels: [...value.labels, { key: 'sheet_name', value: 'internal' }] },
  { ...value, labels: [...value.labels.slice(0, 4), value.labels[3]] }, { ...value, labels: value.labels.slice(1) }, { ...value, summary: { ...value.summary, group_count: 3 } },
  { ...value, summary: { ...value.summary, group_count: Number.MAX_SAFE_INTEGER } },
])('rejects incomplete or unrecognized preview contracts safely (%j)', data => {
  expect(isArtifactDisclosure(data, 'boxplot')).toBe(false)
})
