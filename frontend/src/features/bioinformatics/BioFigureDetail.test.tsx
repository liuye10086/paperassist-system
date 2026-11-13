import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import BioFigureDetail,{BioFigureComposer} from './BioFigureDetail'
import {processedFixture,rawFixture} from './spatialFixtures'
import type {BioFigure,FigureConfig} from './spatialContracts'
import {setLocale} from '../../shared/i18n'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),captureApiSession:()=>()=>true,getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks();vi.unstubAllGlobals();setLocale('zh-CN')})
const config:FigureConfig={kind:'spatial_gene',color_by:'cluster',gene_ids:['ENSG2'],layer:'counts',title:'Old',palette:'viridis',vmin:null,vmax:null,width:1800,height:1500,dpi:300,output_language:'en'}
const previous=(value:FigureConfig):BioFigure=>({id:'figure1',root_id:'root1',version:1,processed_source:processedFixture.source,annotation_version_id:null,config:value,manifest_sha256:'f'.repeat(64),members:[]})
it('allows single-cell annotation UMAP only with a verified matching manual label version',async()=>{
 const result={...processedFixture,manifest:{assay:'single_cell'}}
 vi.mocked(apiFetch).mockImplementation(async(_url,init)=>Response.json(init?.method==='POST'?{id:'figann'}:{items:[{id:'ann1',set_id:'s1',name:'Manual',version:1,raw_source:rawFixture,processed_dataset_version_id:result.id,origin:'manual'},{id:'foreign',set_id:'s2',name:'Foreign',version:1,raw_source:rawFixture,processed_dataset_version_id:'other',origin:'manual'}]}))
 render(<BioFigureComposer projectId="p1" result={result} onNavigate={()=>{}}/>)
 expect(screen.getByRole('option',{name:'人工注释'})).toBeTruthy()
 fireEvent.change(screen.getByLabelText('图片类型'),{target:{value:'annotation'}})
 expect((screen.getByRole('button',{name:'生成独立单图版本'}) as HTMLButtonElement).disabled).toBe(true)
 await screen.findByRole('option',{name:'Manual · 已保存'})
 expect(screen.queryByRole('option',{name:'Foreign · 已保存'})).toBeNull()
 fireEvent.change(screen.getByLabelText('人工注释来源'),{target:{value:'ann1'}})
 fireEvent.click(screen.getByRole('button',{name:'生成独立单图版本'}))
 await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.some(c=>c[1]?.method==='POST')).toBe(true))
 const post=vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST')!
 expect(post[0]).toBe('/api/v1/projects/p1/bio-figures')
 expect(JSON.parse(String(post[1]?.body))).toMatchObject({annotation_version_id:'ann1',config:{kind:'annotation'}})
})
it.each([['integration_covariates','协变量校正前后对比图'],['integration_harmony','批次整合前后对比图']])('opens %s as a read-only published figure with preview and download',async (kind,label)=>{
 vi.stubGlobal('URL',class extends URL{static createObjectURL=()=> 'blob:integration';static revokeObjectURL=vi.fn()})
 const download='/api/v1/projects/p1/bio-figures/figure1/members/image1/download'
 const figure={...previous(config),config:{...config,kind},members:[{id:'image1',key:kind,format:'png',filename:`${kind}.png`,size_bytes:3,sha256:'a'.repeat(64),download_url:download}]}
 vi.mocked(apiFetch).mockImplementation(async url=>String(url)===download?new Response(new Blob(['PNG'],{type:'image/png'})):Response.json(String(url).includes('bio-processed-datasets')?processedFixture:figure))
 render(<BioFigureDetail projectId="p1" figureId="figure1" onNavigate={()=>{}}/>)
 expect(await screen.findByRole('img',{name:label})).toBeTruthy()
 expect(vi.mocked(apiFetch).mock.calls.some(([url])=>String(url).includes('bio-processed-datasets'))).toBe(false)
 expect(screen.getByRole('link',{name:'下载 PNG'}).getAttribute('href')).toBe(download)
 expect(screen.queryByRole('heading',{name:'查看高级图件配置'})).toBeNull()
 expect(screen.getByText('此图记录整合处理前后的实际结果，可查看和下载。')).toBeTruthy()
 expect(screen.queryByText('单图配置与版本')).toBeNull()
 expect(screen.queryByRole('button',{name:'生成独立单图版本'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'高级配置'}))
 expect(screen.getByRole('heading',{name:'查看高级图件配置'})).toBeTruthy()
 expect(screen.getByText('1800 × 1500')).toBeTruthy()
 expect(screen.queryByText('vmax')).toBeNull()
})
it('adds only the published PNG member from a fixed figure to the delivery candidates',async()=>{
 const download='/api/v1/projects/p1/bio-figures/figure1/members/image1/download'
 const member={id:'image1',key:'umap',format:'png',filename:'umap.png',size_bytes:3,sha256:'a'.repeat(64),download_url:download}
 const figure={...previous({...config,kind:'umap'}),members:[member,{...member,id:'data1',format:'csv',filename:'values.csv'}]}
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>init?.method==='POST'?Response.json({file_id:'added',filename:'analysis-figure-c0d35d33e8c0.png',format:'png'}):
  String(url)===download?new Response(new Blob(['PNG'],{type:'image/png'})):Response.json(String(url).includes('bio-processed-datasets')?processedFixture:figure))
 render(<BioFigureDetail projectId="p1" figureId="figure1" onNavigate={()=>{}} deliveryTarget={{assignmentRevision:3}}/>)
 fireEvent.click(await screen.findByRole('button',{name:'加入交付候选 · UMAP 聚类图.png'}))
 expect(screen.queryByRole('button',{name:'加入交付候选 · values.csv'})).toBeNull()
 await screen.findByText('已加入交付候选 · UMAP 聚类图.png')
 const attach=vi.mocked(apiFetch).mock.calls.find(([url])=>String(url).endsWith('/analyst-workspace/delivery-artifacts'))
 expect(JSON.parse(String(attach?.[1]?.body))).toEqual({assignment_revision:3,kind:'bio_figure_png',version_id:'figure1',member_id:'image1'})
})
it('creates only a figure request with a frozen source and explicit output language',async()=>{vi.mocked(apiFetch).mockResolvedValue(Response.json({id:'figure1'}));const navigate=vi.fn();render(<BioFigureComposer projectId="p1" result={processedFixture} onNavigate={navigate}/>);fireEvent.change(screen.getByLabelText('图片标题'),{target:{value:'My figure'}});fireEvent.change(screen.getByLabelText('图片语言'),{target:{value:'zh-CN'}});fireEvent.click(screen.getByText('生成独立单图版本'));await waitFor(()=>expect(navigate).toHaveBeenCalledWith({view:'bio-figure',fileId:'',figureId:'figure1'}));const call=vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST');expect(call?.[0]).toBe('/api/v1/projects/p1/bio-figures');expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({processed_source:processedFixture.source,expected_version:0,config:{title:'My figure',output_language:'zh-CN'}});expect(vi.mocked(apiFetch).mock.calls.every(c=>!String(c[0]).includes('/bio-analysis-runs'))).toBe(true)})
it('freezes PCA coloring by an actual mapping field without inferring donors',async()=>{vi.mocked(apiFetch).mockResolvedValue(Response.json({id:'figure1'}));render(<BioFigureComposer projectId="p1" result={processedFixture} onNavigate={()=>{}}/>);fireEvent.change(screen.getByLabelText('图片类型'),{target:{value:'pca'}});fireEvent.change(screen.getByLabelText('颜色分组来源'),{target:{value:'batch'}});fireEvent.click(screen.getByText('生成独立单图版本'));await waitFor(()=>expect(apiFetch).toHaveBeenCalled());const body=JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST')?.[1]?.body));expect(body.config).toMatchObject({kind:'pca',color_by:'batch'});expect(screen.getByText('未知映射单独显示为 unknown，不代表独立重复。')).toBeTruthy()})
it.each(['marker_dotplot','marker_heatmap'])('switching to %s fixes mean-log1p colors and preserves selected stable genes',async kind=>{vi.mocked(apiFetch).mockResolvedValue(Response.json({id:'figure2'}));render(<BioFigureComposer projectId="p1" result={processedFixture} previous={previous(config)} onNavigate={()=>{}}/>);fireEvent.change(screen.getByLabelText('图片类型'),{target:{value:kind}});const layer=screen.getByLabelText('表达层') as HTMLSelectElement;expect(layer.value).toBe('log1p');expect(layer.disabled).toBe(true);fireEvent.click(screen.getByText('生成独立单图版本'));await waitFor(()=>expect(apiFetch).toHaveBeenCalled());const body=JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST')?.[1]?.body));expect(body.config).toMatchObject({kind,layer:'log1p',gene_ids:['ENSG2']})})
it.each([['pca','variance'],['qc','distribution'],['qc','violin'],['qc','scatter'],['qc','mitochondrial'],['qc','sample_id'],['qc','section'],['qc','batch']])('editing %s/%s retains that exact frozen panel',async(kind,panel)=>{vi.mocked(apiFetch).mockResolvedValue(Response.json({id:'figure2'}));render(<BioFigureComposer projectId="p1" result={processedFixture} previous={previous({...config,kind,panel} as FigureConfig)} onNavigate={()=>{}}/>);fireEvent.change(screen.getByLabelText('图片标题'),{target:{value:'Changed title'}});fireEvent.change(screen.getByLabelText('色盘'),{target:{value:'magma'}});expect((screen.getByLabelText('图片面板') as HTMLSelectElement).value).toBe(panel);fireEvent.click(screen.getByText('生成独立单图版本'));await waitFor(()=>expect(apiFetch).toHaveBeenCalled());const body=JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST')?.[1]?.body));expect(body.config).toMatchObject({kind,panel,title:'Changed title',palette:'magma'})})
it('resets an incompatible panel when switching kinds and sends an explicit default for old responses',async()=>{vi.mocked(apiFetch).mockResolvedValue(Response.json({id:'figure2'}));render(<BioFigureComposer projectId="p1" result={processedFixture} previous={previous({...config,kind:'pca',panel:'variance'} as FigureConfig)} onNavigate={()=>{}}/>);fireEvent.change(screen.getByLabelText('图片类型'),{target:{value:'umap'}});const panels=screen.getByLabelText('图片面板') as HTMLSelectElement;expect(panels.value).toBe('default');expect(Array.from(panels.options).map(v=>v.value)).toEqual(['default','scores']);fireEvent.change(screen.getByLabelText('图片面板'),{target:{value:'scores'}});fireEvent.change(screen.getByLabelText('图片类型'),{target:{value:'pca'}});expect((screen.getByLabelText('图片面板') as HTMLSelectElement).value).toBe('scores');fireEvent.click(screen.getByText('生成独立单图版本'));await waitFor(()=>expect(apiFetch).toHaveBeenCalled());const body=JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST')?.[1]?.body));expect(body.config).toMatchObject({kind:'pca',panel:'scores'})})
it('normalizes a legacy config with no panel to the explicit default without changing the kind',async()=>{vi.mocked(apiFetch).mockResolvedValue(Response.json({id:'figure2'}));render(<BioFigureComposer projectId="p1" result={processedFixture} previous={previous({...config,kind:'pca'})} onNavigate={()=>{}}/>);fireEvent.change(screen.getByLabelText('图片标题'),{target:{value:'Legacy title edit'}});fireEvent.click(screen.getByText('生成独立单图版本'));await waitFor(()=>expect(apiFetch).toHaveBeenCalled());const body=JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST')?.[1]?.body));expect(body.config).toMatchObject({kind:'pca',panel:'default',title:'Legacy title edit'})})
it('hides unused layer and color limits for categorical plots and clears stale expression bounds',async()=>{vi.mocked(apiFetch).mockResolvedValue(Response.json({id:'figure2'}));render(<BioFigureComposer projectId="p1" result={processedFixture} previous={previous({...config,vmin:1,vmax:8})} onNavigate={()=>{}}/>);expect((screen.getByLabelText('色阶下限') as HTMLInputElement).value).toBe('1');fireEvent.change(screen.getByLabelText('图片类型'),{target:{value:'pca'}});expect(screen.queryByLabelText('表达层')).toBeNull();expect(screen.queryByLabelText('色阶下限')).toBeNull();expect(screen.queryByLabelText('色阶上限')).toBeNull();fireEvent.click(screen.getByText('生成独立单图版本'));await waitFor(()=>expect(apiFetch).toHaveBeenCalled());const body=JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST')?.[1]?.body));expect(body.config).toMatchObject({kind:'pca',vmin:null,vmax:null,layer:'log1p'});fireEvent.change(screen.getByLabelText('图片类型'),{target:{value:'spatial_gene'}});expect((screen.getByLabelText('色阶下限') as HTMLInputElement).value).toBe('')})

it('orders marker pages naturally while preserving every other image position and source array',async()=>{
 const {orderMarkerPngMembers}=await import('./markerFigureOrder')
 const keys=['qc_png','marker_dotplot_page_10_png','umap_png','marker_dotplot_page_2_png','marker_dotplot_png','marker_heatmap_page_2_png','pca_png','marker_heatmap_png']
 const members=keys.map(key=>({key}))
 expect(orderMarkerPngMembers(members).map(m=>m.key)).toEqual(['qc_png','marker_dotplot_png','umap_png','marker_dotplot_page_2_png','marker_dotplot_page_10_png','marker_heatmap_png','pca_png','marker_heatmap_page_2_png'])
 expect(members.map(m=>m.key)).toEqual(keys)
})
