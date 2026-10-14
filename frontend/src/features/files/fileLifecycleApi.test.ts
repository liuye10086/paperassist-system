import {afterEach,expect,test,vi} from 'vitest'
import {assessmentFixture,countKeys} from './lifecycleFixtures'
import {isAssessment,isImpactTask,isPage,isReceipt,lifecycleBase,lifecycleRequest,reasonLabels} from './fileLifecycleApi'
import {setApiSession} from '../../shared/api/client'
import {setLocale,translate} from '../../shared/i18n'
afterEach(()=>{vi.unstubAllGlobals();setLocale('zh-CN')})
test('strict assessment accepts historical text identities and rejects malformed or cross-file scopes',()=>{
 const value=assessmentFixture('old file:一')
 expect(isAssessment(value,'old file:一','delete')).toBe(true)
 for(const broken of [{...value,file_id:'foreign'},{...value,action:'reparse'},{...value,counts:[]},{...value,counts:{...value.counts,tasks:-1}},{...value,counts:{}},{...value,assessment_revision:'secret'},{...value,latest_versions:{...value.latest_versions,dataset_versions:[{id:['x'],version:1,sheet_index:0}]}},{...value,reasons:[{code:'unknown'}]},{...value,download_url:'https://foreign'},{...value,original_integrity:'missing'},{...value,can_reparse:false},{...value,reasons:[{code:'internal_testing_retention'},{code:'active_tasks'}]},{...value,reasons:[{code:'internal_testing_retention'},{code:'internal_testing_retention'}]}])expect(isAssessment(broken,'old file:一','delete')).toBe(false)
 expect(Object.keys(value.counts)).toEqual(countKeys)
 expect(lifecycleBase('old project/中文','old file:一')).toBe('/api/v1/projects/old%20project%2F%E4%B8%AD%E6%96%87/files/old%20file%3A%E4%B8%80/lifecycle')
})
test('task and full-total history validators reject forged URLs, unsafe IDs, bad pages and receipt scope',()=>{
 const a=assessmentFixture(),r={id:'old request',file_id:'f',reason:'reason',status:'retained',requested_at:'2026-10-13T00:00:00Z',resolved_at:'2026-10-13T00:00:00Z',policy_version:a.policy_version,assessment_revision:a.assessment_revision,assessment:a}
 expect(isReceipt(r,'f')).toBe(true);expect(isReceipt({...r,assessment:{...a,file_id:'foreign'}},'f')).toBe(false)
 expect(isPage({items:[r],total:21,page:3,page_size:10},3,(v):v is typeof r=>isReceipt(v,'f'))).toBe(true)
 expect(isPage({items:[r],total:0,page:3,page_size:10},3,(v):v is typeof r=>isReceipt(v,'f'))).toBe(false)
 const task={id:'historic task',origin:'task',task_type:'parse_file',status:'failed',created_at:r.requested_at,sources:[{kind:'parse_versions',id:'old version',version:1}],has_newer_version:true,source_status:'newer_attempt_available',stale_reasons:['newer_attempt_available']}
 expect(isImpactTask(task)).toBe(true);expect(isImpactTask({...task,project_id:'foreign'})).toBe(false);expect(isImpactTask({...task,url:'https://foreign'})).toBe(false);expect(isImpactTask({...task,sources:[{kind:'parse_versions',id:{bad:true},version:1}]})).toBe(false)
})
test.each(['response','body'])('rejects previous account delayed %s despite ignored abort',async phase=>{
 setApiSession('account-a');let resolve!:(value:unknown)=>void;const waiting=new Promise(resolvePromise=>{resolve=resolvePromise})
 const response=Response.json(assessmentFixture());if(phase==='body')response.json=()=>waiting
 vi.stubGlobal('fetch',vi.fn(()=>phase==='response'?waiting:Promise.resolve(response)))
 const pending=lifecycleRequest('/api/v1/projects/p/files/f/lifecycle/assessment?action=delete',new AbortController().signal,()=>{},(v):v is ReturnType<typeof assessmentFixture>=>isAssessment(v,'f','delete'))
 await Promise.resolve();setApiSession('account-b');resolve(phase==='response'?response:assessmentFixture())
 await expect(pending).rejects.toMatchObject({name:'AbortError'})
})
test('all lifecycle reasons have Chinese and English user prose',()=>{for(const label of Object.values(reasonLabels)){setLocale('zh-CN');expect(translate(label)).toBe(label);setLocale('en');expect(translate(label)).not.toBe(label)}})
test('lifecycle wrapper rejects an external request target before fetch',async()=>{const fetch=vi.fn(async()=>Response.json(assessmentFixture()));vi.stubGlobal('fetch',fetch);await expect(lifecycleRequest('https://foreign.test/assessment',new AbortController().signal,()=>{},(v):v is ReturnType<typeof assessmentFixture>=>isAssessment(v,'f','delete'))).rejects.toThrow();expect(fetch).not.toHaveBeenCalled()})
