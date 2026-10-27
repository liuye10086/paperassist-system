import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { useState } from 'react'
import WorkspaceShell, { type ProjectSection } from './WorkspaceShell'
afterEach(cleanup)
function Harness({ type = 'sci' }: {type?: 'sci' | 'thesis'}) {
 const [section,setSection]=useState<ProjectSection>('overview')
 return <WorkspaceShell view="project" onNavigate={vi.fn()} onCreate={vi.fn()} projectName="测试研究" projectType={type} section={section} onSectionChange={setSection} onCurrentProject={vi.fn()}><p>body</p></WorkspaceShell>
}
test('groups enter first task and expose every applicable task',async()=>{
 const user=userEvent.setup(); render(<Harness/>); const nav=within(screen.getByRole('navigation',{name:'项目导航'}))
 expect(nav.queryByRole('button',{name:'项目文件'})).toBeNull()
 await user.click(nav.getByRole('button',{name:'材料准备'})); expect(nav.getByRole('button',{name:'项目文件'}).getAttribute('aria-current')).toBe('page')
 await user.click(nav.getByRole('button',{name:'文献'})); expect(nav.getByRole('button',{name:'文献'}).getAttribute('aria-current')).toBe('page')
 await user.click(nav.getByRole('button',{name:'分析与成果'})); expect(nav.queryByRole('button',{name:'文献'})).toBeNull(); expect(nav.getByRole('button',{name:'图表与报告'})).toBeTruthy()
 await user.click(nav.getByRole('button',{name:'稿件写作'})); expect(nav.getByRole('button',{name:'期刊建议'})).toBeTruthy(); expect(nav.queryByRole('button',{name:'学校模板'})).toBeNull()
 await user.click(nav.getByRole('button',{name:'评审与修改'})); expect(nav.getByRole('button',{name:'项目任务'})).toBeTruthy()
 await user.click(nav.getByRole('button',{name:'项目概览'})); expect(nav.queryByRole('button',{name:'项目任务'})).toBeNull()
})
test('thesis writing and mobile Escape keep navigation usable',async()=>{
 const user=userEvent.setup();render(<Harness type="thesis"/>);const nav=within(screen.getByRole('navigation',{name:'项目导航'}));await user.click(nav.getByRole('button',{name:'稿件写作'}));expect(nav.getByRole('button',{name:'毕业论文写作'})).toBeTruthy();expect(nav.getByRole('button',{name:'学校模板'})).toBeTruthy()
 const menu=screen.getByRole('button',{name:'导航'});await user.click(menu);expect(menu.getAttribute('aria-expanded')).toBe('true');await user.keyboard('{Escape}');expect(menu.getAttribute('aria-expanded')).toBe('false');expect(document.activeElement).toBe(menu)
})
