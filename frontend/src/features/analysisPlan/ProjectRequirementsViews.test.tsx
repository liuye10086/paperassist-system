import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ProjectRequirements from './ProjectRequirements'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test('research requirements keep creation and material drafts when collapsed or changing tasks', async () => {
 const fetch = vi.fn(async (_url: string, _init?: RequestInit) => Response.json({ items: [], total: 0, page: 1, page_size: 10 }))
 vi.stubGlobal('fetch', fetch)
 const user = userEvent.setup()
 render(<ProjectRequirements projectId="p1" files={[]} />)
 await user.click(screen.getByRole('button', { name: '打开研究需求与材料' }))
 const research = screen.getByLabelText('研究问题') as HTMLTextAreaElement
 await user.type(research, 'Synthetic material-first question')
 expect(screen.queryByRole('heading', { name: '外部材料与来源' })).toBeNull()
 expect(screen.queryByRole('heading', { name: '研究需求历史' })).toBeNull()
 await user.click(screen.getByRole('button', { name: '收起研究需求与材料' }))
 expect(research.isConnected).toBe(true)
 await user.click(screen.getByRole('button', { name: '打开研究需求与材料' }))
 expect(screen.getByLabelText('研究问题')).toBe(research)
 await user.click(screen.getByRole('button', { name: '需求材料' }))
 const title = screen.getByLabelText('材料标题') as HTMLInputElement
 await user.type(title, 'Synthetic material draft')
 await user.click(screen.getByRole('button', { name: '研究需求历史' }))
 expect(screen.queryByRole('heading', { name: '外部材料与来源' })).toBeNull()
 await user.click(screen.getByRole('button', { name: '需求材料' }))
 expect(screen.getByLabelText('材料标题')).toBe(title)
 expect(title.value).toBe('Synthetic material draft')
 await user.click(screen.getByRole('button', { name: '创建研究需求' }))
 expect(research.value).toBe('Synthetic material-first question')
 expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})
