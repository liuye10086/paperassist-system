import {act,cleanup,fireEvent,render,screen,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ManuscriptPreview from './ManuscriptPreview'
import {snapshotFixture} from './manuscriptFixtures'
import {validSnapshot,type Snapshot} from './manuscriptTypes'
import {setLocale} from '../../shared/i18n'
import {actualSections,type AdaptationPreview} from '../journals/adaptationContracts'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it('shows one frozen chapter at a time in body view and offers explicit full reading',()=>{
 const snapshot={...snapshotFixture,sections:['title','abstract','introduction','results','discussion','materials_and_methods','references'].map(id=>({id,paragraphs:[{id:`${id}:1`,text:`Content ${id}`,origin:'model_generated',source_ids:[],citations:[]}]}))} as Snapshot
 render(<ManuscriptPreview snapshot={snapshot} presentation="body"/>)
 expect(screen.getByText('Content abstract')).toBeTruthy();expect(screen.queryByText('Content introduction')).toBeNull()
 fireEvent.change(screen.getByLabelText('正文章节'),{target:{value:'introduction'}})
 expect(screen.getByText('Content introduction')).toBeTruthy();expect(screen.queryByText('Content abstract')).toBeNull()
 fireEvent.change(screen.getByLabelText('正文章节'),{target:{value:'all'}})
 expect(screen.getByText('Content abstract')).toBeTruthy();expect(screen.getByText('Content introduction')).toBeTruthy()
})
it.each([false,true])('opens the frozen reference chapter from a citation without changing workspace hash (school: %s)',school=>{
 const referenceChapter=school?'school-references':'references'
 const snapshot={...snapshotFixture,references:[{number:1,text:'Frozen reference',project_reference_id:'ref1'}],sections:[{id:'abstract',purpose:'abstract',title:'Abstract',paragraphs:[{id:'a:1',text:'Abstract claim',origin:'user_provided',source_ids:[],citations:[1]}]},{id:referenceChapter,purpose:'references',title:'References',paragraphs:[]}],...(school?{thesis_context:{profile:{school:'School',applicable_version:'2026'},confirmation_id:'confirmation'}}:{})} as unknown as Snapshot
 window.history.replaceState(null,'','#project=p1&section=manuscripts&view=body')
 const hash=window.location.hash;render(<ManuscriptPreview snapshot={snapshot} presentation="body"/>)
 expect(screen.queryByText('Frozen reference')).toBeNull()
 fireEvent.click(screen.getByRole('link',{name:/1$/}))
 expect(screen.getByLabelText('正文章节')).toHaveProperty('value',referenceChapter)
 expect(screen.getByText('Frozen reference')).toBeTruthy()
 expect(document.activeElement?.textContent).toBe('Frozen reference');expect(window.location.hash).toBe(hash)
})
it('offers the reference chapter for older two-section fact drafts',()=>{
 const snapshot={...snapshotFixture,methods:[{...snapshotFixture.methods[0],citations:[1]}],references:[{number:1,text:'Legacy reference',project_reference_id:'ref1'}]} as Snapshot
 render(<ManuscriptPreview snapshot={snapshot} presentation="body"/>)
 expect(screen.getByRole('option',{name:'References'})).toHaveProperty('value','references')
 fireEvent.click(screen.getByRole('link',{name:/1$/}))
 expect(screen.getByLabelText('正文章节')).toHaveProperty('value','references')
 expect(document.activeElement?.textContent).toBe('Legacy reference')
})
it('labels synthetic journal adaptation on an ordinary draft independently of scientific writing provenance',()=>{
 const snapshot={...snapshotFixture,journal_adaptation_provenance:{adaptation_id:'a1',base_version_id:'v1',input_sha256:'a'.repeat(64),display_version:'journal_display_v1',synthetic:true}} as Snapshot
 const original=JSON.stringify(snapshot);expect(validSnapshot(snapshot,'p1')).toBe(true)
 render(<ManuscriptPreview snapshot={snapshot}/>);expect(screen.getByText('期刊适配使用了合成指南或稿件输入，仅验证离线工程，不代表真实期刊适配验收。')).toBeTruthy()
 expect(screen.queryByText('合成模拟材料，仅验证流程，不代表真实模型效果。')).toBeNull()
 expect(screen.getByText('Frozen methods')).toBeTruthy();expect(snapshot.writing_provenance).toBeUndefined();expect(JSON.stringify(snapshot)).toBe(original)
 act(()=>setLocale('en'));expect(screen.getByText('Journal adaptation uses a synthetic guide or manuscript input for offline engineering validation only; it does not establish acceptance of a real journal adaptation.')).toBeTruthy()
 expect(validSnapshot({...snapshot,journal_adaptation_provenance:{...snapshot.journal_adaptation_provenance,synthetic:'true'}},'p1')).toBe(false)
})
it.each([false,undefined])('does not invent synthetic journal provenance when the flag is %s',synthetic=>{
 const snapshot={...snapshotFixture,journal_adaptation_provenance:{adaptation_id:'a1',base_version_id:'v1',input_sha256:'a'.repeat(64),display_version:'journal_display_v1',...(synthetic===undefined?{}:{synthetic})}} as Snapshot
 expect(validSnapshot(snapshot,'p1')).toBe(true);render(<ManuscriptPreview snapshot={snapshot}/>)
 expect(screen.queryByText('期刊适配使用了合成指南或稿件输入，仅验证离线工程，不代表真实期刊适配验收。')).toBeNull()
})
it('excludes the manuscript Title from heading and body styles and from actual global style changes',()=>{
 const ids=['title','abstract','introduction','results','discussion','materials_and_methods','references'] as const
 const styles={heading_font_size_pt:14,body_font_size_pt:12,heading_line_spacing:1.5,body_line_spacing:2,heading_space_before_pt:10,heading_space_after_pt:6,body_space_before_pt:4,body_space_after_pt:8}
 const title={...snapshotFixture.methods[0],id:'title-p',text:'Frozen scientific title'},body={...snapshotFixture.methods[0],id:'abstract-p',text:'Frozen abstract body'}
 const snapshot={...snapshotFixture,sections:ids.map(id=>({id,paragraphs:id==='title'?[title]:id==='abstract'?[body]:[]})),journal_display_context:{version:'journal_display_v1',names:Object.fromEntries(ids.map(id=>[id,id])),order:ids,styles}} as unknown as Snapshot
 render(<ManuscriptPreview snapshot={snapshot}/>);const titleParagraph=screen.getByText('Frozen scientific title').closest('p')!,titleLabel=screen.getByRole('heading',{name:'title'})
 expect(titleLabel.getAttribute('style')).toBeNull();expect(titleParagraph.getAttribute('style')).toBeNull()
 expect(screen.getByRole('heading',{name:'abstract'}).style.fontSize).toBe('14pt');expect(screen.getByText('Frozen abstract body').closest('p')!.style.fontSize).toBe('12pt')
 const preview={sections:ids.map((section_id,position)=>({section_id,before:{display_name:section_id,position,styles:{}},after:{display_name:section_id,position,styles},changed:true}))} as AdaptationPreview
 const actual=actualSections(preview,Object.entries(styles).map(([key,after])=>({id:key,key,before:null,after,evidence:[],reason:'explicit source'})))
 expect(actual[0].changed).toBe(false);expect(actual[0].after.styles).toEqual({});expect(actual.slice(1).every(section=>section.changed)).toBe(true)
})
it('labels image observations, numbered tables, caption candidates and saved Methods reference issues',()=>{
 const snapshot={...snapshotFixture,output_language:'zh-CN',illustration_check_version:1,methods:[{...snapshotFixture.methods[0],origin:'image_observation',text:'已保存图像观察',cross_references:[{kind:'figure',target_id:'image1',number:1,panel_label:'A'}]}],results_groups:[{id:'g1',title:'观察',paragraphs:[],tables:[{id:'t1',number:2,title:'观察汇总',columns:['内容'],rows:[['说明']],source_ids:[]}],figures:[{id:'image1',number:1,title:'图像',caption:'候选图注',caption_status:'candidate',sha256:'a'.repeat(64),source_ids:[]}]}],issues:[{id:'body-reference:methods:0',kind:'conflict',field:'methods:procedures',message:'正文或图注引用无法对应：图 9。请核对编号；原文保留。',values:['图 9']}]} as Snapshot
 render(<ManuscriptPreview snapshot={snapshot}/>);expect(screen.getByText('图像观察，不作为统计结论')).toBeTruthy();expect(screen.getByText('候选图注，需人工补充与确认')).toBeTruthy();expect(screen.getByText('表 2. 观察汇总')).toBeTruthy();expect(screen.getByText(/正文或图注引用无法对应/)).toBeTruthy();expect(screen.getByText('图 1A')).toBeTruthy()
})
it('shows Results before Methods in the saved output language and does not duplicate server citation numbering',async()=>{
 const source={kind:'original',id:'image1',file_id:'image1',role:'image_observation',label:'Original image',sha256:'a'.repeat(64),download_url:'/api/v1/projects/p1/files/image1/download',content:{}}
 const snapshot={...snapshotFixture,output_language:'zh-CN',methods:[{...snapshotFixture.methods[0],text:'已核验论述 (1)',citations:[1]}],sources:[source],references:[{number:1,text:'Author. Published study.',project_reference_id:'ref1'}],results_groups:[{id:'g1',title:'结果分组',paragraphs:[],tables:[],figures:[{id:'image1',number:1,title:'Original image',caption:'Caption',sha256:'a'.repeat(64),source_ids:['image1']}]}]} as Snapshot
 const NativeURL=URL;vi.stubGlobal('URL',class extends NativeURL{static createObjectURL=vi.fn(()=> 'blob:source-image');static revokeObjectURL=vi.fn()})
 const fetcher=vi.fn(async(_url:string)=>new Response('image',{headers:{'Content-Type':'image/png'}}));vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptPreview snapshot={snapshot}/>)
 const titles=screen.getAllByRole('heading',{level:4}).map(n=>n.textContent)
 expect(titles.indexOf('结果')).toBeLessThan(titles.indexOf('材料与方法'))
 expect(screen.getByRole('heading',{name:'参考文献'})).toBeTruthy()
 expect((await screen.findByRole('img',{name:'Original image'})).getAttribute('src')).toBe('blob:source-image')
 expect(fetcher.mock.calls[0][0]).toBe(source.download_url)
 const paragraph=screen.getByText('已核验论述 (1)').closest('.manuscript-paragraph')!
 expect(within(paragraph as HTMLElement).queryByText('[1]')).toBeNull()
})

it.each([
 ['zh-CN','表 1. data.xlsx — 指标','表 1. data.xlsx — 指标'],
 ['en','Table 1. data.xlsx — metric','Table 1. data.xlsx — metric'],
 ['zh-CN','指标','表 1. 指标'],
 ['en','Metric','Table 1. Metric'],
 ['en','Table 2. Other metric','Table 1. Table 2. Other metric'],
] as const)('avoids duplicate frozen table numbering in %s: %s', (output_language,title,caption)=>{
 const snapshot={...snapshotFixture,output_language,results_groups:[{id:'g1',title:'Results',paragraphs:[],figures:[],tables:[{id:'table1',number:1,title,columns:['Value'],rows:[['1']],source_ids:[]}]}]} as Snapshot
 render(<ManuscriptPreview snapshot={snapshot}/>);expect(screen.getByRole('table').querySelector('caption')?.textContent).toBe(caption);expect(snapshot.results_groups[0].tables[0].title).toBe(title)
})
