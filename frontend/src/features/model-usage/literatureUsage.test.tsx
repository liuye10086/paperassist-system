import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,render,screen,within} from '@testing-library/react'
import ProjectModelUsage from './ProjectModelUsage'
import TaskModelUsage from './TaskModelUsage'
import {isProjectUsage,isTaskUsage} from './modelUsageTypes'
import {usageFixture} from '../tasks/taskFixtures'
import {setLocale} from '../../shared/i18n'
// Synthetic usage receipt only: no provider call or paid request is made.
const literatureUsage={...usageFixture,items:[{...usageFixture.items[0],task_type:'literature_assistance',model:'Synthetic literature model'}]}
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it('accepts literature assistance usage through both project and task contracts',()=>{
 expect(isProjectUsage(literatureUsage,1)).toBe(true)
 expect(isTaskUsage(literatureUsage,1)).toBe(true)
 expect(isProjectUsage({...literatureUsage,items:[{...literatureUsage.items[0],task_type:'invented_model_type'}]},1)).toBe(false)
})
it.each(['zh-CN','en'] as const)('renders literature assistance purpose and retained unknown cost in project usage in %s',async locale=>{
 setLocale(locale);vi.stubGlobal('fetch',vi.fn(async()=>Response.json(literatureUsage)))
 render(<ProjectModelUsage projectId="p1"/>)
 expect(await screen.findByText(locale==='en'?'Literature model assistance':'文献模型建议')).toBeTruthy()
 const row=screen.getByText('Synthetic literature model').closest('tr')!
 expect(within(row).getByText(locale==='en'?'Awaiting reconciliation':'待核对')).toBeTruthy()
 expect(within(row).queryByText('USD 0.000000')).toBeNull()
 expect(screen.queryByRole('alert')).toBeNull()
 expect(document.body.textContent).not.toContain('call-private')
})
it.each(['zh-CN','en'] as const)('renders saved literature assistance call in the task usage panel in %s',async locale=>{
 setLocale(locale);const fetch=vi.fn(async()=>Response.json(literatureUsage));vi.stubGlobal('fetch',fetch)
 render(<TaskModelUsage taskId="literature-assist1"/>)
 expect(await screen.findByText('Synthetic literature model')).toBeTruthy()
 expect(screen.queryByRole('alert')).toBeNull()
 expect(fetch.mock.calls).toHaveLength(1)
 expect(document.body.textContent).not.toContain('call-private')
})
