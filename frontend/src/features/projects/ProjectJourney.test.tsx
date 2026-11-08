import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, vi, it } from 'vitest'
import { ProjectWorkspaceVisibleContext } from '../../shared/components/WorkspaceChromeContext'
import ProjectJourney from './ProjectJourney'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

const state = {
  project_id: 'p1',
  project_type: 'research' as const,
  files: { total: 1, ready: 1 },
  requirements: { saved: true, version: 2, services: ['analysis'] as ('analysis' | 'sci_draft' | 'thesis_draft')[] },
  results: { available: false },
  next_step: 'analysis' as const,
}
const props = {
  project: { id: 'p1', name: '研究', research_topic: '主题', project_type: 'research' as const,
    default_output_language: 'zh-CN' as const, file_count: 1, created_at: '', updated_at: '' },
  section: 'analysis' as const,
  overviewView: 'settings' as const,
  onOverview: vi.fn(), onUpload: vi.fn(), onAnalysis: vi.fn(), onResults: vi.fn(), onWriting: vi.fn(),
  blocked: vi.fn((section: string) => section === 'artifacts' ? '请先完成分析' : ''), active: true, hasAnalysis: true, workflowState: state,
}

function renderJourney() {
  return render(<ProjectWorkspaceVisibleContext.Provider value={true}>
    <ProjectJourney {...props} />
  </ProjectWorkspaceVisibleContext.Provider>)
}

it('shows completed, active and waiting statuses from workflow state', () => {
  renderJourney()
  expect(screen.getAllByText('已完成').length).toBeGreaterThan(0)
  expect(screen.getByText('进行中')).toBeTruthy()
  expect(screen.getByText('待处理')).toBeTruthy()
})

it('exposes one primary next action and keeps blocked steps disabled', () => {
  renderJourney()
  expect(screen.getByRole('button', { name: /下一步/ })).toBeTruthy()
  expect(screen.getAllByRole('button', { name: /第/ }).some(button => button.hasAttribute('disabled'))).toBe(true)
})

it('keeps the results step active until the user opens it', () => {
  render(<ProjectWorkspaceVisibleContext.Provider value={true}>
    <ProjectJourney {...props} workflowState={{ ...state, results: { available: true }, next_step: 'results' }} />
  </ProjectWorkspaceVisibleContext.Provider>)
  const navigation = screen.getByRole('navigation', { name: '项目操作步骤' })
  const resultsStep = within(navigation).getByRole('button', { name: '第 5 步：查看结果' })
  expect(resultsStep.textContent).toContain('进行中')
})
