import {afterEach,expect,test,vi} from 'vitest'
import {cleanup,render,screen} from '@testing-library/react'
import ProjectModelUsage from './ProjectModelUsage'
import {usageFixture} from '../tasks/taskFixtures'
import {setLocale} from '../../shared/i18n'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
test.each(['zh-CN','en'] as const)('reads recommendation call usage and shows its purpose in %s',async locale=>{
 setLocale(locale);vi.stubGlobal('fetch',vi.fn(async()=>Response.json({...usageFixture,items:[{...usageFixture.items[0],task_type:'analysis_recommendation'}]})))
 render(<ProjectModelUsage projectId="p1"/>)
 expect(await screen.findByText(locale==='en'?'Restricted analysis recommendation':'受限分析建议')).toBeTruthy()
 expect(document.body.textContent).not.toContain('call-private')
})
