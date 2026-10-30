import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ProjectManuscripts from './ProjectManuscripts'
import ManuscriptPreview from './ManuscriptPreview'
import ManuscriptWriting from './ManuscriptWriting'
import ManuscriptReview from './ManuscriptReview'
import {reviewContext} from './reviewFixtures'
import {taskFixture} from '../tasks/taskFixtures'
import {setLocale} from '../../shared/i18n'
import {candidatesFixture,manuscriptFixture,snapshotFixture} from './manuscriptFixtures'
import {emptyInput,validInput,validSnapshot,type Snapshot,type ManuscriptVersion} from './manuscriptTypes'
const profile={revision:2,school:'测试学校',department:'',major:'',degree_type:'硕士',education_level:'研究生',applicable_version:'2026',bound_confirmation_id:'confirm1'}
const chapters=[{id:'chapter-method',title:'第二章 独立方法',level:1,purpose:'materials_and_methods',output_language:'en',result_group_ids:[]},{id:'chapter-result',title:'第三章 实验结果',level:2,purpose:'results',output_language:'zh-CN',result_group_ids:['g1']}]
const school={schema_version:1,profile,template_version_id:'template1',confirmation_id:'confirm1',confirmation_sha256:'a'.repeat(64),confirmation:{id:'confirm1',chapters:chapters.map(({id,title,level})=>({id,title,level}))},source_files:[],chapters}
const snapshot={...snapshotFixture,output_language:'zh-CN',thesis_context:school,sections:chapters.map((c,i)=>({...c,paragraphs:[{id:`p${i}`,text:i?'学校结果正文':'Frozen school method',origin:'user_provided',source_ids:[],citations:[]}]})),results_groups:[{id:'g1',title:'固定分组',paragraphs:[],figures:[],tables:[{id:'t1',title:'独立表格',columns:['值'],rows:[['待补充']],source_ids:[]}]}],school_content_report:{rules_version:'school_v1',issues:[],can_publish:true,scientifically_verified:false}} as unknown as Snapshot
const readiness={ready:true,blocking_reasons:[],profile,confirmation_id:'confirm1',chapters:chapters.map(({id,title,level})=>({id,title,level})),purposes:['abstract','introduction','materials_and_methods','results','discussion','conclusion','references','acknowledgements','manual','other'],template_source_file_ids:[]}
const props={projectId:'p1',researchTopic:'学校研究',outputLanguage:'zh-CN' as const,active:true,projectType:'thesis' as const}
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it('accepts frozen school chapters but rejects metadata order mismatches',()=>{
 expect(validSnapshot(snapshot,'p1')).toBe(true)
 expect(validSnapshot({...snapshot,school_content_report:undefined},'p1')).toBe(false)
 expect(validSnapshot({...snapshot,sections:[...snapshot.sections!].reverse()},'p1')).toBe(false)
})
it('previews school order, actual titles and per-chapter language with a table only once',()=>{
 render(<ManuscriptPreview snapshot={snapshot}/>)
 const headings=screen.getAllByRole('heading').map(n=>n.textContent)
 expect(headings.indexOf(chapters[0].title)).toBeGreaterThan(-1)
 expect(headings.indexOf(chapters[0].title)).toBeLessThan(headings.indexOf(chapters[1].title))
 expect(screen.getAllByRole('table')).toHaveLength(1)
 expect(screen.getByText('Frozen school method').closest('[lang]')?.getAttribute('lang')).toBe('en')
 expect(screen.queryByRole('heading',{name:'材料与方法'})).toBeNull()
})
it('requires explicit school purposes and freezes mapping in confirmed chapter order',async()=>{
 const fetcher=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('/candidates')?{...candidatesFixture,project_type:'thesis',thesis:readiness}:url.endsWith('/preview')?snapshot:{items:[]}));vi.stubGlobal('fetch',fetcher)
 render(<ProjectManuscripts {...props}/>)
 const first=await screen.findByRole('group',{name:chapters[0].title})
 expect(within(first).getByLabelText('内容用途')).toHaveProperty('value','')
 fireEvent.click(screen.getByRole('button',{name:'预览事实稿'}));expect(fetcher.mock.calls.some(([url])=>url.endsWith('/preview'))).toBe(false)
 fireEvent.change(within(first).getByLabelText('内容用途'),{target:{value:'materials_and_methods'}})
 const second=screen.getByRole('group',{name:chapters[1].title});fireEvent.change(within(second).getByLabelText('内容用途'),{target:{value:'results'}})
 fireEvent.change(within(first).getByLabelText('章节语言'),{target:{value:'en'}})
 fireEvent.click(screen.getByRole('button',{name:'预览事实稿'}))
 await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>url.endsWith('/preview'))).toBe(true))
 const call=fetcher.mock.calls.find(([url])=>url.endsWith('/preview'))!
 expect(JSON.parse(String(call[1]?.body)).thesis).toEqual({confirmation_id:'confirm1',profile_revision:2,chapter_mappings:[{chapter_id:'chapter-method',purpose:'materials_and_methods',output_language:'en',result_group_ids:[]},{chapter_id:'chapter-result',purpose:'results',output_language:'project',result_group_ids:[]}]})
})
it('keeps missing school binding visible and blocks submission with a school template link',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/candidates')?{...candidatesFixture,project_type:'thesis',thesis:{...readiness,ready:false,confirmation_id:null,blocking_reasons:['请先绑定学校模板'],chapters:[]}}:{items:[]})))
 render(<ProjectManuscripts {...props}/>);expect(await screen.findByText('请先绑定学校模板')).toBeTruthy();expect(screen.getByRole('link',{name:'配置学校模板'}).getAttribute('href')).toContain('section=school-templates');expect(screen.getByRole('button',{name:'预览事实稿'}).matches(':disabled')).toBe(true)
})
it('uses actual school rewrite ids and exposes controlled writing for the school contract',async()=>{
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{if(init?.method)throw Error('network');return Response.json({items:[]})});vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptWriting projectId="p1" manuscriptId="m1" version={{...manuscriptFixture.versions[0],snapshot} as unknown as ManuscriptVersion} onPublished={vi.fn()}/>);
 expect(screen.getByRole('button',{name:'受控写作与人工审核'})).toBeTruthy()
 fireEvent.change(screen.getByLabelText('写作方式'),{target:{value:'rewrite_section'}})
 fireEvent.change(screen.getByLabelText('目标章节'),{target:{value:'chapter-method'}})
 fireEvent.change(screen.getByLabelText('自由写作要求'),{target:{value:'核对方法'}})
 fireEvent.click(screen.getByRole('button',{name:'发起章节重写'}));await screen.findByRole('alert')
 expect(JSON.parse(String(fetcher.mock.calls.find(([,init])=>init?.method)?.[1]?.body)).target_section).toBe('chapter-method')
})

it('opens fixed school export while keeping controlled writing available',async()=>{
 const version={...manuscriptFixture.versions[0],snapshot,input:{...manuscriptFixture.versions[0].input,thesis:{confirmation_id:'confirm1',profile_revision:2,chapter_mappings:chapters.map(c=>({chapter_id:c.id,purpose:c.purpose,output_language:c.output_language,result_group_ids:c.result_group_ids}))}}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/candidates')?{...candidatesFixture,project_type:'thesis',thesis:readiness}:url.endsWith('/manuscripts')?{items:[{...manuscriptFixture,versions:[version]}]}:url.includes('/context?')?reviewContext:{items:[]})))
 render(<ProjectManuscripts {...props}/>);fireEvent.click(await screen.findByRole('button',{name:'查看版本 1'}))
 expect(await screen.findByRole('heading',{name:'学校固定版本导出'})).toBeTruthy()
 expect(screen.getByRole('link',{name:'下载 DOCX'})).toBeTruthy();expect(screen.getByRole('button',{name:'受控写作与人工审核'})).toBeTruthy()
})
it('shows actual chapter titles in review and finds methods by purpose',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/context?')?{...reviewContext,facts:[],relationships:{...reviewContext.relationships,paragraphs:snapshot.sections!.map(s=>({id:s.paragraphs[0].id,section_id:s.id,purpose:s.purpose,source_ids:[],figure_ids:[]})),methods:[{id:'p0',section_id:'chapter-method',purpose:'materials_and_methods',source_ids:[],figure_ids:[]}],figures:[]}}:{items:[]})))
 render(<ManuscriptReview projectId="p1" manuscriptId="m1" version={{...manuscriptFixture.versions[0],snapshot} as unknown as ManuscriptVersion} currentRevision={1} onPublished={vi.fn()}/>);
 expect(await screen.findByRole('heading',{name:'第二章 独立方法 · 段落 1'})).toBeTruthy()
 fireEvent.click(screen.getByText('研究关联'));fireEvent.click(screen.getByRole('button',{name:'添加关联'}))
 expect(within(screen.getByLabelText('关联方法')).getByRole('option',{name:'Frozen school method'})).toBeTruthy()
})
it('renders readable Chinese readiness codes and English chapter controls',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/candidates')?{...candidatesFixture,project_type:'thesis',thesis:{...readiness,ready:false,blocking_reasons:['school_template_not_bound']}}:{items:[]})))
 const view=render(<ProjectManuscripts {...props}/>);await waitFor(()=>expect(screen.queryByText('正在读取稿件资料……')).toBeNull());expect(screen.getByText('请先绑定学校模板')).toBeTruthy()
 view.unmount();setLocale('en');vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/candidates')?{...candidatesFixture,project_type:'thesis',thesis:readiness}:{items:[]})))
 render(<ProjectManuscripts {...props}/>);expect(await screen.findAllByLabelText('Content purpose')).toHaveLength(2)
})
it('does not offer manual chapters for model rewrite',()=>{
 const manual={...snapshot,thesis_context:{...school,chapters:[{...chapters[0],purpose:'manual'}]},sections:[{...snapshot.sections![0],purpose:'manual'}]} as unknown as Snapshot
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[]})))
 render(<ManuscriptWriting projectId="p1" manuscriptId="m1" version={{...manuscriptFixture.versions[0],snapshot:manual} as unknown as ManuscriptVersion} onPublished={vi.fn()}/>);
 expect(screen.queryByRole('option',{name:'指定章节重写'})).toBeNull()
})
it('blocks school publication when the content report has a hard missing chapter',async()=>{
 const issue={id:'school:missing',category:'structure',severity:'error',location:'chapter-method',message:'学校必需章节缺少正文',actual:[],expected:'body',source_evidence:[],rules_version:'school_v1'}
 const candidate={...snapshot,school_content_report:{rules_version:'school_v1',issues:[issue],can_publish:false,scientifically_verified:false}}
 const request={id:'w1',project_id:'p1',manuscript_id:'m1',base_revision:1,input:{base_revision:1,mode:'full_draft',target_section:null,instructions:'',keywords:[],acknowledgements:''},task:{...taskFixture,id:'w1',project_id:'p1',task_type:'manuscript_writing',phase:'write',status:'succeeded',display_status:'succeeded',input_version:{kind:'manuscript_writing',base_version_id:'v1',base_revision:1,output_language:'zh-CN',workflow_version:'manuscript_writing_v1'}},candidate,published_revision:null,real_calls_enabled:false,preservation_check:{non_target_sections_preserved:true}}
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[request]})))
 render(<ManuscriptWriting projectId="p1" manuscriptId="m1" version={{...manuscriptFixture.versions[0],snapshot} as unknown as ManuscriptVersion} onPublished={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'预览写作候选'}));expect(await screen.findByText(issue.message)).toBeTruthy();expect(screen.getByRole('button',{name:'确认发布为不可变新版本'}).matches(':disabled')).toBe(true)
})

it('assigns result groups explicitly to one school results chapter and removes stale group assignments',async()=>{
 const ready={...readiness,chapters:[...readiness.chapters,{id:'chapter-extra',title:'第四章 补充结果',level:1}]}
 const fetcher=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('/candidates')?{...candidatesFixture,project_type:'thesis',thesis:ready}:url.endsWith('/preview')?snapshot:{items:[]}));vi.stubGlobal('fetch',fetcher)
 render(<ProjectManuscripts {...props}/>);await screen.findByRole('group',{name:chapters[0].title})
 for(const c of ready.chapters)fireEvent.change(within(screen.getByRole('group',{name:c.title})).getByLabelText('内容用途'),{target:{value:c.id==='chapter-method'?'materials_and_methods':'results'}})
 fireEvent.click(screen.getByRole('button',{name:'添加 Results 分组'}));fireEvent.change(screen.getByLabelText('分组标题'),{target:{value:'学校分组'}})
 const result=screen.getByRole('group',{name:chapters[1].title}),extra=screen.getByRole('group',{name:'第四章 补充结果'})
 fireEvent.click(within(result).getByRole('checkbox',{name:'学校分组'}));expect(within(extra).getByRole('checkbox',{name:'学校分组'}).matches(':disabled')).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'移除分组'}));fireEvent.click(screen.getByRole('button',{name:'预览事实稿'}));await waitFor(()=>expect(fetcher.mock.calls.some(([u])=>u.endsWith('/preview'))).toBe(true))
 const body=JSON.parse(String(fetcher.mock.calls.find(([u])=>u.endsWith('/preview'))?.[1]?.body));expect(body.thesis.chapter_mappings.every((m:{result_group_ids:string[]})=>m.result_group_ids.length===0)).toBe(true)
})
it('rejects a candidate that changes the frozen school confirmation',async()=>{
 const candidate={...snapshot,thesis_context:{...school,confirmation_id:'other-confirmation'}}
 const request={id:'w1',project_id:'p1',manuscript_id:'m1',base_revision:1,input:{base_revision:1,mode:'full_draft',target_section:null,instructions:'',keywords:[],acknowledgements:''},task:{...taskFixture,id:'w1',project_id:'p1',task_type:'manuscript_writing',phase:'write',status:'succeeded',display_status:'succeeded',input_version:{kind:'manuscript_writing',base_version_id:'v1',base_revision:1,output_language:'zh-CN',workflow_version:'manuscript_writing_v1'}},candidate,published_revision:null,real_calls_enabled:false,preservation_check:{non_target_sections_preserved:true}}
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[request]})))
 render(<ManuscriptWriting projectId="p1" manuscriptId="m1" version={{...manuscriptFixture.versions[0],snapshot} as unknown as ManuscriptVersion} onPublished={vi.fn()}/>);
 expect(await screen.findByRole('alert')).toBeTruthy();expect(screen.queryByRole('button',{name:'预览写作候选'})).toBeNull()
})

it('keeps an unauthorized school writing request waiting without inventing a candidate',async()=>{
 const request={id:'w1',project_id:'p1',manuscript_id:'m1',base_revision:1,input:{base_revision:1,mode:'full_draft',target_section:null,instructions:'',keywords:[],acknowledgements:''},task:{...taskFixture,id:'w1',project_id:'p1',task_type:'manuscript_writing',phase:'write',status:'waiting_confirmation',display_status:'waiting_confirmation',error_code:'manuscript_writing_not_authorized',reason_code:'model_authorization_required',input_version:{kind:'manuscript_writing',base_version_id:'v1',base_revision:1,output_language:'zh-CN',workflow_version:'manuscript_writing_v1'}},candidate:null,published_revision:null,real_calls_enabled:false,preservation_check:null}
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[request]})))
 render(<ManuscriptWriting projectId="p1" manuscriptId="m1" version={{...manuscriptFixture.versions[0],snapshot} as unknown as ManuscriptVersion} onPublished={vi.fn()}/>);
 expect(await screen.findByText('等待模型授权；本环境不会发起真实调用。')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'预览写作候选'}));expect(screen.getByText('任务尚无可预览候选；请查看任务状态。')).toBeTruthy();expect(screen.queryByRole('button',{name:'确认发布为不可变新版本'})).toBeNull()
})

it('accepts the school report wrapper with common review issue rule versions and renders references once',()=>{
 const issue={id:'uncertainty:school',category:'uncertainty',severity:'human_review',location:'school:content',message:'语义须核对',actual:null,expected:null,source_evidence:[],rules_version:'manuscript-review-v1'}
 expect(validSnapshot({...snapshot,school_content_report:{rules_version:'school-content-v1',issues:[issue],can_publish:true,scientifically_verified:false}},'p1')).toBe(true)
 const ref={id:'school-refs',title:'参考资料',level:1,purpose:'references',output_language:'zh-CN',result_group_ids:[],paragraphs:[{id:'reference:1',text:'Reference text only once',origin:'literature',source_ids:[],citations:[]}]}
 render(<ManuscriptPreview snapshot={{...snapshot,sections:[...snapshot.sections!,ref],references:[{number:1,text:'Reference text only once',project_reference_id:'ref1'}]} as unknown as Snapshot}/>);
 expect(screen.getAllByText('Reference text only once')).toHaveLength(1)
})

it('preserves the old SCI input contract by omitting thesis and rejects explicit null',()=>{
 const input=emptyInput('SCI control','en')
 expect(Object.hasOwn(input,'thesis')).toBe(false);expect(validInput(input)).toBe(true)
 expect(validInput({...input,thesis:null})).toBe(false)
})

it.each([1,2])('reads revision %s while other school revisions use different chapter ids and waiting rewrites',async(revision)=>{
 const oldChapters=chapters.map(c=>({...c,id:'old-'+c.id})),newChapters=chapters.map(c=>({...c,id:'new-'+c.id}))
 const makeSnapshot=(current:typeof chapters)=>({...snapshot,thesis_context:{...school,chapters:current},sections:current.map((c,i)=>({...c,paragraphs:snapshot.sections![i].paragraphs}))}) as unknown as Snapshot
 const request=(base_revision:number,target:string)=>({id:'w'+base_revision,project_id:'p1',manuscript_id:'m1',base_revision,input:{base_revision,mode:'rewrite_section',target_section:target,instructions:'核对本版本方法',keywords:[],acknowledgements:''},task:{...taskFixture,id:'w'+base_revision,project_id:'p1',task_type:'manuscript_writing',phase:'write',status:'waiting_confirmation',display_status:'waiting_confirmation',error_code:'manuscript_writing_not_authorized',reason_code:'model_authorization_required',input_version:{kind:'manuscript_writing',base_version_id:'v'+base_revision,base_revision,output_language:'zh-CN',workflow_version:'manuscript_writing_v1'}},candidate:null,published_revision:null,real_calls_enabled:false,preservation_check:null})
 const items=[request(1,oldChapters[0].id),request(2,newChapters[0].id)]
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items})))
 render(<ManuscriptWriting projectId="p1" manuscriptId="m1" version={{...manuscriptFixture.versions[0],id:'v'+revision,revision,snapshot:makeSnapshot(revision===1?oldChapters:newChapters)} as unknown as ManuscriptVersion} onPublished={vi.fn()}/>);
 expect(await screen.findByText('等待模型授权；本环境不会发起真实调用。')).toBeTruthy()
 expect(screen.queryByRole('alert')).toBeNull();expect(screen.getAllByRole('button',{name:'预览写作候选'})).toHaveLength(1)
 fireEvent.click(screen.getByRole('button',{name:'刷新写作任务'}));await waitFor(()=>expect(screen.queryByRole('alert')).toBeNull())
})
