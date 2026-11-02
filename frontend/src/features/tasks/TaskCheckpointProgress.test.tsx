import {act,cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import TaskCheckpointProgress from './TaskCheckpointProgress'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
const progress={stage:'source_verification',completed_members:1,total_members:3,table_count:2,figure_count:1,stage_started_at:'2026-11-02T00:00:00Z',stage_ended_at:null,stage_elapsed_seconds:4,observed_at:'2026-11-02T00:00:04Z',stages:[{stage:'frozen_inputs',started_at:'2026-11-02T00:00:00Z',ended_at:'2026-11-02T00:00:01Z',elapsed_seconds:1},{stage:'source_verification',started_at:'2026-11-02T00:00:01Z',ended_at:null,elapsed_seconds:3}]}
it('shows actual checkpoint stages and selected-source counts with exact historical delivery navigation, never a percentage',async()=>{
 const fetcher=vi.fn(async(_url:string)=>Response.json({task_id:'t1',task_type:'delivery_package',project_id:'p1',delivery_id:'d1',snapshot_id:'s1',status:'running',progress}));vi.stubGlobal('fetch',fetcher)
 render(<TaskCheckpointProgress projectId="p1" taskId="t1" taskType="delivery_package" active/>);await screen.findByText('来源核验');expect(screen.getByText('1 / 3 所选成员')).toBeTruthy();expect(screen.getByRole('link',{name:'返回此固定交付快照'}).getAttribute('href')).toBe('#project=p1&section=overview&view=deliveries&delivery=d1&snapshot=s1');expect(screen.queryByRole('progressbar')).toBeNull();expect(fetcher.mock.calls[0][0]).toBe('/api/v1/tasks/t1/progress')
})
it('exposes only the renderer stage actually supplied by a report and preserves source table/figure counts',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({task_id:'t1',task_type:'research_report',project_id:'p1',status:'running',progress:{...progress,stage:'rendering_report_and_package',completed_members:undefined,total_members:undefined}})))
 render(<TaskCheckpointProgress projectId="p1" taskId="t1" taskType="research_report" active/>);await screen.findByText('整理报告文档与成果包');expect(screen.getByText('来源统计：2 表 / 1 图')).toBeTruthy();expect(screen.queryByText(/PDF 生成|50%|重新生成/)).toBeNull()
})
it('does not display a crossed-project checkpoint or fetch while inactive',async()=>{
 const fetcher=vi.fn(async()=>Response.json({task_id:'t1',task_type:'delivery_package',project_id:'other-project',status:'running',progress}));vi.stubGlobal('fetch',fetcher)
 const view=render(<TaskCheckpointProgress projectId="p1" taskId="t1" taskType="delivery_package" active={false}/>);await act(async()=>{});expect(fetcher).not.toHaveBeenCalled();view.rerender(<TaskCheckpointProgress projectId="p1" taskId="t1" taskType="delivery_package" active/>);await screen.findByRole('alert');expect(screen.queryByText('来源核验')).toBeNull()
})
it.each([{projectId:'p1',taskId:'t2'},{projectId:'p2',taskId:'t1'}])('hides the prior stage and delivery link immediately when identity changes to $projectId/$taskId and its read fails',async next=>{
 let second=false
 vi.stubGlobal('fetch',vi.fn(async()=>second?Response.json({detail:{code:'internal_error'}},{status:500}):Response.json({task_id:'t1',task_type:'delivery_package',project_id:'p1',delivery_id:'d1',snapshot_id:'s1',status:'succeeded',progress})))
 const view=render(<TaskCheckpointProgress projectId="p1" taskId="t1" taskType="delivery_package" active/>);await screen.findByText('来源核验');expect(screen.getByRole('link',{name:'返回此固定交付快照'})).toBeTruthy()
 second=true;view.rerender(<TaskCheckpointProgress {...next} taskType="delivery_package" active/>);expect(screen.queryByText('来源核验')).toBeNull();expect(screen.queryByRole('link',{name:'返回此固定交付快照'})).toBeNull()
 await screen.findByRole('alert');expect(screen.queryByText('来源核验')).toBeNull();expect(screen.queryByRole('link',{name:'返回此固定交付快照'})).toBeNull()
})
