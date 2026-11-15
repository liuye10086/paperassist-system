import {fireEvent, within} from '@testing-library/react'

export const reportNarrativeStatus = {
 id: 'prepared-narrative', binding_sha256:'a'.repeat(64), bundle_sha256:'b'.repeat(64), artifact_sha256:'c'.repeat(64),
 task:{id:'narrative-task',status:'succeeded',revision:3},allowed_actions:[],model_calls:[],
 result:{narrative:{abstract:'Interpretation ready.',design_and_data:'Frozen study scope.',quality_control:'Quality reviewed.',
  methods_summary:'Saved methods.',key_findings:'Saved findings.',limitations:'Inference limited.',reader_cautions:'Review before use.'},figures:[]},
}

export function reportNarrativeResponse(url:string):Response|undefined {
 if(url.endsWith('/research-report-narratives/preview'))return Response.json({bundle_sha256:'b'.repeat(64),binding_sha256:reportNarrativeStatus.binding_sha256,
  model:'fixture-model',reserved_micro_usd:1000,real_calls_enabled:true,fact_count:1,figures:[]})
 if(url.endsWith('/research-report-narratives')||url.endsWith(`/research-report-narratives/${reportNarrativeStatus.id}`))return Response.json(reportNarrativeStatus)
}

export async function prepareReportNarrative(container:HTMLElement=document.body){
 const view=within(container)
 fireEvent.click(view.getByRole('button',{name:'生成详细解读'}))
 fireEvent.click(await view.findByRole('checkbox',{name:'我同意发送上述材料以生成详细解读'}))
 fireEvent.click(view.getByRole('button',{name:'确认材料并生成解读'}))
 await view.findByText(reportNarrativeStatus.result.narrative.abstract)
}
