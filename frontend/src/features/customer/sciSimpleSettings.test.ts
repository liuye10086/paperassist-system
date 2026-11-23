import { expect, it } from 'vitest'
import { prepareSciSettings, sciSettingsDraft } from './sciProjectSettings'

it.each(['research', 'narrative_review'] as const)('saves %s intent before a journal or results are available', article_type => {
  const result = prepareSciSettings({ ...sciSettingsDraft(), article_type, proposed_title: 'Single-cell atlas',
    keywords: ['atlas', 'cell', 'sequencing', 'expression'] })
  expect(result).toMatchObject({ settings: { article_type, proposed_title: 'Single-cell atlas', target_journal: null } })
})
