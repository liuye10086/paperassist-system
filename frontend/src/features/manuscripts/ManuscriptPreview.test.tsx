import {cleanup,render,screen,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ManuscriptPreview from './ManuscriptPreview'
import {snapshotFixture} from './manuscriptFixtures'
import type {Snapshot} from './manuscriptTypes'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
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
