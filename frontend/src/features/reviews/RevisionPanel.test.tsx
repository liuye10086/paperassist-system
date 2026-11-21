import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import RevisionPanel from './RevisionPanel'
import {taskFixture} from '../tasks/taskFixtures'
import {exportFixture,manuscriptFixture} from '../manuscripts/manuscriptFixtures'
import {setLocale} from '../../shared/i18n'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
const evidence={id:'e1',kind:'source',sha256:'a'.repeat(64),content:'固定证据：仅观察到关联'}
const context={round_id:'r1',plan_revision:2,manuscript:{id:'m1',revision:1,version_id:'v1'},expected_current_revision:3,project_type:'sci',output_language:'en',locations:[{kind:'paragraph',id:'p1',section_id:'methods',section_title:'方法',text:'Old paragraph'}],citation_candidates:[],evidence:[evidence],grounded_plans:[{item_id:'i1',original_text:'Explain the association.',existing_content:'Old paragraph',evidence:[evidence],plan:'根据固定观察证据澄清关联',missing:['独立实验待补']}],constraints:{}}
const round={project_type:'sci',id:'r1',revision:2,manuscript:{id:'m1',version_id:'v1',revision:1,title:'旧稿'},sources:[{id:'s1',label:'Reviewer 2'}],items:[{id:'i1',source_id:'s1',number:1,original_text:'Explain the association.'}]} as never

it.each(['zh-CN','en'] as const)('uses actual generated location and evidence fields on the revision page in %s',async locale=>{
 setLocale(locale)
 const raw='materials_and_methods/methods:purpose',source='aa086d01-4f4a-5f85-9b28-9d143feea1fa',other='5da696af-99a7-44c1-8f29-25a4b067720e'
 const pieces=['意见：原文 '+source+' 📝\n固定位置：','\n已读取具体资料：','：分组说明；','：统计报告\n具体处理：核对 ','。']
 const values=[raw,source,other,raw],ids=['methods:purpose',source,other,'methods:purpose']
 let plan=''
 const spans=values.map((value,i)=>{plan+=pieces[i];const start=Array.from(plan).length;plan+=value;return {id:ids[i],kind:i===0||i===3?'paragraph':'evidence',start,end:start+value.length}})
 plan+=pieces[4]
 const item={id:'i1',source_id:'s1',number:1,original_text:'原文 '+source,plan,locations:[{kind:'paragraph',id:'methods:purpose'}]}
 const saved={...(round as object),items:[item],versions:[{revision:1,items:[item]}],generated_plan_locations:{i1:spans}}
 const location={kind:'paragraph',id:'methods:purpose',section_id:'materials_and_methods',section_title:'materials_and_methods',paragraph_number:1,text:'稿件原文'}
 const materials=[{...evidence,id:source,kind:'document_version',content:{filename:'分组说明.docx'}},{...evidence,id:other,kind:'document_version',content:{filename:'统计报告.docx'}}]
 const c={...context,locations:[location],evidence:materials,grounded_plans:[{...context.grounded_plans[0],plan,location_spans:spans,locations:[location],evidence:materials}]}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('revision-context')?c:{items:[]})))
 const props={projectId:'p1',active:true,disabled:false,customer:true,onOpenTask:vi.fn(),view:'revision' as const}
 const ui=render(<RevisionPanel {...props} round={saved as never}/>)
 const output=await screen.findByText(/已读取具体资料：/)
 expect(output.textContent).not.toContain(raw)
 expect(output.textContent).toMatch(locale==='en'?/Paragraph 1/i:/段落 1/)
 expect(output.textContent).toContain('分组说明.docx：分组说明；统计报告.docx：统计报告')
 expect(output.textContent?.split(source)).toHaveLength(2)
 const manual='客户手写 '+source+'/'+raw
 ui.rerender(<RevisionPanel {...props} round={{...saved,items:[{...item,plan:manual}]} as never}/>)
 expect(await screen.findByText(manual)).toBeTruthy()
})

it('waits for the initial plan and clears a recovered revision-context read error',async()=>{
 const fetcher=vi.fn(async(url:string)=>url.endsWith('/revision-context')&&unavailable?
  Response.json({detail:{code:'task_input_invalid'}},{status:409}):Response.json(url.endsWith('/revision-context')?context:{items:[]}))
 let unavailable=true
 vi.stubGlobal('fetch',fetcher)
 const props={projectId:'p1',active:true,disabled:false,customer:true,onOpenTask:vi.fn(),view:'revision' as const}
 const waiting={...(round as object),items:[],versions:[],task:{status:'running'}}
 const ui=render(<RevisionPanel {...props} round={waiting as never}/>)
 expect(fetcher).not.toHaveBeenCalled()
 ui.rerender(<RevisionPanel {...props} round={round}/>)
 await screen.findByRole('alert')
 unavailable=false
 fireEvent.click(screen.getByRole('button',{name:'保留操作并更新核对基线'}))
 await screen.findByText('已有资料支持的具体计划')
 expect(screen.queryByRole('alert')).toBeNull()
})
it('selects readable fixed evidence and previews concrete changes before one batch adoption with current CAS',async()=>{
 const posts:{url:string;body:Record<string,unknown>}[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{const body=init?.body?JSON.parse(String(init.body)):{};if(init?.method==='POST')posts.push({url,body});return Response.json(url.endsWith('/revision-context')?context:url.endsWith('/preview')?{...context,actual_changes:[{item_id:'i1',kind:'replace_paragraph',location:context.locations[0],before:'Old paragraph',after:'Clarified association.',reason:'固定证据支持',evidence:[evidence]}],unexecuted:[{item_id:'i2',status:'waiting_material',reason:'独立实验尚未完成'}],public_issues:[],constraint_issues:[],can_adopt:true,preview_sha256:'b'.repeat(64),synthetic:true}:init?.method==='POST'?{id:'rev1',round_id:'r1',input_snapshot:{},task:{...taskFixture,task_type:'review_revision',phase:'verify',status:'queued',display_status:'queued',input_version:{kind:'review_revision',revision_id:'rev1',round_id:'r1',base_version_id:'v1',workflow_version:'review_revision_v1'}},result:null,validation:{},created_at:taskFixture.created_at}:{items:[]})}))
 render(<RevisionPanel projectId="p1" round={round} active onOpenTask={vi.fn()} disabled={false}/>);
 fireEvent.click(screen.getByRole('button',{name:'执行本批修改'}));await screen.findByText('根据固定观察证据澄清关联');expect(screen.getByText(/固定父稿：版本 1/)).toBeTruthy();expect(screen.getByText(/当前最新版本 3/)).toBeTruthy()
 fireEvent.change(screen.getByLabelText('本次处理意见'),{target:{value:'i1'}});fireEvent.change(screen.getByLabelText('固定修改位置'),{target:{value:'p1'}});fireEvent.click(screen.getByLabelText(/固定证据：仅观察到关联/));fireEvent.change(screen.getByLabelText('具体修改内容'),{target:{value:'Clarified association.'}});fireEvent.change(screen.getByLabelText('修改理由'),{target:{value:'固定证据支持'}});fireEvent.click(screen.getByRole('button',{name:'加入本批操作'}));fireEvent.click(screen.getByRole('button',{name:'预览实际差异与检查'}));await screen.findByText(/独立实验尚未完成/);expect(posts[0].body).toMatchObject({plan_revision:2,expected_current_revision:3,operations:[{item_id:'i1',location_id:'p1',evidence_ids:['e1'],text:'Clarified association.'}]});fireEvent.click(screen.getByRole('button',{name:'统一采用并另存公共新稿'}));await waitFor(()=>expect(posts).toHaveLength(2));expect(posts[1].body.preview_sha256).toBe('b'.repeat(64));expect(screen.queryByText('公共新稿已完成')).toBeNull()
})
it('preserves unsaved concrete edits when refreshing saved outputs',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/revision-context')?context:{items:[]})))
 render(<RevisionPanel projectId="p1" round={round} active onOpenTask={vi.fn()} disabled={false}/>);fireEvent.click(screen.getByRole('button',{name:'执行本批修改'}));await screen.findByText('根据固定观察证据澄清关联');fireEvent.change(screen.getByLabelText('具体修改内容'),{target:{value:'本地未保存改文'}});fireEvent.click(screen.getByRole('button',{name:'刷新本批成果'}));await waitFor(()=>expect(screen.getByLabelText('具体修改内容')).toHaveProperty('value','本地未保存改文'))
})
it('keeps repeated full source payloads collapsed while fixed evidence remains selectable',async()=>{const bulky={...evidence,kind:'analysis_run',content:{filename:'fixed-results.xlsx',internal_marker:'Full fixed evidence '.repeat(100),url:'https://example.invalid/fixed',optional:null}},fixed={...context,evidence:[bulky],grounded_plans:[{...context.grounded_plans[0],evidence:[bulky]}]};vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/revision-context')?fixed:{items:[]})));render(<RevisionPanel projectId="p1" round={round} active onOpenTask={vi.fn()} disabled={false}/>);fireEvent.click(screen.getByRole('button',{name:'执行本批修改'}));await screen.findByText('根据固定观察证据澄清关联');for(const raw of screen.getAllByText(/internal_marker/)){const details=raw.closest('details');expect(details).not.toBeNull();expect(details?.open).toBe(false)}expect(screen.getByRole('checkbox',{name:/fixed-results.xlsx/})).toBeTruthy();expect(screen.getByLabelText('具体修改内容')).toBeTruthy()})
it('binds a fixed verified citation source separately from the same-text manuscript target',async()=>{
 const statement='The fixed observation supports an association.',candidate={id:'literature:c1',text:statement,citations:[{project_reference_id:'ref1',reference_id:'r1',review_id:'checked1',metadata_version_id:'metadata1'}]},fixed={...context,locations:[{kind:'paragraph',id:'target',section_id:'methods',section_title:'方法',text:statement}],citation_candidates:[candidate]},posts:Record<string,unknown>[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{if(init?.method==='POST'){posts.push(JSON.parse(String(init.body)));return Response.json({...fixed,actual_changes:[],unexecuted:[],public_issues:[],constraint_issues:[],can_adopt:false,preview_sha256:'b'.repeat(64),synthetic:true})}return Response.json(url.endsWith('/revision-context')?fixed:{items:[]})}))
 render(<RevisionPanel projectId="p1" round={round} active onOpenTask={vi.fn()} disabled={false}/>);fireEvent.click(screen.getByRole('button',{name:'执行本批修改'}));await screen.findByText('根据固定观察证据澄清关联');fireEvent.change(screen.getByLabelText('本次处理意见'),{target:{value:'i1'}});fireEvent.change(screen.getByLabelText('编辑操作'),{target:{value:'bind_citation'}});fireEvent.change(screen.getByLabelText('固定修改位置'),{target:{value:'target'}});const source=screen.getByLabelText('具体修改内容');expect(Array.from(source.querySelectorAll('option')).map(o=>o.value)).toEqual(['','literature:c1']);fireEvent.change(source,{target:{value:'literature:c1'}});fireEvent.click(screen.getByLabelText(/固定证据：仅观察到关联/));fireEvent.change(screen.getByLabelText('修改理由'),{target:{value:'原陈述相同，采用已有核验绑定'}});fireEvent.click(screen.getByRole('button',{name:'加入本批操作'}));fireEvent.click(screen.getByRole('button',{name:'预览实际差异与检查'}));await waitFor(()=>expect(posts).toHaveLength(1));expect(posts[0]).toMatchObject({operations:[{item_id:'i1',kind:'bind_citation',location_id:'target',text:'literature:c1',evidence_ids:['e1']}]})
})
it('synchronizes a default run before its default document and preserves an explicit missing run',async()=>{
 const saved={id:'rev1',round_id:'r1',output_status:'published',input_snapshot:{},created_at:taskFixture.created_at,task:{...taskFixture,task_type:'review_revision',phase:'verify',input_version:{kind:'review_revision',revision_id:'rev1',round_id:'r1',base_version_id:'v1',workflow_version:'review_revision_v1'}},validation:{},result:{actual_changes:[],unexecuted:[],public_issues:[],constraint_issues:[],items:[],public_check_version:3,output:{manuscript_id:'m1',version_id:'v2',parent_version_id:'v1',revision:2,task_id:'mt1'}}};
 const document={id:'d1',project_id:'p1',revision_id:'rev1',round_id:'r1',kind:'reply',version:1,language:'en',confirmed_at:null,created_at:taskFixture.created_at,latest_version:1,snapshot:{title:'Reply',project_type:'sci',synthetic:true,language:'en',kind:'reply',revision_id:'rev1',result_sha256:'a'.repeat(64),output:{manuscript_id:'m1',version_id:'v2',revision:2},items:[],location_notice:'Fixed locations'}};
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/revision-context')?context:url.endsWith('/revisions')?{items:[saved]}:url.endsWith('/documents')?{items:[document]}:{items:[]})));
 const selections:string[]=[],props={projectId:'p1',round,active:true,disabled:false,onOpenTask:vi.fn(),onSelectRun:(id:string)=>selections.push('run:'+id),onSelectDocument:(id:string)=>selections.push('document:'+id),view:'response' as const};const ui=render(<RevisionPanel {...props}/>);await screen.findByText(/Reply · 版本 1/);expect(selections).toEqual(['run:rev1','document:d1']);
 ui.rerender(<RevisionPanel {...props} initialRun="missing"/>);expect(await screen.findByRole('alert')).toHaveProperty('textContent','指定修改批次不可用；不会自动替换为最新成果。');expect(selections).toEqual(['run:rev1','document:d1']);
})

it('shows readable revisions, source excerpts and a flat Word download in the customer view', async () => {
 const location={...context.locations[0],section_id:'materials_and_methods',section_title:'materials_and_methods',text:'Original method.'}
 const material={id:'f2a6939b-b706-4037-b294-68b106ebd602',kind:'document_version',sha256:'b'.repeat(64),
  content:{filename:'实验说明.docx',parser_version:'openxml-v3',document_version_id:'private-parse-id',
   paragraphs:[{id:'private-paragraph-id',text:'原实验材料中的方法依据。'}]},
 }
 const realContext={...context,locations:[location],evidence:[material],grounded_plans:[{
  ...context.grounded_plans[0],locations:[location],existing_content:location.text,evidence:[material],
  plan:'意见：Explain the association.\n固定位置：materials_and_methods/p1\n固定现文：Original method.\n已读取具体资料：'+material.id+'：原实验材料中的方法依据。\n具体处理：使用事实 ID 并按 p1 更新。',
 }]}
 const changes=[{item_id:'i1',kind:'replace_paragraph',location,before:location.text,after:'Revised method.',reason:'按实验说明补充方法。',evidence:[material]}]
 const repeated={severity:'human_review',message:'请核对方法与数据的一致性。'}
 const blocker={severity:'error',message:'尚缺所用试剂的名称。'}
 const revision={id:'rev1',round_id:'r1',output_status:'published',input_snapshot:{},created_at:taskFixture.created_at,
  task:{...taskFixture,task_type:'review_revision',status:'succeeded',display_status:'succeeded',phase:'verify',
   input_version:{kind:'review_revision',revision_id:'rev1',round_id:'r1',base_version_id:'v1',workflow_version:'review_revision_v1'}},
  validation:{},result:{actual_changes:changes,unexecuted:[],public_issues:[],items:[],public_check_version:3,
   output:{manuscript_id:'m1',version_id:'v1',parent_version_id:'original',revision:1,task_id:'mt1'}},
 }
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/revisions/preview')?{
  ...realContext,actual_changes:changes,unexecuted:[],public_issues:[repeated,repeated],constraint_issues:[repeated,blocker],
  can_adopt:false,preview_sha256:'c'.repeat(64),synthetic:true,
 }:url.endsWith('/revision-context')?realContext:
  url.endsWith('/revisions')?{items:[revision]}:url.endsWith('/manuscripts/m1/versions/1')?manuscriptFixture.versions[0]:
  url.endsWith('/exports')?{items:[exportFixture]}:{items:[]})))
 const {container}=render(<RevisionPanel projectId="p1" round={round} active disabled={false} onOpenTask={vi.fn()} customer view="revision"/>)
 expect((await screen.findByText('Revised method.')).closest('[hidden]')).toBeNull()
 expect(screen.getAllByText(/材料与方法/).length).toBeGreaterThan(0)
 expect(screen.getAllByText('原实验材料中的方法依据。').length).toBeGreaterThan(0)
 expect(screen.getAllByText('实验说明.docx').length).toBeGreaterThan(0)
 expect((await screen.findByRole('link',{name:'下载这份 Word'})).getAttribute('href')).toBe(exportFixture.download_url)
 expect(container.textContent).not.toMatch(/materials_and_methods|document_version|parser_version|private-parse-id|SHA256|事实 ID|固定父稿：版本 1/)
 expect(container.querySelector('details, button[aria-expanded]')).toBeNull()
 fireEvent.change(screen.getByLabelText('本次处理意见'),{target:{value:'i1'}})
 fireEvent.change(screen.getByLabelText('固定修改位置'),{target:{value:'p1'}})
 fireEvent.click(screen.getByRole('checkbox',{name:'实验说明.docx'}))
 fireEvent.change(screen.getByLabelText('具体修改内容'),{target:{value:'Revised method.'}})
 fireEvent.change(screen.getByLabelText('修改理由'),{target:{value:'对照实验说明。'}})
 fireEvent.click(screen.getByRole('button',{name:'加入本批操作'}))
 fireEvent.click(screen.getByRole('button',{name:'预览实际差异与检查'}))
 await screen.findByText(/尚缺所用试剂的名称/)
 expect(screen.getAllByText(/请核对方法与数据的一致性/)).toHaveLength(1)
 expect(screen.getByRole('button',{name:'统一采用并另存公共新稿'})).toHaveProperty('disabled',true)
})
