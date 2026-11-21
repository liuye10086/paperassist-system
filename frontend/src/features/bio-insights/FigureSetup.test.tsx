import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {useEffect,useState} from 'react'
import FigureSetup from './FigureSetup'
import type {Config} from './contracts'
import {defaultConfig,buildPlan} from './state'
import {apiFetch} from '../../shared/api/client'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner',onApiSessionChanged:()=>()=>{}}))
afterEach(cleanup)
it('selects a saved composition for redraw without a differential contrast or threshold',()=>{
 let latest:Config={...defaultConfig('figure'),q_threshold:.05,minimum_absolute_effect:1}
 function Editor(){const [config,set]=useState(latest);return <FigureSetup projectId="p" config={config} sources={[]} onChange={value=>{latest=value;set(value)}}/>}
 render(<Editor/>)
 fireEvent.change(screen.getByLabelText('图型'),{target:{value:'single_cell_composition'}})
 expect(latest.figure_type).toBe('single_cell_composition')
 expect(latest.contrast_id).toBeUndefined()
 expect(screen.queryByLabelText('图件比较 ID')).toBeNull()
 expect(screen.queryByLabelText('显示 Top N（不改变完整表）')).toBeNull()
 expect(screen.getByText(/读取已保存的供者组成表/)).toBeTruthy()
})
it('uses an explicit color scale for the CellChat heatmap',()=>{
 let latest={...defaultConfig('figure'),figure_type:'topic_cellchat'}
 function Editor(){const [config,set]=useState<Config>(latest);return <FigureSetup projectId="p" config={config} sources={[]} onChange={next=>{latest={...next,figure_type:String(next.figure_type)};set(next)}}/>}
 render(<Editor/>)
 expect(screen.getByLabelText('通讯热图色阶')).toHaveProperty('value','viridis')
 expect(screen.queryByLabelText('配色（逐行 #RRGGBB）')).toBeNull()
 fireEvent.change(screen.getByLabelText('通讯热图色阶'),{target:{value:'custom'}})
 expect(screen.getByLabelText('配色（逐行 #RRGGBB）')).toBeTruthy()
 fireEvent.change(screen.getByLabelText('图型'),{target:{value:'topic_slingshot'}})
 expect(latest).not.toHaveProperty('cellchat_colormap')
})
it('binds display thresholds and drops them when the figure changes',()=>{
 let latest=defaultConfig('figure')
 function Editor(){const [config,set]=useState(latest);return <FigureSetup projectId="p" config={config} sources={[]} onChange={next=>{latest=next;set(next)}}/>}
 render(<Editor/>)
 expect(screen.getByLabelText('着色 q 阈值')).toHaveProperty('value','0.05')
 fireEvent.change(screen.getByLabelText('着色 q 阈值'),{target:{value:'0'}})
 fireEvent.change(screen.getByLabelText('着色最小绝对效应'),{target:{value:'1.5'}})
 expect(latest).toMatchObject({q_threshold:0,minimum_absolute_effect:1.5})
 fireEvent.change(screen.getByLabelText('图型'),{target:{value:'enrichment'}})
 expect(latest).not.toHaveProperty('minimum_absolute_effect')
 expect(screen.getByLabelText('展示条目最大 q／FDR（留空显示全部）')).toHaveProperty('value','')
 fireEvent.change(screen.getByLabelText('展示条目最大 q／FDR（留空显示全部）'),{target:{value:'0.1'}})
 expect(latest.q_threshold).toBe(.1)
 fireEvent.change(screen.getByLabelText('图型'),{target:{value:'topic_genie3'}})
 expect(latest).not.toHaveProperty('q_threshold')
 fireEvent.change(screen.getByLabelText('显示调控边 Top N'),{target:{value:'45'}})
 expect(latest.regulation_top_n).toBe(45)
})
it('offers saved-value topic figures and clears irrelevant comparison selections',()=>{
 let value:Config={...defaultConfig('figure'),contrast_id:'old',processed_source_id:'old',expression_groups:[{label:'x',observation_keys:[]}],feature_ids:['gene'],z_score:true}
 function Harness(){const [c,set]=useState(value);return <FigureSetup projectId="p1" config={c} onChange={v=>{value=v;set(v)}} sources={[]}/>}
 render(<Harness/>)
 expect(Array.from(screen.getByLabelText('图型').querySelectorAll('option'),o=>o.value)).toEqual(expect.arrayContaining(['topic_slingshot','topic_genie3','topic_cellchat']))
 fireEvent.change(screen.getByLabelText('图型'),{target:{value:'topic_cellchat'}})
 expect(value.contrast_id).toBeUndefined();expect(value.processed_source_id).toBeUndefined();expect(value.expression_groups).toEqual([]);expect(value.feature_ids).toEqual([])
 expect(screen.queryByLabelText('图件比较 ID')).toBeNull()
 expect(screen.getByText(/读取已保存的专题数值/)).toBeTruthy()
})
it('does not request a result table before a primary result is selected',async()=>{vi.mocked(apiFetch).mockClear();vi.mocked(apiFetch).mockResolvedValue(Response.json({items:[],total:0,matched_total:0}));render(<FigureSetup projectId="p1" config={defaultConfig('figure')} onChange={vi.fn()} sources={[]}/>);expect(screen.getByText('请先在固定来源中添加对应角色。')).not.toBeNull();await waitFor(()=>expect(apiFetch).not.toHaveBeenCalled())})
it('retains the original figure types and binds a GSEA curve to its real stable term row',async()=>{let c:Config={...defaultConfig('figure'),result_source_id:'r1'};vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).includes('/tables/')?{columns:['row_key','term_id','NES'],items:[{row_key:'term-row1',term_id:'TERM0',NES:'0'}],total:1,matched_total:1,page:1,page_size:100}:{id:'r1',members:[{id:'m1',key:'enrichment_results',format:'tsv'}]}));function Harness(){const[v,set]=useState(c);useEffect(()=>{c=v as typeof c},[v]);return <FigureSetup projectId="p1" config={v} onChange={set} sources={[]}/>};render(<Harness/>);expect(Array.from(screen.getByLabelText('图型').querySelectorAll('option'),o=>o.value)).toEqual(expect.arrayContaining(['distribution','volcano','heatmap','enrichment','gsea','venn','upset','candidate_evidence']));fireEvent.change(screen.getByLabelText('图型'),{target:{value:'gsea'}});await screen.findByRole('option',{name:/TERM0/});fireEvent.change(screen.getByLabelText('GSEA 精确 term 行'),{target:{value:'term-row1'}});await waitFor(()=>expect(c.term_row_key).toBe('term-row1'));const body=buildPlan('curve',c,[],0,'draft');expect(body.config).not.toHaveProperty('q_threshold');expect(body.config).not.toHaveProperty('minimum_absolute_effect')})

it('describes actual group mean log1p heatmap values',()=>{render(<FigureSetup projectId="p1" config={{...defaultConfig('figure'),figure_type:'heatmap'}} onChange={vi.fn()} sources={[]}/>);expect(screen.getByText(/组均值 log1p 表达，未经按基因标准化/)).toBeTruthy();expect(screen.queryByText(/按基因 z-score/)).toBeNull()})
it('retains spatial heatmap semantics when a stored version has the new empty sample defaults',()=>{render(<FigureSetup projectId="p1" config={{...defaultConfig('figure'),figure_type:'heatmap',sample_groups:[],analysis_layer:'analysis',z_score:false,expression_groups:[{label:'A',observation_keys:[{processed_version_id:'old',barcode:'b'}]}]}} onChange={vi.fn()} sources={[]}/>);expect(screen.getByLabelText('热图观察轴')).toHaveProperty('value','spatial');expect(screen.getByText(/组均值 log1p 表达，未经按基因标准化/)).toBeTruthy()})
it('keeps the generic enrichment default and supports explicit adjusted-metric ordering',()=>{
 function Harness(){
  const [config,setConfig]=useState<Config>({...defaultConfig('figure'),figure_type:'enrichment'})
  return <FigureSetup projectId="p1" config={config} onChange={setConfig} sources={[]}/>
 }
 render(<Harness/>)
 expect(screen.getByLabelText('富集条目排序')).toHaveProperty('value','')
 expect(screen.getByLabelText('富集条目 Top N')).toBeTruthy()
 fireEvent.change(screen.getByLabelText('图型'),{target:{value:'volcano'}})
 fireEvent.change(screen.getByLabelText('图型'),{target:{value:'enrichment'}})
 expect(screen.getByLabelText('富集条目排序')).toHaveProperty('value','')
 fireEvent.change(screen.getByLabelText('富集条目排序'),{target:{value:'adjusted_metric_term_id'}})
 expect(screen.getByLabelText('富集条目排序')).toHaveProperty('value','adjusted_metric_term_id')
})
