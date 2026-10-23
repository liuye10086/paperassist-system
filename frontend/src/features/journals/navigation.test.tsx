import {act,cleanup,render,renderHook,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import WorkspaceShell from '../projects/WorkspaceShell'
import useProjectSelection from '../projects/useProjectSelection'
import {setLocale} from '../../shared/i18n'
import ProjectSummary from '../projects/ProjectSummary'
import {summaryFixture} from '../../test/fixtures/summaryFixture'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN');window.history.replaceState(null,'','/')})
it('offers journal advice only in SCI and translates its label',()=>{
 const props={view:'project' as const,projectName:'Research',onNavigate:vi.fn(),onCreate:vi.fn(),onCurrentProject:vi.fn(),children:<div/>}
 const view=render(<WorkspaceShell {...props} projectType="sci"/>);expect(screen.getByRole('button',{name:'期刊建议'})).toBeTruthy()
 view.rerender(<WorkspaceShell {...props} projectType="thesis"/>);expect(screen.queryByRole('button',{name:'期刊建议'})).toBeNull()
 setLocale('en');view.rerender(<WorkspaceShell {...props} projectType="sci"/>);expect(screen.getByRole('button',{name:'Journal suggestions'})).toBeTruthy()
})
it.each(['sci','thesis'])('restores journal deep links with project type %s',async type=>{
 window.history.replaceState(null,'','/#project=p1&section=journals')
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({id:'p1',name:'Research',research_topic:'Topic',project_type:type,file_count:0,created_at:'2026-10-23T00:00:00Z',updated_at:'2026-10-23T00:00:00Z',default_output_language:'zh-CN'})))
 const {result}=renderHook(()=>useProjectSelection(vi.fn(),vi.fn()));await waitFor(()=>expect(result.current.project?.id).toBe('p1'))
 expect(result.current.section).toBe(type==='sci'?'journals':'overview')
})
it('opens journal suggestions from SCI overview and scopes future placeholders to later work',async()=>{
 const open=vi.fn();vi.stubGlobal('fetch',vi.fn(async()=>Response.json(summaryFixture())))
 render(<ProjectSummary projectId="p1" projectType="sci" onOpenJournals={open}/>);const button=await screen.findByRole('button',{name:'打开期刊建议'});button.click();expect(open).toHaveBeenCalledTimes(1);expect(screen.queryByText('SCI 期刊与投稿')).toBeNull();expect(screen.getByText('期刊目标适配与投稿进展')).toBeTruthy()
})
it('preserves an exact adaptation deep link and handles reverse navigation from a saved manuscript',async()=>{
 window.history.replaceState(null,'','/#project=p1&section=journals&adaptation=a1')
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({id:'p1',name:'Research',research_topic:'Topic',project_type:'sci',file_count:0,created_at:'2026-10-23T00:00:00Z',updated_at:'2026-10-23T00:00:00Z',default_output_language:'zh-CN'})))
 const {result}=renderHook(()=>useProjectSelection(vi.fn(),vi.fn()));await waitFor(()=>expect(result.current.project?.id).toBe('p1'))
 expect(window.location.hash).toContain('adaptation=a1')
 act(()=>result.current.changeSection('manuscripts'))
 act(()=>{window.location.hash='#project=p1&section=journals&adaptation=a2';window.dispatchEvent(new HashChangeEvent('hashchange'))})
 await waitFor(()=>expect(result.current.section).toBe('journals'));expect(window.location.hash).toContain('adaptation=a2')
})
