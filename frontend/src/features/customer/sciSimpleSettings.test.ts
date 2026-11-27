import { expect, it } from 'vitest'
import { prepareSciSettings, restoreSciSettingsDraft, sciSettingsDraft } from './sciProjectSettings'

const keywords = ['atlas', 'cell', 'sequencing', 'expression']

it.each(['research', 'narrative_review'] as const)('saves %s intent with a selected journal and no results', article_type => {
  const result = prepareSciSettings({ ...sciSettingsDraft(), article_type, proposed_title: 'Single-cell atlas', keywords,
    target_journal: { selection: 'Nature Communications', customName: '' } })
  expect(result).toMatchObject({ settings: { article_type, proposed_title: 'Single-cell atlas',
    target_journal: { choice: 'other', name: 'Nature Communications' } } })
})

it('maps a saved journal to its preset and keeps older custom journal drafts', () => {
  const saved = sciSettingsDraft({ article_type: 'research', proposed_title: 'Atlas', keywords, figure_findings: [],
    target_journal: { choice: 'other', name: 'PLOS ONE' } })
  expect(saved.target_journal).toEqual({ selection: 'PLOS ONE', customName: '' })
  const restored = restoreSciSettingsDraft({ ...saved, target_journal: { choice: 'nature_subjournal', name: 'Nature Methods' } })
  expect(restored.target_journal).toEqual({ selection: 'other', customName: 'Nature Methods' })
})

it('saves review basics after restoring an old draft with an unfinished subsection', () => {
  const restored = restoreSciSettingsDraft({
    ...sciSettingsDraft(), article_type: 'narrative_review', proposed_title: 'Single-cell atlas', keywords,
    target_journal: { selection: 'Science', customName: '' },
    review_sections: [{ id: 'unused', heading: 'Old heading', content: '' }],
  })
  expect(prepareSciSettings(restored)).toMatchObject({ settings: {
    article_type: 'narrative_review', proposed_title: 'Single-cell atlas', review_sections: [],
  } })
})
