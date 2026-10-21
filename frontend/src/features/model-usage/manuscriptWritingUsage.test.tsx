import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,render,screen,within} from '@testing-library/react'
import ProjectModelUsage from './ProjectModelUsage'
import TaskModelUsage from './TaskModelUsage'
import {isProjectUsage,isTaskUsage} from './modelUsageTypes'
import {usageFixture} from '../tasks/taskFixtures'
import {setLocale} from '../../shared/i18n'
const writingUsage={...usageFixture,items:[{...usageFixture.items[0],task_type:'manuscript_writing',model:'Synthetic writing fixture'}]}
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it('accepts manuscript writing receipts in project and task usage while rejecting invented types',()=>{
 expect(isProjectUsage(writingUsage,1)).toBe(true);expect(isTaskUsage(writingUsage,1)).toBe(true);expect(isProjectUsage({...writingUsage,items:[{...writingUsage.items[0],task_type:'invented_writing'}]},1)).toBe(false)
})
it.each(['zh-CN','en'] as const)('renders retained writing accounting and purpose in %s without implying free verified calls',async locale=>{
 setLocale(locale);vi.stubGlobal('fetch',vi.fn(async()=>Response.json(writingUsage)));render(<ProjectModelUsage projectId="p1"/>);expect(await screen.findByText(locale==='en'?'Complete manuscript writing':'完整稿件写作')).toBeTruthy();const row=screen.getByText('Synthetic writing fixture').closest('tr')!;expect(within(row).getByText(locale==='en'?'Awaiting reconciliation':'待核对')).toBeTruthy();expect(within(row).queryByText('USD 0.000000')).toBeNull();expect(document.body.textContent).not.toContain('call-private')
})
it('loads writing receipts from the task usage panel',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json(writingUsage)));render(<TaskModelUsage taskId="writing-task"/>);expect(await screen.findByText('Synthetic writing fixture')).toBeTruthy();expect(screen.queryByRole('alert')).toBeNull()
})
