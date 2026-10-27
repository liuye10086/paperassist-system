import {cleanup,render,screen,renderHook,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import WorkspaceShell from '../projects/WorkspaceShell'
import useProjectSelection from '../projects/useProjectSelection'
import {setLocale} from '../../shared/i18n'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN');window.history.replaceState(null,'','/')})
it('offers school templates only for thesis projects and translates navigation',()=>{
 const props={view:'project' as const,projectName:'研究',section:'school-templates' as const,onNavigate:vi.fn(),onCreate:vi.fn(),onCurrentProject:vi.fn(),children:<div/>}
 const view=render(<WorkspaceShell {...props} projectType="thesis"/>);expect(screen.getByRole('button',{name:'学校模板'}).getAttribute('aria-current')).toBe('page');expect(screen.queryByRole('button',{name:'SCI 写作'})).toBeNull()
 view.rerender(<WorkspaceShell {...props} section="manuscripts" projectType="sci"/>);expect(screen.queryByRole('button',{name:'学校模板'})).toBeNull();expect(screen.getByRole('button',{name:'SCI 写作'})).toBeTruthy()
 setLocale('en');view.rerender(<WorkspaceShell {...props} projectType="thesis"/>);expect(screen.getByRole('button',{name:'School template'})).toBeTruthy()
})
it('restores the school template section from its project deep link',async()=>{
 window.history.replaceState(null,'','/#project=p1&section=school-templates')
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({id:'p1',name:'研究',research_topic:'主题',project_type:'thesis',file_count:0,created_at:'2026-10-08T00:00:00Z',updated_at:'2026-10-08T00:00:00Z',default_output_language:'zh-CN'})))
 const {result}=renderHook(()=>useProjectSelection(vi.fn(),vi.fn()));await waitFor(()=>expect(result.current.project?.id).toBe('p1'));expect(result.current.section).toBe('school-templates');expect(window.location.hash).toContain('section=school-templates')
})

it('keeps the thesis manuscript deep link and school-specific navigation label',async()=>{
 window.history.replaceState(null,'','/#project=p1&section=manuscripts')
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({id:'p1',name:'研究',research_topic:'主题',project_type:'thesis',file_count:0,created_at:'2026-10-08T00:00:00Z',updated_at:'2026-10-08T00:00:00Z',default_output_language:'zh-CN'})))
 const {result}=renderHook(()=>useProjectSelection(vi.fn(),vi.fn()));await waitFor(()=>expect(result.current.project?.id).toBe('p1'));expect(result.current.section).toBe('manuscripts');expect(window.location.hash).toContain('section=manuscripts')
 render(<WorkspaceShell view="project" section="manuscripts" projectName="研究" projectType="thesis" onNavigate={vi.fn()} onCreate={vi.fn()} onCurrentProject={vi.fn()}><div/></WorkspaceShell>)
 expect(screen.getByRole('button',{name:'毕业论文写作'}).getAttribute('aria-current')).toBe('page')
})
