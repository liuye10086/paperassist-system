import {webcrypto,createHash} from 'node:crypto'
import {afterEach,expect,it,vi} from 'vitest'
import {canonicalJson,jsonDigest,codepointRange,validFigureVersion,validLiveRequest,validManifest,validReviewContext} from './writingLiveTypes'
import {reviewContext,unsubmittedRequest} from './writingLiveFixtures'
import {validSnapshot,validCandidates,validInput} from './manuscriptTypes'
import {manuscriptFixture} from './manuscriptFixtures'
import {taskFixture} from '../tasks/taskFixtures'
afterEach(()=>vi.unstubAllGlobals())
it('uses canonical JSON text and codepoint ranges, not bare SHA or UTF16 offsets',async()=>{
 vi.stubGlobal('crypto',webcrypto)
 expect(canonicalJson({z:1,a:'中文'})).toBe('{"a":"中文","z":1}')
 expect(await jsonDigest('中文')).toBe(createHash('sha256').update('"中文"').digest('hex'))
 expect(codepointRange('😀SCI文字',2,5)).toEqual({start:1,end:4})
})
it('accepts server v2 numeric occurrences without relaxing legacy paragraph bindings',()=>{
 const snapshot={...manuscriptFixture.versions[0].snapshot,writing_provenance:{schema_version:2,composition_version:2,provider_provenance:'synthetic_fixture',verification_status:'scientific_reviewed_language_pending'},methods:[{id:'a',text:'n=12',origin:'model_generated',source_ids:['s1'],citations:[],numeric_bindings:[{occurrence:0,value:'12',kind:'study',source_alias:'s1',fact_path:'/n',evidence_id:null}]}]}
 expect(validSnapshot(snapshot,'p1')).toBe(true)
 expect(validSnapshot({...snapshot,writing_provenance:undefined},'p1')).toBe(false)
 expect(validSnapshot({...snapshot,writing_provenance:{...snapshot.writing_provenance,composition_version:3}},'p1')).toBe(false)
})
it('allows generated figure language versions in initial source selection',()=>{
 const source={kind:'figure_language_version',id:'fv1',file_id:'f1',role:'image_observation'}
 expect(validInput({...manuscriptFixture.versions[0].input,sources:[source]})).toBe(true)
 expect(validCandidates({items:[{...source,label:'English figure',version:null,allowed_roles:['image_observation'],download_url:'/api/v1/projects/p1/manuscript-figure-language-versions/fv1/download'}],citation_drafts:[],methods_fields:[]},'p1')).toBe(true)
})
it('rejects mismatched v2 workflow and unsupported provider provenance',()=>{
 const input={schema_version:2,base_revision:1,mode:'full_draft',target_section:null,output_language:'en',instructions:'',keywords:[],acknowledgements:'',selected_source_ids:[],selected_evidence_ids:[]}
 const request={schema_version:2,id:'t1',project_id:'p1',manuscript_id:'m1',base_revision:1,input,task:{...taskFixture,task_type:'manuscript_writing',phase:'write',input_version:{kind:'manuscript_writing',base_version_id:'v1',base_revision:1,output_language:'en',workflow_version:'manuscript_writing_v2'}},candidate:null,published_revision:null,real_calls_enabled:false,model_calls:[]}
 expect(validLiveRequest(request,'p1','m1')).toBe(true)
 expect(validLiveRequest({...request,schema_version:3},'p1','m1')).toBe(false)
 expect(validLiveRequest({...request,task:{...request.task,input_version:{...request.task.input_version,workflow_version:'manuscript_writing_v1'}}},'p1','m1')).toBe(false)
 expect(validLiveRequest({...request,model_calls:[{id:'c1',bundle_id:'b1',authorization_id:'a1',logical_task_id:'l1',provider_provenance:'verified'}]},'p1','m1')).toBe(false)
})
it('accepts the real figure text_manifest byte SHA contract and rejects foreign download paths',()=>{
 const v={schema_version:1,id:'fv1',output_language:'en',mode:'local_boxplot',original:{kind:'figure',id:'f1',file_id:'file1',sha256:'a'.repeat(64)},sha256:'b'.repeat(64),snapshot_sha256:'c'.repeat(64),data_fingerprint:'d'.repeat(64),geometry_fingerprint:'e'.repeat(64),text_manifest:[{location:'title',text:'Test',sha256:'f'.repeat(64)}],title:'Test',caption:'Test',download_url:'/api/v1/projects/p1/manuscript-figure-language-versions/fv1/download'}
 expect(validFigureVersion(v,'p1')).toBe(true);expect(validFigureVersion(v,'p2')).toBe(false)
})
it('rejects incomplete claim evidence material and review contexts that could crash the reviewer',()=>{
 expect(validManifest({sources:{},evidence:{e1:{evidence_id:'e1',binding:{project_reference_id:'r1',metadata_version_id:'m1',evidence:[{}]}}}})).toBe(false)
 expect(validReviewContext({...reviewContext,required_paragraph_ids:['absent:1']},'p1','w1')).toBe(false)
 expect(validReviewContext({...reviewContext,required_paragraph_ids:['title:1','title:1']},'p1','w1')).toBe(false)
})

it.each(['reserved','released'] as const)('reads %s calls before supplier submission without accepting unknown provenance',status=>{
 const request=unsubmittedRequest(status);expect(validLiveRequest(request,'p1','m1')).toBe(true)
 expect(validLiveRequest({...request,model_calls:[{...request.model_calls[0],provider_provenance:'unexpected'}]},'p1','m1')).toBe(false)
})
