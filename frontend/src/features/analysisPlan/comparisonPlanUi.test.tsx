import {afterEach,expect,test,vi} from 'vitest'
import {cleanup,render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnalysisPlanLauncher from './AnalysisPlanLauncher'
import {v3Plan} from './batch02Fixtures'
import {comparisonSelection,groupOptions} from '../analysis/comparisonFixtures'
import {setLocale} from '../../shared/i18n'
import AnalysisPlanReview from './AnalysisPlanReview'
import {v3Review} from './batch02Fixtures'
import {comparisonPlan} from '../analysis/comparisonFixtures'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
const fields=[{column:'A',name:'Participant ID'},{column:'C',name:'Outcome',numeric:true,unit:'kg'},{column:'D',name:'Group',numeric:false},{column:'F',name:'Before',numeric:true,unit:'kg'},{column:'G',name:'After',numeric:true,unit:'kg'}]
function mount(initial?:unknown){vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>String(input).includes('comparison-group-options')?new Response(JSON.stringify(groupOptions)):new Response(JSON.stringify({items:[],total:0,page:1,page_size:5}))));render(<AnalysisPlanLauncher projectId="p1" fileId="f1" source={v3Plan.source as never} selection={{task_type:'descriptive_boxplot',sheet_name:v3Plan.source.sheet_name,numeric_column:'C',group_column:'D',unit:'kg',missing_policy:'exclude_selected_missing'}} initialSelection={initial as never} fields={fields} setupRevision={2} disabled={false} onPublished={()=>{}}/>)}
test('six comparison methods are available and full group options preserve user selection order',async()=>{
 mount();const user=userEvent.setup();await user.selectOptions(screen.getByLabelText('计划方法'),'welch_t')
 await user.selectOptions(screen.getByLabelText('结局数值列'),'C');await user.selectOptions(screen.getByLabelText('分组列'),'D')
 await screen.findByLabelText('纳入 Control（3 行）');await user.click(screen.getByLabelText('纳入 Control（3 行）'));await user.click(screen.getByLabelText('纳入 Treatment（3 行）'))
 expect(screen.getByText('参与组顺序：Control → Treatment')).toBeTruthy()
 expect(screen.getByText('仅纳入已选组；未选组和缺失行将说明排除原因。')).toBeTruthy()
 expect(fetch).toHaveBeenCalledWith(expect.stringContaining('comparison-group-options?dataset_id='),expect.anything())
 expect(screen.getByLabelText('计划方法').querySelectorAll('option').length).toBe(13)
})
test('same-looking numeric and textual groups remain separately identifiable in the local selector',async()=>{
 mount();vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>Response.json(String(input).includes('comparison-group-options')?{...groupOptions,row_count:6,options:[{kind:'number',value:'1',label:'1',count:3},{kind:'text',value:'1',label:'1',count:3}]}:{items:[],total:0,page:1,page_size:5})))
 const user=userEvent.setup();await user.selectOptions(screen.getByLabelText('计划方法'),'welch_t');await user.selectOptions(screen.getByLabelText('结局数值列'),'C');await user.selectOptions(screen.getByLabelText('分组列'),'D')
 expect(await screen.findByLabelText('纳入 1（数值）（3 行）')).toBeTruthy()
 expect(screen.getByLabelText('纳入 1（文本）（3 行）')).toBeTruthy()
})
test('paired form exposes ID audit, frozen difference direction and complete pairs in English',async()=>{
 setLocale('en');mount({...comparisonSelection,design:'paired',method:'wilcoxon',groups:[],numeric_column:null,group_column:null,pair_id_column:'A',before_column:'F',after_column:'G',missing_policy:'complete_pairs',assumptions:{independent_units:false,distribution:'unknown',inference_confirmed:false}})
 expect(screen.getByLabelText('Pair ID column')).toBeTruthy()
 expect(screen.getByText('Difference direction: Before − After.')).toBeTruthy()
 expect(screen.getByText('IDs must be present and unique in every source row; an incomplete measurement excludes the entire pair.')).toBeTruthy()
 expect(screen.getByText('Pair IDs stay local and are excluded from model materials.')).toBeTruthy()
 await waitFor(()=>expect(screen.queryByText('分析计划')).toBeNull())
})
test('comparison review waits for excluded-group acknowledgement and an explicit separate approval',async()=>{
 const issue={id:'group_not_selected:all',code:'group_not_selected',severity:'warning',field:null,count:1,coordinates:['D8'],message:'server text',allowed_resolutions:['retain']}
 const review={...v3Review,selection:comparisonSelection,research_request:comparisonPlan.research_request,check:{...comparisonPlan.check,issues:[issue],limitations:['研究设计及分布前提由用户确认，程序检查不能证明独立性、正态性或差值对称性。']}}
 const fetch=vi.fn(async(_url:string,init?:RequestInit)=>Response.json(init?.method==='POST'?{...review.task,status:'running',display_status:'running'}:review));vi.stubGlobal('fetch',fetch)
 render(<AnalysisPlanReview projectId="p1" taskId="t1"/>)
 const button=await screen.findByRole('button',{name:'确认并发布分析计划'})
 expect((button as HTMLButtonElement).disabled).toBe(true)
 expect(fetch.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
 await userEvent.selectOptions(screen.getByLabelText('处理：部分组未纳入（数据区域）'),'retain')
 expect((button as HTMLButtonElement).disabled).toBe(false)
 await userEvent.click(button)
 const decision=fetch.mock.calls.find(([,init])=>init?.method==='POST')
 expect(JSON.parse(String(decision?.[1]?.body))).toMatchObject({operation:'approve',resolutions:{'group_not_selected:all':'retain'},plan_revision:1})
 expect(JSON.parse(String(decision?.[1]?.body))).not.toHaveProperty('selection')
})
test('missing pair IDs block confirmation and preserve actionable local diagnosis in English',async()=>{
 setLocale('en')
 const issue={id:'pair_id_missing:all',code:'pair_id_missing',severity:'blocking',field:null,count:1,coordinates:['A8'],message:'secret id',allowed_resolutions:[]}
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({...v3Review,selection:comparisonSelection,check:{...comparisonPlan.check,issues:[issue],selection_check:{...comparisonPlan.check.selection_check,ready:false}}})))
 render(<AnalysisPlanReview projectId="p1" taskId="t1"/>)
 expect(await screen.findByText('Missing pair ID')).toBeTruthy()
 expect(screen.getByText('Pair IDs must be present and unique in all source rows, including rows with missing measurements.')).toBeTruthy()
 expect((screen.getByRole('button',{name:'Approve and publish analysis plan'}) as HTMLButtonElement).disabled).toBe(true)
 expect(document.body.textContent).not.toContain('secret id')
})
