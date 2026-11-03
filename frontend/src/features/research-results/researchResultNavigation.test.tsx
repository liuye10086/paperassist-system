import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import ResearchFigureComposer from './ResearchFigureComposer'
import ResearchReport from './ResearchReport'

beforeEach(() => { setApiSession('csrf', 'owner'); sessionStorage.clear() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); clearApiSession(); sessionStorage.clear() })

it.each(['figure', 'report'] as const)('preserves a copied %s draft when switching result categories', async kind => {
  const config = { expected_revision: 0, mode: 'reuse', panels: [], title: 'Original figure', caption: '', caption_fact_ids: [], caption_sources: [], language: 'zh-CN', figure_language: 'original', width_mm: 180, dpi: 300, columns: 2, background: '#ffffff', margin_mm: 3, font_size_pt: 10, formats: ['png'] }
  const finding = { id: 'finding', revision: 1, content: { title: 'Findings', facts: [], methods: [], gaps: [], limitations: [], claims: [] } }
  const record = { id: 'fixed', root_id: 'root', revision: 1, config, content: { title: 'Original report', language: 'zh-CN', finding, figures: [], tables: [] }, members: [], task: { id: 'task', status: 'succeeded' }, manifest: null }
  const fetch = vi.fn(async () => Response.json({ ...record, items: [], total: 0, page: 1, page_size: 20 }))
  vi.stubGlobal('fetch', fetch)
  const Component = kind === 'figure' ? ResearchFigureComposer : ResearchReport
  const props = { projectId: 'p1', active: true, selectedId: 'fixed', onSelect: vi.fn() }
  const view = render(<Component {...props} />)
  fireEvent.click(await screen.findByRole('button', { name: kind === 'figure' ? '以此版本另存新图版本' : '以此报告另存新版本' }))
  const label = kind === 'figure' ? '图标题' : '报告标题'
  fireEvent.change(screen.getByLabelText(label), { target: { value: 'Retained draft' } })
  view.rerender(<Component {...props} active={false} selectedId="" />)
  view.rerender(<Component {...props} />)
  expect((await screen.findByLabelText(label) as HTMLInputElement).value).toBe('Retained draft')
  expect(JSON.parse(sessionStorage.getItem(`paperassist.research-draft.v1:owner:p1:${kind}:fixed`)!).title).toBe('Retained draft')
})
