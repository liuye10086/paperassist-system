import {expect,it} from 'vitest'
import {isTaskPage,isWorkspace,isEventPage,sameInputVersion} from '../tasks/taskTypes'
const input={kind:'bio_cloud_run' as const,workflow_version:'bio_cloud_run_v1' as const,run_id:'r1',profile_id:'profile',sample_id:'S',input_sha256:'a'.repeat(64)}
const task={id:'t1',project_id:'p',task_type:'bio_cloud_run',status:'cancelled',phase:'compute',display_status:'cancelled',reason_code:null,error_code:null,created_at:'2026-11-05T00:00:00Z',updated_at:'2026-11-05T00:00:00Z',input_version:input,revision:2,current_attempt:1,retry_count:0}
const source={file_id:null,filename:'单细胞云端预处理 · S',analysis_run_id:null,is_current:true}
it('accepts cloud run in unified task list and validates public input identity',()=>{
 const page={project_id:'p',page:1,page_size:10,total:1,items:[{task,source}]}
 expect(isTaskPage(page,'p',1)).toBe(true)
 expect(isTaskPage({...page,items:[{task:{...task,input_version:{...input,input_sha256:'invalid'}},source}]},'p',1)).toBe(false)
 expect(isTaskPage({...page,items:[{task:{...task,input_version:{...input,bucket:'secret'}},source}]},'p',1)).toBe(false)
 expect(sameInputVersion(input,input)).toBe(true)
 expect(sameInputVersion(input,{...input,run_id:'other'})).toBe(false)
})
it('accepts safe cloud workspace artifact and rejects mismatched run or generic retry',()=>{
 const detail={task,source,wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null,bio_cloud:{run_id:'r1',status:'cancelled',engine:'STARsolo',provider_run_id:'remote1'}}}
 expect(isWorkspace(detail,'p','t1')).toBe(true)
 expect(isWorkspace({...detail,allowed_actions:['retry']},'p','t1')).toBe(false)
 expect(isWorkspace({...detail,artifacts:{...detail.artifacts,bio_cloud:{...detail.artifacts.bio_cloud,run_id:'other'}}},'p','t1')).toBe(false)
})
it('accepts cancellation task event',()=>{
 expect(isEventPage({task_id:'t1',items:[{seq:1,task_revision:2,event_type:'cancelled',status:'cancelled',phase:'compute',reason_code:null,created_at:'2026-11-05T00:00:00Z'}],next_cursor:1,has_more:false},'t1',0)).toBe(true)
})

import {render,screen,cleanup} from '@testing-library/react'
import BioTaskLinks from '../tasks/BioTaskLinks'
import type {TaskView} from '../tasks/taskTypes'
it('links cloud task to existing bio dataset workspace',()=>{
 render(<BioTaskLinks task={task as unknown as TaskView}/>)
 expect((screen.getByRole('link',{name:'返回生信工作区核对云运行'}) as HTMLAnchorElement).getAttribute('href')).toBe('#project=p&section=analysis&view=bio-datasets')
 cleanup()
})
it('keeps valid 100-character profile and sample identifiers accepted by backend contracts',()=>{
 expect(isTaskPage({project_id:'p',page:1,page_size:10,total:1,items:[{task:{...task,input_version:{...input,profile_id:'p'.repeat(100),sample_id:'s'.repeat(100)}},source}]},'p',1)).toBe(true)
})
