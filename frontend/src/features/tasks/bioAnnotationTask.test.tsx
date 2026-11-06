import {expect,it} from 'vitest'
import {render,screen,cleanup} from '@testing-library/react'
import {isTask,isWorkspace,sameInputVersion} from './taskTypes'
import BioTaskLinks from './BioTaskLinks'
import {processedFixture,runFixture} from '../bioinformatics/spatialFixtures'
const input={schema_version:1,kind:'bio_annotation',run_id:'annrun',parent_processed_source:processedFixture.source,reference_id:'monaco',workflow_version:'bio_annotation_v1',engine_version:'visium_explore_v1.0.0',environment_digest:'e'.repeat(64),output_language:'en'}
const task={...runFixture.task,id:'annotationtask',task_type:'bio_annotation',status:'running',display_status:'computing',input_version:input}
it('accepts independent annotation tasks and rejects mixed project or base-result identities',()=>{
 expect(isTask(task,'p1')).toBe(true)
 expect(isTask({...task,input_version:{...input,parent_processed_source:{...processedFixture.source,project_id:'p2'}}},'p1')).toBe(false)
 expect(isTask({...task,result_bio_processed_dataset_version_id:'processed1'},'p1')).toBe(false)
 expect(sameInputVersion(input as never,{...input,reference_id:'other'} as never)).toBe(false)
 expect(sameInputVersion(input as never,{...input,parent_processed_source:{...processedFixture.source,manifest_sha256:'f'.repeat(64)}} as never)).toBe(false)
})
it('validates independent annotation workspaces and provides a route back to the fixed candidate workspace',()=>{
 const workspace={task,source:{file_id:null,filename:'SingleR',analysis_run_id:null,is_current:true},wait:null,allowed_actions:[],artifacts:{figure:null,explanation:null,report:null}}
 expect(isWorkspace(workspace,'p1','annotationtask')).toBe(true)
 expect(isWorkspace({...workspace,source:{...workspace.source,file_id:'file1'}},'p1','annotationtask')).toBe(false)
 render(<BioTaskLinks task={task as never}/>);expect(screen.getByRole('link',{name:'查看细胞候选注释与人工标签'}).getAttribute('href')).toContain('processed=processed1&tab=spatial');cleanup()
})
it('recognizes direct single-cell v3 analysis and child runs without requiring an obsolete QC confirmation',()=>{
 const child={...runFixture.task,status:'running',display_status:'computing',input_version:{...runFixture.task.input_version,workflow_version:'bio_analysis_v3'}}
 expect(isTask(child,'p1')).toBe(true)
})
