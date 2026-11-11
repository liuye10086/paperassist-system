import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ProjectJourney from './ProjectJourney'
import type {Project} from './projectTypes'
import type {AnalysisNavigation} from './analysisViews'

afterEach(cleanup)
const project:Project={id:'p1',name:'项目',research_topic:'主题',project_type:'research',file_count:1,created_at:'',updated_at:''}
const props={project,overviewView:'settings' as const,blocked:()=>'',hasAnalysis:true,onOverview:vi.fn(),onUpload:vi.fn(),onAnalysis:vi.fn(),onResults:vi.fn(),onWriting:vi.fn()}
it.each(['bio-result','bio-insight-result','report'] as AnalysisNavigation['view'][])('shows the results step at the existing %s route without claiming completion',analysisView=>{
 render(<ProjectJourney {...props} section="analysis" analysisView={analysisView}/>)
 const results=screen.getByRole('button',{name:'第 5 步：查看结果'})
 const analysis=screen.getByRole('button',{name:'第 4 步：执行分析'})
 expect(results.getAttribute('aria-current')).toBe('step')
 expect(analysis.getAttribute('aria-current')).toBeNull()
 for (const step of [screen.getByRole('button',{name:'第 3 步：选择需求'}), analysis, results]) {
   expect(step.textContent).not.toContain('已完成')
 }
})
it('shows the results step while viewing Word manuscripts',()=>{
 render(<ProjectJourney {...props} section="manuscripts"/>);expect(screen.getByRole('button',{name:'第 5 步：查看结果'}).getAttribute('aria-current')).toBe('step')
})
it('continues to show the working step at a run route',()=>{
 render(<ProjectJourney {...props} section="analysis" analysisView="bio-analysis"/>);expect(screen.getByRole('button',{name:'第 4 步：执行分析'}).getAttribute('aria-current')).toBe('step');expect(screen.getByRole('button',{name:'第 5 步：查看结果'}).getAttribute('aria-current')).toBeNull()
})
