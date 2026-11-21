// B04 task 9 (D6): the migration page opened from the template change preview preselects the new template, and its
// customer wording says what happens to downloaded Word files instead of “historical versions keep the old template”.
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {findTechnicalText} from '../../test/technicalText'
import SchoolChanges from './SchoolChanges'
import {manuscriptFixture} from './manuscriptFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
import type {SchoolChange} from './schoolChangeTypes'
import {ManuscriptDraftContext} from './manuscriptDraftContext'
import {setLocale} from '../../shared/i18n'

afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
const oldConfirmation='5d0c3a52-7f1e-4f0b-9a55-0c1b3e7d2a10',newConfirmation='9b2e6f14-3c7a-4d8e-b1f0-6a4c2d8e9f31',otherConfirmation='0f8a2b6c-1d3e-4f5a-8b7c-9d0e1f2a3b4c'
const systemIds=[oldConfirmation,newConfirmation,otherConfirmation,'a'.repeat(64),'b'.repeat(64)]
const savedAt='2026-11-18T09:30:00Z'
const version={...manuscriptFixture.versions[0],id:'base3',revision:3,created_at:savedAt,snapshot:{...manuscriptFixture.versions[0].snapshot,thesis_context:{confirmation_id:oldConfirmation,chapters:[{id:'c1',title:'方法',level:1,purpose:'materials_and_methods',output_language:'zh-CN',result_group_ids:[]}]}}} as unknown as ManuscriptVersion
const adoptedVersion={...version,id:'base4',revision:4,created_at:'2026-11-19T10:05:00Z'} as unknown as ManuscriptVersion
const change:SchoolChange={id:'change1',kind:'template_migration',manuscript_id:'m1',base_version_id:'base3',base_revision:3,created_at:'2026-11-19T10:00:00Z',input_sha256:'a'.repeat(64),source:{target_confirmation_id:newConfirmation},original_download_url:null,input_sections:[{id:'s1',title:'原方法',paragraphs:['方法正文'],suggested_chapter_id:'c1',match_method:'title',candidate_chapter_ids:['c1']}],target_chapters:[{id:'c1',title:'研究方法',level:1,purpose:'materials_and_methods',output_language:'zh-CN',result_group_ids:[]}],mappings:[{input_section_id:'s1',chapter_id:'c1'}],differences:[],issues:[],can_adopt:true,preview_sha256:'b'.repeat(64),adopted_revision:4}
function server(saved:SchoolChange=change){
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/school-templates'))return Response.json({items:[
   {id:'t1',name:'旧模板',version_label:'2025',confirmation:{id:oldConfirmation}},
   {id:'t2',name:'学校 2026 模板',version_label:'2026',confirmation:{id:newConfirmation}},
   {id:'t3',name:'学院模板',version_label:'',confirmation:{id:otherConfirmation}}]})
  if(url.endsWith('/school-changes')&&!init?.method)return Response.json({items:[saved]})
  if(url.endsWith('/school-changes/change1'))return Response.json(saved)
  if(init?.method==='POST')return Response.json(saved,{status:201})
  return Response.json({items:[],total:0,page:1,page_size:50})
 });vi.stubGlobal('fetch',fetcher);return fetcher
}
const customer=(props:Partial<Parameters<typeof SchoolChanges>[0]>={})=><SchoolChanges projectId="p1" manuscriptId="m1" version={version} versions={[adoptedVersion,version]} currentRevision={3} active templateOnly onAdopted={vi.fn()} {...props}/>

const bindingDifference={kind:'template_changed',location:'school',message:'显式采用新学校确认，父稿保持原样。',before:oldConfirmation,after:newConfirmation}
it.each(['zh-CN','en'] as const)('names both templates in a saved binding difference in %s',async(locale)=>{
 server({...change,differences:[bindingDifference]});setLocale(locale)
 const {container}=render(customer())
 fireEvent.click(await screen.findByRole('button',{name:locale==='en'?'View this input':'查看此输入'}))
 const card=(await screen.findByRole('heading',{name:locale==='en'?'Important differences and checks':'重要差异与检查'})).nextElementSibling!
 expect(card.textContent).toContain('旧模板 · 2025')
 expect(card.textContent).toContain('学校 2026 模板 · 2026')
 expect(card.textContent).toContain(locale==='en'?'Before migration: 旧模板':'迁移前：旧模板')
 expect(card.textContent).toContain(locale==='en'?'After migration: 学校 2026 模板':'迁移后：学校 2026 模板')
 expect(screen.getByRole('option',{name:'学院模板'})).toBeTruthy()
 expect(card.textContent).not.toMatch(/父稿|school confirmation/i)
 expect(findTechnicalText(container,{systemIds})).toEqual([])
})
it('describes the saved binding difference when a historical name is unavailable',async()=>{
 const missing='78f96d62-5695-4871-a9dc-c6214a1f7988'
 server({...change,differences:[{...bindingDifference,before:missing}]})
 render(customer())
 fireEvent.click(await screen.findByRole('button',{name:'查看此输入'}))
 const card=(await screen.findByRole('heading',{name:'重要差异与检查'})).nextElementSibling!
 expect(card.textContent).toContain('原稿采用的学校模板')
 expect(card.textContent).not.toContain(missing)
})
it('retains confirmation identifiers in the staff binding difference details',async()=>{
 server({...change,differences:[bindingDifference]})
 render(customer({templateOnly:false}))
 fireEvent.click(await screen.findByRole('button',{name:'查看此输入'}))
 const details=(await screen.findByText('查看变更内容')).closest('details')!
 expect(details.textContent).toContain(oldConfirmation)
 expect(details.textContent).toContain(newConfirmation)
})
it('keeps chapter order and level values in a migration with a binding difference',async()=>{
 server({...change,differences:[
  {kind:'template_changed',location:'chapter_order',message:'学校章节顺序改变。',before:'绪论 → 方法',after:'方法 → 绪论'},
  {kind:'template_changed',location:'c1',message:'学校章节层级改变。',before:'2',after:'3'},
  bindingDifference,
 ]})
 render(customer())
 fireEvent.click(await screen.findByRole('button',{name:'查看此输入'}))
 const order=(await screen.findByText('学校章节顺序改变。')).closest('article')!
 expect(order.textContent).toContain('绪论 → 方法')
 expect(order.textContent).toContain('方法 → 绪论')
 expect(screen.getByText('学校章节层级改变。').closest('article')?.textContent).toContain('迁移后：3')
})

it('preselects the new template and focuses the migration for the customer, without counting it as a draft',async()=>{
 server();const guard=vi.fn()
 const {container}=render(<ManuscriptDraftContext.Provider value={guard}>{customer({initialTarget:newConfirmation})}</ManuscriptDraftContext.Provider>)
 const select=await screen.findByLabelText('选择新模板') as HTMLSelectElement
 await waitFor(()=>expect(select.value).toBe(newConfirmation))
 const register=screen.getByRole('button',{name:'开始迁移'})
 await waitFor(()=>expect(document.activeElement).toBe(register))
 // Preselecting is not the customer's edit, so leaving does not ask to discard it.
 const dirty=()=>guard.mock.calls.at(-1)![1]()
 expect(dirty()).toBe(false)
 expect(screen.getByText('已下载的 Word 保持原样；第 3 版要按新模板导出，需要先把稿件迁移到新模板。')).toBeTruthy()
 expect(screen.queryByText(/历史稿继续使用原模板/)).toBeNull()
 expect(container.textContent).not.toMatch(/父版本|固定版本|仍按原模板|以后再次导出/)
 expect(container.querySelectorAll('details')).toHaveLength(0)
 expect(findTechnicalText(container,{systemIds})).toEqual([])
 // A real change of target is the customer's draft.
 fireEvent.change(select,{target:{value:otherConfirmation}})
 await waitFor(()=>expect(dirty()).toBe(true))
})

it('labels the customer versions with VersionLabel, including the saved migration',async()=>{
 server()
 const {container}=render(customer({initialTarget:newConfirmation}))
 const saved=await screen.findByRole('button',{name:'查看此输入'})
 fireEvent.click(saved)
 await screen.findByRole('region',{name:'匹配与重要差异'})
 const labels=[...container.querySelectorAll('.version-label')].map(node=>node.textContent)
 expect(labels.some(text=>/^第 3 版 · /.test(text??''))).toBe(true)
 expect(labels.some(text=>/^第 4 版 · /.test(text??''))).toBe(true)
 expect(container.querySelector('time[datetime="'+savedAt+'"]')).toBeTruthy()
 expect(container.textContent).not.toMatch(/父版本|固定版本|已另存为版本/)
 expect(container.querySelectorAll('details')).toHaveLength(0)
 expect(findTechnicalText(container,{systemIds})).toEqual([])
})

it('does not preselect a template that cannot be a migration target',async()=>{
 server()
 render(customer({initialTarget:oldConfirmation}))
 const select=await screen.findByLabelText('选择新模板') as HTMLSelectElement
 await screen.findByRole('option',{name:'学校 2026 模板 · 2026'})
 expect(select.value).toBe('')
 expect(document.activeElement).not.toBe(screen.getByRole('button',{name:'开始迁移'}))
})

it('words the customer migration in English',async()=>{
 server()
 setLocale('en')
 const {container}=render(customer({initialTarget:newConfirmation}))
 await screen.findByText('Downloaded Word files stay as they are. To export version 3 with the new template, migrate the manuscript to the new template first.')
 await screen.findByRole('option',{name:'学校 2026 模板 · 2026'})
 expect(container.textContent).toMatch(/Version 3/)
 // Template names are the school's own text; everything else is English.
 expect(container.textContent!.replace(/旧模板|学校 2026 模板|学院模板/g,'')).not.toMatch(/[一-鿿]/)
})

// B05 task 11: the customer migration page says what to choose and what is saved, without registering, version inputs
// or mapping wording; the staff page keeps its wording.
const pending:SchoolChange={...change,id:'change2',adopted_revision:null,input_sections:[{...change.input_sections[0],match_method:'bookmark'}],differences:[{kind:'text',location:'c1',message:'标题已更新',before:'原方法',after:'研究方法'}]}
function pendingServer(){
 const fetcher=server();const base=fetcher.getMockImplementation()!
 fetcher.mockImplementation(async(url:string,init?:RequestInit)=>url.endsWith('/school-changes')&&!init?.method?Response.json({items:[pending]}):url.endsWith('/school-changes/change2')?Response.json(pending):base(url,init))
}
const internal=/登记|版本输入|匹配并另存|对应章节|按原书签/
it('words every step of the customer migration in customer language',async()=>{
 pendingServer()
 const {container}=render(customer({initialTarget:newConfirmation}))
 const select=await screen.findByLabelText('选择新模板') as HTMLSelectElement
 await waitFor(()=>expect(select.value).toBe(newConfirmation))
 expect(screen.getByRole('option',{name:'请选择要改用的学校模板'})).toBeTruthy()
 expect(screen.getByRole('button',{name:'刷新'})).toBeTruthy()
 await waitFor(()=>expect(document.activeElement).toBe(screen.getByRole('button',{name:'开始迁移'})))
 expect(screen.getByRole('heading',{name:'迁移记录'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'查看此输入'}))
 await screen.findByRole('region',{name:'匹配与重要差异'})
 expect(screen.getByText('请为每一章选好在新模板中的位置。没选的内容不会被删掉，但要全部选好才能保存。')).toBeTruthy()
 expect(screen.getByText('按原文结构建议')).toBeTruthy()
 expect(screen.getByText(/^迁移后/).textContent).toContain('研究方法')
 expect((screen.getByRole('button',{name:'确认并保存为新的一版'}) as HTMLButtonElement).disabled).toBe(false)
 fireEvent.change(screen.getByLabelText('“原方法”放到新模板的哪一章'),{target:{value:''}})
 expect(screen.getByText('章节位置已修改，请先重新查看迁移后的变化。')).toBeTruthy()
 expect(screen.getByRole('button',{name:'查看迁移后的变化'})).toBeTruthy()
 expect(container.textContent).not.toMatch(internal)
 expect(container.querySelectorAll('details')).toHaveLength(0)
})
it('words every step of the customer migration in English',async()=>{
 pendingServer()
 setLocale('en')
 const {container}=render(customer({initialTarget:newConfirmation}))
 const select=await screen.findByLabelText('Choose the new template') as HTMLSelectElement
 await waitFor(()=>expect(select.value).toBe(newConfirmation))
 expect(screen.getByRole('button',{name:'Start the migration'})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'View this input'}))
 await screen.findByText('Suggested from the structure of the original')
 fireEvent.change(screen.getByLabelText('Chapter of the new template for “原方法”'),{target:{value:''}})
 expect(screen.getByRole('button',{name:'See the changes after migration'})).toBeTruthy()
 expect(container.textContent).not.toMatch(/Register|version input|Target chapter|Confirm mapping/i)
 expect(container.textContent!.replace(/旧模板|学校 2026 模板|学院模板|原方法|研究方法|方法正文|标题已更新/g,'')).not.toMatch(/[一-鿿]/)
})

it('keeps the staff migration page as it was',async()=>{
 server()
 const {container}=render(<SchoolChanges projectId="p1" manuscriptId="m1" version={version} currentRevision={3} active onAdopted={vi.fn()}/>)
 await screen.findByRole('option',{name:'学校 2026 模板 · 2026'})
 expect(screen.getByText('新绑定仅影响新建稿；历史稿继续使用原模板。')).toBeTruthy()
 expect(screen.getByText('基于固定版本 3；另存新版本，保留原稿与原导出。')).toBeTruthy()
 expect((screen.getByLabelText('迁移目标模板') as HTMLSelectElement).value).toBe('')
 expect(container.textContent).toMatch(/父版本 3/)
 expect(container.querySelectorAll('.version-label')).toHaveLength(0)
})
