// Customer-page journal fixtures (B03 task 9). Every identifier is a UUID or a real-looking hash so that the
// technical-text scanner can catch full values and 8/12-character cuts; all of them are listed in systemIds.
import {taskFixture} from '../tasks/taskFixtures'

export const projectId='3f6b2a10-8c4d-4e5f-9a01-b2c3d4e5f607'
export const profileId='a1b2c3d4-0e1f-4a2b-8c3d-4e5f60718293'
export const guideId='b2c3d4e5-1f20-4b3c-9d4e-5f6071829304'
export const guide2Id='c3d4e5f6-2031-4c4d-8e5f-607182930415'
export const recommendationId='d4e5f607-3142-4d5e-9f60-718293041526'
export const targetId='e5f60718-4253-4e6f-8071-829304152637'
export const checkId='f6071829-5364-4f70-9182-930415263748'
export const adaptationId='07182930-6475-4081-a293-041526374859'
export const manuscriptId='18293041-7586-4192-b304-15263748596a'
export const versionId='29304152-8697-42a3-8415-263748596a7b'
export const outputVersionId='3a415263-97a8-43b4-9526-3748596a7b8c'
export const recommendationTaskId='4b526374-a8b9-44c5-a637-48596a7b8c9d'
export const checkTaskId='5c637485-b9ca-45d6-b748-596a7b8c9dae'
export const adaptationTaskId='6d748596-cadb-46e7-8859-6a7b8c9daebf'
export const outputTaskId='7e8596a7-dbec-47f8-996a-7b8c9daebfc0'
export const materialId='8f96a7b8-ecfd-4809-aa7b-8c9daebfc0d1'
export const fileId='90a7b8c9-fd0e-491a-8b8c-9daebfc0d1e2'
export const materialItemId='a1b8c9da-0e1f-4a2b-9c9d-aebfc0d1e2f3'
export const ruleId='b2c9daeb-1f20-4b3c-8dae-bfc0d1e2f304'
export const rule2Id='c3daebfc-2031-4c4d-9ebf-c0d1e2f30415'
export const userId='d4ebfc0d-3142-4d5e-8fc0-d1e2f3041526'
export const requirementsHash='5d1f0c2e9a7b3c4d6e8f0a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f'
export const previewHash='6e2a1d3f0b8c4d5e7f9a1b2c3d4e5f6071829304b5c6d7e8f90a1b2c3d4e5f6a'
export const candidateHash='7f3b2e4a1c9d5e6f8a0b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f6a7b'
export const bodyHash='80c4a3f5b2d0e6f7a9b1c3d4e5f6071829304a5b6c7d8e9f0a1b2c3d4e5f6a7b8'
export const systemIds=[projectId,profileId,guideId,guide2Id,recommendationId,targetId,checkId,adaptationId,manuscriptId,versionId,outputVersionId,recommendationTaskId,checkTaskId,adaptationTaskId,outputTaskId,materialId,fileId,materialItemId,ruleId,rule2Id,userId,requirementsHash,previewHash,candidateHash,bodyHash]
// Raw values that must not appear as whole words on customer journal pages.
export const rawValues=['succeeded','failed','queued','running','available','allowed','user_provided','synthetic','revision','target','check','guide','requirements','parent','journal_display_v1','research','narrative_review']
export const time='2026-11-19T03:20:00Z'

export const material={kind:'document_version' as const,id:materialId,file_id:fileId,label:'Author instructions.docx'}
const evidence={value:['cardiology'],status:'verified' as const,quote:'Scope: cardiology',location:'line:2',source_type:'user_provided',source_url:'https://journal.example.org/scope'}
export const profile={id:profileId,project_id:projectId,name:'Frontiers in Cardiovascular Medicine',source_type:'user_provided' as const,source_text:'Scope: cardiology',source_url:'https://journal.example.org/scope',official_url:'https://journal.example.org',source_status:'available' as const,verified_on:'2026-11-18',conditions:'客户提供',permission:'客户提供的指南',synthetic:false,verification_level:'user_material_only',created_at:time,fields:{topics:evidence},material:{...material,content:{items:[{id:materialItemId,text:'Scope: cardiology'}]}}}
export const rule={id:ruleId,key:'word_limit' as const,value:3000,status:'known' as const,quote:'Maximum body words: 3000',location:'line:1',article_type:'research',count_method:'en_whitespace_body' as const,origin:'journal',note:''}
export const rule2={...rule,id:rule2Id,value:2500,quote:'Body words at most 2500',origin:'unit'}
export const guide={id:guideId,project_id:projectId,profile_id:profileId,name:'Author guidelines',source_type:'user_provided' as const,source_text:'Maximum body words: 3000',source_url:'https://journal.example.org/guide',official_url:'https://journal.example.org',source_version:'2026 版',acquired_on:'2026-11-18',verified_on:'2026-11-18',article_types:['research'],conditions:'客户提供',permission:'客户提供的指南',permission_status:'allowed' as const,source_status:'available' as const,requirements:[rule],extracted_requirements:[{...rule,id:`extracted:${ruleId}`}],extract:true,requirements_version:requirementsHash,synthetic:false,verification_level:'user_material_only',created_at:time,material,
 retrieval:{requested_url:'https://journal.example.org/guide',final_url:'https://journal.example.org/guide',fetched_at:time,body_sha256:bodyHash,bytes:2048,content_type:'text/html',etag:`"${candidateHash}"`,last_modified:null,official_verification:'not_established' as const}}
export const guide2={...guide,id:guide2Id,source_version:'2026 单位版',requirements:[rule2],extracted_requirements:[],retrieval:undefined,material:null}
const scoped=(r:typeof rule,source:{id:string;source_version:string})=>({...r,id:`${source.id}:${r.id}`,source_id:source.id,source_version:source.source_version})
export const recommendation={id:recommendationId,created_at:time,
 input_snapshot:{project_id:projectId,kind:'journal_recommendation' as const,recommendation_id:recommendationId,workflow_version:'journal_recommendation_v1' as const,
  research:{limit:3,title:'心衰队列研究',topics:['cardiology'],article_type:'research',abstract:'摘要',main_results:'主要结果',domain:'',discipline:'',language:'en',oa:null,budget:null,unit_requirements:[],hard_filters:['topics'],materials:[],manuscript:{id:manuscriptId,revision:1}},
  materials:[{...material,content:{items:[{id:materialItemId,text:'Scope: cardiology'}]}}],profiles:[profile],manuscript:{id:manuscriptId,revision:1,version_id:versionId},real_model_calls:false as const,real_network_calls:false as const},
 task:{...taskFixture,id:recommendationTaskId,project_id:projectId,task_type:'journal_recommendation',phase:'plan',status:'succeeded',display_status:'succeeded',reason_code:null,error_code:null,input_version:{kind:'journal_recommendation',recommendation_id:recommendationId,workflow_version:'journal_recommendation_v1'}},
 result:{candidates:[{profile,reasons:[{field:'topics',message:'明确标签匹配：cardiology',state:'match' as const,evidence}],matched_tag_count:1,preference_match_count:0}],pending_verification:[],excluded:[],candidate_total:1,limitations:[],real_model_calls:false as const,real_network_calls:false as const}}
export const target={id:targetId,project_id:projectId,recommendation_id:recommendationId,profile_id:profileId,guide_id:guideId,requirements_version:requirementsHash,article_type:'research',additional_guide_ids:[guide2Id],resolutions:[],
 candidate:recommendation.result.candidates[0],guide,additional_guides:[guide2],selected_requirements:[rule],
 conflicts:[{key:'word_limit',requirements:[scoped(rule,guide),scoped(rule2,guide2)],reason:'等待单位核对',deferred:true}],
 decisions:[{key:'word_limit',selected_id:`${guideId}:${ruleId}`,preserved_ids:[`${guide2Id}:${rule2Id}`],reason:'以期刊要求为准',evidence:[scoped(rule,guide)]}],
 warnings:[{key:'unit_requirements',message:'单位要求需人工核对',source_id:guide2Id}],synthetic:false,confirmed_by:userId,confirmed_at:time}
const formatInput={kind:'journal_format_check',check_id:checkId,target_id:targetId,guide_id:guideId,requirements_version:requirementsHash,manuscript_version_id:versionId,check_version:1,workflow_version:'journal_format_check_v1'}
export const check={id:checkId,created_at:time,
 task:{...taskFixture,id:checkTaskId,project_id:projectId,task_type:'journal_format_check',phase:'verify',status:'succeeded',display_status:'succeeded',reason_code:null,error_code:null,input_version:formatInput},
 input_snapshot:{id:checkId,project_id:projectId,kind:'journal_format_check' as const,workflow_version:'journal_format_check_v1' as const,target,manuscript:{id:manuscriptId,revision:1,version_id:versionId},check_version:1 as const,public_check_version:2 as const,real_model_calls:false as const,real_network_calls:false as const},
 result:{items:(['length','sections','abstract','illustrations','references'] as const).map((category,i)=>({id:`${checkId}-${i}`,category,key:i===1?'required_sections':'word_limit',status:'pending_verification' as const,actual:i===1?{section_id:'materials_and_methods'}:3200,expected:i===1?['introduction','materials_and_methods']:{max:3000},location:i===1?{section_id:'materials_and_methods'}:'line:1',evidence:[scoped(rule,guide)],suggested_action:'请核对原文',future_automation:'manual',reason:'正文字数超出要求'})),adjustments:[],
  summary:{all_passed:false,counts:{pending_verification:5},meaning:'检查完成不等于全部符合要求'},public_issues:[{id:'numeric:paragraph:1',message:'Reference numbering is not contiguous.',location:`paragraph:${materialItemId}`,actual:4.2,expected:3.2}],synthetic:false,check_version:1 as const,real_model_calls:false as const,real_network_calls:false as const}}
export const manuscripts=[{id:manuscriptId,title:'心衰队列研究稿',versions:[{id:versionId,revision:1,status:'published',created_at:'2026-11-18T09:54:00+08:00',snapshot:{title:'心衰队列研究稿'}}]}]
const sections=['title','abstract','introduction','results','discussion','materials_and_methods','references'].map(section_id=>({section_id,before:{display_name:section_id},after:{display_name:section_id==='materials_and_methods'?'Methods':section_id},changed:section_id==='materials_and_methods'}))
export const preview={target_id:targetId,check_id:checkId,manuscript:{id:manuscriptId,revision:1,version_id:versionId},expected_current_revision:2,preview_sha256:previewHash,sections,
 actions:[{id:ruleId,key:'document_page_line_numbers',before:null,after:{page:true,line:true},evidence:[scoped(rule,guide)],reason:'原文明确要求页码与行号'},{id:rule2Id,key:'body_line_spacing',before:null,after:1.5,evidence:[],reason:'原文明确要求行距'}],
 unexecuted:[{key:'dpi',reason:'许可未知',evidence:[{section_id:'materials_and_methods'}]}],synthetic:false,can_adopt:true,display_version:'journal_display_v1'}
const output={manuscript_id:manuscriptId,version_id:outputVersionId,revision:2,parent_version_id:versionId,task_id:outputTaskId}
export const adaptation={id:adaptationId,created_at:time,
 task:{...taskFixture,id:adaptationTaskId,project_id:projectId,task_type:'journal_adaptation',phase:'verify',status:'failed',display_status:'failed',reason_code:null,error_code:'manuscript_review_blocked',retry_count:0,input_version:{kind:'journal_adaptation',adaptation_id:adaptationId,target_id:targetId,check_id:checkId,manuscript_version_id:versionId,requirements_version:requirementsHash,workflow_version:'journal_adaptation_v1'}},
 input_snapshot:{id:adaptationId,project_id:projectId,kind:'journal_adaptation' as const,workflow_version:'journal_adaptation_v1' as const,target_id:targetId,check_id:checkId,manuscript:{id:manuscriptId,revision:1,version_id:versionId},requirements_version:requirementsHash,expected_current_revision:2,preview_sha256:previewHash,preview,selected_action_ids:[ruleId],synthetic:false,real_model_calls:false as const,real_network_calls:false as const},
 validation:{public_issues:[{id:'numeric:paragraph:1',message:'Reference numbering is not contiguous.',location:`paragraph:${materialItemId}`}],public_check_version:3 as const,candidate_sha256:candidateHash,can_publish:false},
 result:{actual_changes:[preview.actions[0]],unexecuted:preview.unexecuted,public_issues:[{id:'numeric:paragraph:2',message:'Reference numbering is not contiguous.',location:`paragraph:${materialItemId}`}],synthetic:false,display_version:'journal_display_v1',output}}
export const adaptationOutput=output
