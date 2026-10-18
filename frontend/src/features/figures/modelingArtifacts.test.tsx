import {afterEach,expect,test,vi} from 'vitest'
import {cleanup,render,screen} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BoxplotFigure from './BoxplotFigure'
import AnalysisExplanation from '../explanations/AnalysisExplanation'
import WordReport from '../reports/WordReport'
import {modelingRocFixture} from '../analysis/modelFixtures'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
const source=modelingRocFixture.source
const props={base:'/api/v1/projects/p1/files/f1',runId:'r1',revision:1,source:source as never,canGenerate:true,disabled:false,onBusyChange:()=>{},modern:true,artifactVersion:4 as const,planSha:modelingRocFixture.analysis_plan.sha256,outputLanguage:'en' as const}
const figure={source,source_sha256:source.source_sha256,id:'fig4',analysis_run_id:'r1',setup_revision:1,schema_version:4,figure_kind:'roc_curve',language:'en',plan_sha256:props.planSha,title:'Figure 1. ROC',caption:'Synthetic ROC',x_label:'Group',y_label:'Outcome',sha256:'f'.repeat(64),created_at:'2026-10-14T00:00:00Z',engine:{id:'openai_modeling_plot_v4',provider:'openai',model:'synthetic'},verification:{status:'matched',note:'Checked'}}
const explanation={source,source_sha256:source.source_sha256,id:'exp4',analysis_run_id:'r1',figure_id:'fig4',figure_sha256:figure.sha256,setup_revision:1,schema_version:4,language:'en',plan_sha256:props.planSha,created_at:figure.created_at,engine:{id:'analysis_explanation_v4',provider:'openai',model:'synthetic'},verification:{status:'references_checked',note:'Checked'},sections:['purpose','data','methods','results','interpretation','paper_text'].map(key=>({key,title:key,text:'Synthetic '+key,evidence:[]})),limitations:[],provenance:{}}
test('modeling plot opens v6 external preview and waits for an independent send action',async()=>{
 const preview={version:6,provider:'openai',task_type:'boxplot',source_digest:'digest',has_saved_result:false,source:{filename:'synthetic.xlsx',sheet_name:source.sheet_name,dataset_version:source.dataset_version,parent_dataset_version:source.parent_dataset_version,dataset_kind:'prepared'},summary:{valid_count:2,excluded_count:0,group_count:0,figure_kind:'roc_curve',method:'roc_auc',mode:null,output_language:'en',variable_count:2,variables:modelingRocFixture.variables,verification_scope:'independent_curve_calculation',outbound_data:'necessary_anonymous_observations'},labels:[{key:'field:A',value:'Outcome'},{key:'unit:A',value:''},{key:'field:B',value:'Score'},{key:'unit:B',value:''}]}
 const fetch=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('/plot-config')?{configured:true,message:'',model:'synthetic'}:url.endsWith('/disclosure')?preview:{current_revision:1,is_current:true,figure:null,job:null,task:null}));vi.stubGlobal('fetch',fetch)
 render(<BoxplotFigure {...props} filename="synthetic.xlsx" figureKind="roc_curve"/>)
 await userEvent.click(await screen.findByRole('button',{name:'使用 OpenAI 生成ROC 曲线'}))
 expect(await screen.findByRole('button',{name:'确认发送并生成'})).toBeTruthy()
 expect(screen.getByLabelText('确认外发字段 A')).toBeTruthy()
 expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
 expect(fetch.mock.calls.some(([url,init])=>url.endsWith('/boxplot')&&init?.method==='POST')).toBe(false)
})
test.each(['figure','explanation','report'] as const)('rejects modeling %s with the wrong frozen schema or plan',async kind=>{
 const item=kind==='figure'?{...figure,plan_sha256:'d'.repeat(64)}:kind==='explanation'?{...explanation,schema_version:2}:{...explanation,schema_version:2,engine:{id:'word_analysis_report_v4'},filename:'report.docx',explanation_id:'exp4'}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/plot-config')?{configured:false,message:'',model:null}:{current_revision:1,is_current:true,ready:true,figure_id:'fig4',[kind]:item,job:null,task:null,issues:[]})))
 render(kind==='figure'?<BoxplotFigure {...props} figureKind="roc_curve"/>:kind==='explanation'?<AnalysisExplanation {...props} figureId="fig4" configuration={{configured:false,message:'',model:null}}/>:<WordReport {...props} figureId="fig4" explanationId="exp4"/>)
 expect(await screen.findAllByText('数据来源或版本不一致，请重新载入配置。')).toBeTruthy()
})
test('saved modeling figure explanation and Word chain restores without model requests',async()=>{
 const report={...explanation,schema_version:4,engine:{id:'word_analysis_report_v4'},filename:'report.docx',explanation_id:'exp4',size_bytes:3000,sha256:'b'.repeat(64)}
 const fetch=vi.fn(async(url:string,init?:RequestInit)=>Response.json(url.endsWith('/plot-config')?{configured:false,message:'',model:null}:url.endsWith('/boxplot')?{current_revision:1,is_current:true,figure,job:null,task:null}:url.endsWith('/explanation')?{current_revision:1,is_current:true,figure_id:'fig4',explanation,job:null,task:null}:init?.method==='POST'?null:{current_revision:1,is_current:true,ready:true,report,issues:[],task:null}));vi.stubGlobal('fetch',fetch)
 render(<BoxplotFigure {...props} figureKind="roc_curve"/>)
 expect(await screen.findByRole('img',{name:'Figure 1. ROC'})).toBeTruthy()
 expect(await screen.findByText('Synthetic results')).toBeTruthy()
 expect(await screen.findByRole('link',{name:'下载 Word 报告'})).toBeTruthy()
 expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
})
