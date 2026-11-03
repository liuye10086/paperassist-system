import {StrictMode} from 'react'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ManuscriptPresentation from './ManuscriptPresentation'
import {manuscriptFixture} from './manuscriptFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
const version=manuscriptFixture.versions[0] as unknown as ManuscriptVersion
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('saves fixed versions with presentation revision and preserves uncertain request identity and draft',async()=>{
 const change=vi.fn();let fail=true
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){
   if(fail)throw new TypeError('network')
   const input=JSON.parse(String(init.body));return Response.json({...input,id:'presentation1',manuscript_id:'m1',revision:1,schema_version:1,stale:false,stale_version_ids:[],checks:[{code:'ethics_pending',status:'pending',message:'Ethics pending'}],paragraph_groups:[],quality:{scientific_semantic:'pending',word_wps:'pending',real_compliance:'pending'},can_export:true})
  }return Response.json({items:[]})
 });vi.stubGlobal('fetch',fetcher)
 const props={projectId:'p1',manuscriptId:'m1',version,versions:[version],onSelect:change,active:true}
 const result=render(<StrictMode><ManuscriptPresentation {...props}/></StrictMode>);await screen.findByText('尚无已保存输出配置。')
 fireEvent.change(screen.getByLabelText('固定期刊指南版本'),{target:{value:'guide-fixed-1'}});fireEvent.click(screen.getByRole('button',{name:'添加作者'}));fireEvent.change(screen.getByLabelText('作者姓名 1'),{target:{value:'Ada'}});fireEvent.change(screen.getByLabelText('作者来源'),{target:{value:'User confirmation'}})
 fireEvent.click(screen.getByRole('button',{name:'保存输出配置'}));await screen.findByRole('alert')
 result.rerender(<StrictMode><ManuscriptPresentation {...props} active={false}/></StrictMode>);expect((screen.getByLabelText('作者姓名 1') as HTMLInputElement).value).toBe('Ada')
 fail=false;result.rerender(<StrictMode><ManuscriptPresentation {...props}/></StrictMode>);fireEvent.click(screen.getByRole('button',{name:'保存输出配置'}))
 await screen.findByText('Ethics pending');expect(change).toHaveBeenCalledWith(expect.objectContaining({id:'presentation1',revision:1}))
 const calls=fetcher.mock.calls.filter(([,i])=>i?.method==='POST');expect(calls).toHaveLength(2)
 expect(new Headers(calls[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(calls[1][1]?.headers).get('Idempotency-Key'))
 expect(JSON.parse(String(calls[1][1]?.body))).toMatchObject({expected_revision:0,base_version_id:version.id,peer_version_id:null,config:{guide_version_id:'guide-fixed-1',authors:[{name:'Ada',order:1}],statements:expect.arrayContaining([{kind:'ethics',state:'pending',text:'',source:'',reason:''}])}})
})
it('shows stale and pending inventory without claiming compliance',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[{id:'p-old',revision:3,manuscript_id:'m1',base_version_id:version.id,peer_version_id:null,schema_version:1,config:{paragraph_groups:[],terminology:[],figure_pairs:[],authors:[],affiliations:[],statements:[],school:null,blind:{identity_terms:[],hidden_chapter_ids:[],exceptions:[],manual_image_review:false}},checks:[{code:'missing',status:'pending',message:'Missing material'}],paragraph_groups:[],quality:{scientific_semantic:'pending',word_wps:'pending',real_compliance:'pending'},can_export:true,stale:true,stale_version_ids:[version.id]}]})))
 render(<ManuscriptPresentation projectId="p1" manuscriptId="m1" version={version} versions={[version]} onSelect={vi.fn()} active/>);await screen.findByText('Missing material');expect(screen.getByText('关联稿件已有新版本，当前配置需复核。')).toBeTruthy();expect(screen.getByText('保存成功仅固定配置；语义、真实合规与 Word/WPS 仍待人工核对。')).toBeTruthy()
})
it('keeps scientific review notes visible while hiding embedded checksums in the customer preview',async()=>{
 const rawMessage='题注来源 '+ 'a'.repeat(64)+' 由用户关联，语义仍待人工核对。'
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[{id:'p1',revision:1,manuscript_id:'m1',base_version_id:version.id,peer_version_id:null,schema_version:1,config:{paragraph_groups:[],terminology:[],figure_pairs:[],authors:[],affiliations:[],statements:[],school:null,blind:{identity_terms:[],hidden_chapter_ids:[],exceptions:[],manual_image_review:false}},checks:[{code:'caption',status:'pending',message:rawMessage}],paragraph_groups:[],quality:{scientific_semantic:'pending',word_wps:'pending',real_compliance:'pending'},can_export:true,stale:false,stale_version_ids:[]}]})))
 const {container}=render(<ManuscriptPresentation projectId="p1" manuscriptId="m1" version={version} versions={[version]} onSelect={vi.fn()} active/>);
 await screen.findByText(/语义仍待人工核对/);expect(container.textContent).not.toContain('a'.repeat(64));expect(container.textContent).toContain('待补 / 人工核对')
})
it('sends explicit stable paragraph IDs in a one-to-many group and previews returned text',async()=>{
 const p={origin:'user_provided' as const,source_ids:[],citations:[]}
 const zh={...version,id:'zh-fixed',snapshot:{...version.snapshot,output_language:'zh-CN' as const,sections:[{id:'abstract',paragraphs:[{...p,id:'zh-stable',text:'已有中文事实'}]}],methods:[],results_groups:[]}}
 const en={...version,id:'en-fixed',revision:2,snapshot:{...version.snapshot,output_language:'en' as const,sections:[{id:'abstract',paragraphs:[{...p,id:'en-part-a',text:'Existing English fact.'},{...p,id:'en-part-b',text:'Known limitation.'}]}],methods:[],results_groups:[]}}
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{if(!init?.method)return Response.json({items:[]});const input=JSON.parse(String(init.body));return Response.json({...input,schema_version:1,checks:[],quality:{scientific_semantic:'pending',word_wps:'pending',real_compliance:'pending'},paragraph_groups:[{id:input.config.paragraph_groups[0].id,zh:zh.snapshot.sections[0].paragraphs,en:en.snapshot.sections[0].paragraphs,status:'paired'}],can_export:true})});vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptPresentation projectId="p1" manuscriptId="m1" version={zh} versions={[zh,en]} onSelect={vi.fn()} active/>);await screen.findByText('尚无已保存输出配置。')
 fireEvent.change(screen.getByLabelText('关联的另一语言固定版本'),{target:{value:en.id}});fireEvent.click(screen.getByRole('button',{name:'添加关联组'}))
 const chinese=screen.getByLabelText('中文段落') as HTMLSelectElement,english=screen.getByLabelText('英文段落') as HTMLSelectElement
 chinese.options[0].selected=true;fireEvent.change(chinese);english.options[0].selected=true;english.options[1].selected=true;fireEvent.change(english);fireEvent.change(screen.getByLabelText('关联状态'),{target:{value:'paired'}});fireEvent.click(screen.getByRole('button',{name:'预览配置核对'}))
 await screen.findByText('Existing English fact.');const post=fetcher.mock.calls.find(([,i])=>i?.method==='POST')!;expect(post[0]).toContain('/presentations/preview');expect(JSON.parse(String(post[1]?.body))).toMatchObject({base_version_id:'zh-fixed',peer_version_id:'en-fixed',config:{paragraph_groups:[{id:expect.any(String),zh_ids:['zh-stable'],en_ids:['en-part-a','en-part-b'],status:'paired'}]}})
})
it('fixes existing school options, required chapter purpose and source in the saved configuration',async()=>{
 const options={manual_fields:{author:'Provided author',student_id:'',department:'',major:'',class_name:'',supervisor:'',submission_date:''},manual_chapters:[{chapter_id:'appendix',text:'Actual supplied appendix'}],english_title:'Fixed title',keywords:[],include_toc:true,toc_depth:3}
 const schoolVersion={...version,snapshot:{...version.snapshot,sections:[{id:'appendix',title:'附录',paragraphs:[]}]}}
 const fetcher=vi.fn(async(_url:string,init?:RequestInit)=>{if(!init?.method)return Response.json({items:[]});const input=JSON.parse(String(init.body));return Response.json({...input,id:'school-p',revision:1,manuscript_id:'m1',schema_version:1,stale:false,stale_version_ids:[],checks:[{code:'registration',status:'pending',message:'Registration pending'}],paragraph_groups:[],quality:{scientific_semantic:'pending',word_wps:'pending',real_compliance:'pending'},can_export:true})});vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptPresentation projectId="p1" manuscriptId="m1" version={schoolVersion} versions={[schoolVersion]} schoolOptions={options} onSelect={vi.fn()} active/>);await screen.findByText('尚无已保存输出配置。');fireEvent.click(screen.getByLabelText('固定当前学校导出字段到配置'));fireEvent.click(screen.getByRole('button',{name:'添加补充用途'}));fireEvent.change(screen.getByLabelText('补充章节'),{target:{value:'appendix'}});fireEvent.change(screen.getByLabelText('补充内容来源'),{target:{value:'User document page 5'}});fireEvent.click(screen.getByRole('button',{name:'保存输出配置'}));await screen.findByText('Registration pending')
 await waitFor(()=>expect(fetcher.mock.calls.some(([,i])=>i?.method==='POST')).toBe(true));expect(JSON.parse(String(fetcher.mock.calls.find(([,i])=>i?.method==='POST')![1]?.body))).toMatchObject({config:{school:{options,supplements:[{chapter_id:'appendix',purpose:'appendix',required:true,source:'User document page 5'}]}}})
})
