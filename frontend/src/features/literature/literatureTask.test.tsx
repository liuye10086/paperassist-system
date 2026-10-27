import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { isTask, isTaskPage, isWorkspace } from '../tasks/taskTypes'
import WorkspaceShell from '../projects/WorkspaceShell'
afterEach(cleanup)
import { literatureTask, literatureWorkspace } from './fixtures'
it('decodes literature task and null-file source without requiring manuscript evidence', () => {
 expect(isTask(literatureTask, 'p1')).toBe(true)
 expect(isTaskPage({ project_id: 'p1', page: 1, page_size: 10, total: 1, items: [literatureWorkspace] }, 'p1', 1)).toBe(true)
 expect(isWorkspace(literatureWorkspace, 'p1', 'search1')).toBe(true)
 expect(isWorkspace({ ...literatureWorkspace, artifacts: { ...literatureWorkspace.artifacts, literature: { search_id: 'other', retrieved_count: 0, matched_count: null } } }, 'p1', 'search1')).toBe(false)
})
it('adds literature navigation for a project', () => {
 render(<WorkspaceShell view="project" section="literature" projectName="Synthetic project" onNavigate={vi.fn()} onCreate={vi.fn()} onCurrentProject={vi.fn()}><div /></WorkspaceShell>)
 expect(screen.getByRole('button', { name: '文献' })).toBeTruthy()
})
