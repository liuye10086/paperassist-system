import {afterEach,expect,test,vi} from 'vitest'
import {cleanup,render,screen} from '@testing-library/react'
import AnalysisExplanation from '../explanations/AnalysisExplanation'
import ExternalSendReview from '../../shared/components/ExternalSendReview'
import {comparisonResult} from '../analysis/comparisonFixtures'
import {setLocale} from '../../shared/i18n'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
test('comparison explanation uses a general causality caution in English',()=>{
 setLocale('en');vi.stubGlobal('fetch',vi.fn(async()=>Response.json({current_revision:2,is_current:true,figure_id:'fig4',explanation:null,job:null,task:null})))
 render(<AnalysisExplanation base="/api/v1/projects/p1/files/f1" runId="run4" revision={2} figureId="fig4" source={comparisonResult.source as never} outputLanguage="en" modern comparison canGenerate={false} disabled={false} onBusyChange={()=>{}} configuration={{configured:false,model:null,message:''}}/>)
 expect(screen.getByText('AI draft—review it before use. The explanation uses verified statistical facts, the figure and the approved external summary. Results do not establish causality.')).toBeTruthy()
 expect(document.body.textContent).not.toContain('Correlation does not imply causation')
})
test('v5 comparison explanation preview states fact-only disclosure without raw values or pair IDs',()=>{
 setLocale('en')
 const disclosure={version:5,provider:'openai',task_type:'explanation',source_digest:'safe-digest',has_saved_result:false,source:{filename:'synthetic.xlsx',sheet_name:'Sheet1',dataset_version:2,parent_dataset_version:1,dataset_kind:'prepared'},summary:{valid_count:6,excluded_count:1,group_count:2,figure_kind:'group_boxplot',method:'welch_t',mode:null,output_language:'en',variable_count:1,variables:comparisonResult.variables,design:'independent',paired_direction:null,posthoc:'none',observation_basis:'independent_rows'},labels:[{key:'field:C',value:'Outcome'},{key:'unit:C',value:'kg'},{key:'group:0',value:'Treatment'},{key:'group:1',value:'Control'},{key:'figure_title',value:'Figure 1'},{key:'research_summary',value:''}]}
 render(<ExternalSendReview disclosure={disclosure as never} disabled={false} onCancel={()=>{}} onConfirm={()=>{}}/>)
 expect(screen.getByText('Send verified comparison facts, figure metadata and the approved summary to OpenAI; raw row values and pair IDs are excluded.')).toBeTruthy()
 expect(document.body.textContent).not.toContain('necessary included-group values')
 expect(document.body.textContent).not.toContain('paired connections use anonymous order')
})
