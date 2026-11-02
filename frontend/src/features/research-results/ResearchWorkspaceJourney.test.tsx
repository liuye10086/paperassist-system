import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ResearchWorkspace from './ResearchWorkspace'
import { useResearchRead } from './api'

vi.mock('./api', async load => ({ ...await load<object>(), useResearchRead: vi.fn() }))
vi.mock('../school-templates/SchoolTemplates', () => ({ default: ({ active }: { active: boolean }) => active ? <p>学校模板工作区</p> : null }))
vi.mock('./ResearchFindings', () => ({ default: () => null }))
vi.mock('./ResearchFigureComposer', () => ({ default: () => null }))
vi.mock('./ResearchReport', () => ({ default: () => null }))
vi.mock('./ResearchWritingHandoff', () => ({ default: () => null }))
vi.mock('./ResearchCandidateReview', () => ({ default: () => null }))
vi.mock('./ResearchPublished', () => ({ default: () => null }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('opens school settings after the results action automatically selects thesis writing', async () => {
  const data = { deliveries: [{ id: 'thesis-delivery', kind: 'thesis_draft', active: true, name: 'thesis_draft' }] }
  vi.mocked(useResearchRead).mockReturnValue({ data, error: '', loading: false, loadingMessage: '', valid: true, refresh: vi.fn() })
  const props = { projectId: 'p1', projectType: 'research' as const, active: true, preferredDeliveryKind: 'thesis_draft' as const,
    section: 'manuscripts' as const, analysis: { view: 'overview' as const, fileId: '' }, artifact: { view: 'list' as const, artifactId: '', kind: '' as const, page: 1 },
    manuscriptView: 'research-selection' as const, manuscriptId: '', revision: 0, schoolNavigation: { view: 'list' as const, templateId: '' },
    onAnalysis: vi.fn(), onArtifact: vi.fn(), onManuscriptView: vi.fn(), onCandidate: vi.fn(), onPublished: vi.fn(), onSchoolNavigate: vi.fn() }
  const view = render(<ResearchWorkspace {...props} />)
  await waitFor(() => expect((screen.getByLabelText('已启用的稿件交付') as HTMLSelectElement).value).toBe('thesis-delivery'))
  view.rerender(<ResearchWorkspace {...props} section="school-templates" />)
  expect(await screen.findByText('学校模板工作区')).toBeTruthy()
  expect(screen.queryByText('thesis_draft')).toBeNull()
})
