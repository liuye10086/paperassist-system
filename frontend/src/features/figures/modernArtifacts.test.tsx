import {afterEach,expect,test,vi} from 'vitest'
import {cleanup,render,screen} from '@testing-library/react'
import BoxplotFigure from './BoxplotFigure'
import AnalysisExplanation from '../explanations/AnalysisExplanation'
import WordReport from '../reports/WordReport'
import {correlationResult} from '../analysis/correlationFixtures'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
const source=correlationResult.source
const props={base:'/api/v1/projects/p1/files/f1',runId:'run3',revision:2,source,canGenerate:true,disabled:false,onBusyChange:()=>{},modern:true,outputLanguage:'en' as const}
const figure={source,source_sha256:source.source_sha256,id:'fig3',analysis_run_id:'run3',setup_revision:2,schema_version:2,figure_kind:'scatter',language:'en',title:'Figure 1. Correlation',caption:'Synthetic scatter',x_label:'weight',y_label:'height',sha256:'f'.repeat(64),created_at:'2026-10-14T00:00:00Z',engine:{id:'openai_analysis_plot_v2',provider:'openai',model:'synthetic'},verification:{status:'matched',note:'Checked'}}
const explanation={source,source_sha256:source.source_sha256,id:'exp3',analysis_run_id:'run3',figure_id:'fig3',figure_sha256:figure.sha256,setup_revision:2,schema_version:2,language:'en',created_at:figure.created_at,engine:{id:'analysis_explanation_v2',provider:'openai',model:'synthetic'},verification:{status:'references_checked',note:'Checked'},sections:[{key:'results',title:'Main results',text:'Synthetic explanation',evidence:[]}],limitations:[],provenance:{}}
test('restores modern same-language explanation verified against references without any model POST',async()=>{
 const fetch=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('/explanation')?{current_revision:2,is_current:true,figure_id:'fig3',explanation,job:null,task:null}:{current_revision:2,is_current:true,ready:false,issues:[],report:null,task:null}));vi.stubGlobal('fetch',fetch)
 render(<AnalysisExplanation {...props} figureId="fig3" configuration={{configured:false,message:'',model:null}} />)
 expect(await screen.findByText('Synthetic explanation')).toBeTruthy()
 expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
})
test.each(['figure','explanation','report'] as const)('rejects a current %s in the wrong output language',async kind=>{
 const item=kind==='figure'?{...figure,language:'zh-CN'}:kind==='explanation'?{...explanation,language:'zh-CN'}:{...explanation,engine:{id:'word_analysis_report_v2'},filename:'report.docx',explanation_id:'exp3',language:'zh-CN'}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/openai/')?{configured:false,message:'',model:null}:{current_revision:2,is_current:true,ready:true,figure_id:'fig3',[kind]:item,job:null,task:null,issues:[]})))
 render(kind==='figure'?<BoxplotFigure {...props} figureKind="scatter"/>:kind==='explanation'?<AnalysisExplanation {...props} figureId="fig3" configuration={{configured:false,message:'',model:null}}/>:<WordReport {...props} figureId="fig3" explanationId="exp3"/>)
 expect(await screen.findAllByText('数据来源或版本不一致，请重新载入配置。')).toBeTruthy()
 expect(screen.queryByText('Synthetic explanation')).toBeNull()
})
test('keeps archived Chinese figure readable under its saved version without generation',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/boxplot')?{current_revision:3,is_current:false,figure:{...figure,schema_version:undefined,figure_kind:undefined,language:'zh-CN',engine:{...figure.engine,id:'openai_boxplot_v1'}},job:null,task:null}:{configured:false,message:'',model:null})))
 render(<BoxplotFigure {...props} canGenerate={false} figureKind="scatter"/>)
 expect(await screen.findByRole('img',{name:'Figure 1. Correlation'})).toBeTruthy()
 expect(screen.getByText('历史结果')).toBeTruthy()
})
test('retains a v2 English result legacy Chinese artifact and permits a separate modern preview',async()=>{
 const fetch=vi.fn(async(url:string)=>Response.json(url.endsWith('/boxplot')?{current_revision:2,is_current:true,generation_compatible:false,figure:{...figure,figure_kind:undefined,schema_version:undefined,language:'zh-CN',engine:{...figure.engine,id:'openai_boxplot_v1'}},job:null,task:null}:url.endsWith('/plot-config')?{configured:true,message:'',model:'synthetic'}:{current_revision:2,is_current:true,figure_id:'fig3',explanation:null,report:null,ready:false,issues:[],job:null,task:null}));vi.stubGlobal('fetch',fetch)
 render(<BoxplotFigure {...props} figureKind="boxplot" legacyFallbackAllowed={true}/>)
 expect(await screen.findByRole('img',{name:'Figure 1. Correlation'})).toBeTruthy()
 expect(screen.getByText('已保存的旧中文成果仍可查看和下载；生成新成果将使用已确认的英文任务语言。')).toBeTruthy()
 expect((screen.getByRole('button',{name:'使用 OpenAI 生成箱线图'}) as HTMLButtonElement).disabled).toBe(false)
})
