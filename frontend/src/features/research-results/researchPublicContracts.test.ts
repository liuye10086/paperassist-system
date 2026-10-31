import {it,expect} from 'vitest'
import {snapshotFixture,manuscriptFixture} from '../manuscripts/manuscriptFixtures'
import {validSnapshot,validManuscript} from '../manuscripts/manuscriptTypes'
import {taskFixture} from '../tasks/taskFixtures'
import {isTask} from '../tasks/taskTypes'
const snapshot={...snapshotFixture,sources:[{kind:'research_finding_version',id:'finding',role:'user_results',label:'Fixed findings',sha256:'a'.repeat(64),locator:{kind:'object'},source_file_ids:['f1'],content:{facts:[]}}]}
it('accepts the actual typed research projection without a fabricated file_id',()=>{expect(validSnapshot(snapshot,'p1')).toBe(true);expect(validSnapshot({...snapshot,sources:[{...snapshot.sources[0],sha256:'bad'}]},'p1')).toBe(false)})
it('accepts the independently published schema 2 research request',()=>{expect(validManuscript({...manuscriptFixture,versions:[{...manuscriptFixture.versions[0],snapshot,input:{schema_version:2,kind:'research_results_methods',candidate_id:'candidate',delivery_id:'delivery',expected_revision:0,title:'Research',output_language:'zh-CN',thesis:null}}]},'p1')).toBe(true)})
it.each(['research_figure','research_report','research_fact_draft'])('accepts fixed offline task input %s',kind=>{expect(isTask({...taskFixture,task_type:kind,input_version:{kind,schema_version:1,workflow_version:kind==='research_fact_draft'?'research_results_methods_v1':kind+'_v1',source_sha256:'a'.repeat(64),output_language:'zh-CN',real_model_calls:false,real_network_calls:false}},'p1','t1')).toBe(true)})
