import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import LiteratureClaims from './LiteratureClaims'
import LiteratureAssistance from './LiteratureAssistance'
import CitationWorkspace from './CitationWorkspace'
import AssistanceResult from './AssistanceResult'
import {setLocale} from '../../shared/i18n'
import {literatureTask} from './fixtures'
const stamp='2026-10-19T01:00:00Z',page=(items:unknown[])=>({project_id:'p1',items,total:items.length,page:1,page_size:10})
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it.each([['zh-CN','en'],['en','zh-CN']] as const)('keeps model result limitations in saved output language (%s / %s)',(ui,language)=>{
 setLocale(ui);render(<AssistanceResult outputLanguage={language} kind="evidence_review" result={{status:'needs_review',relevance:'uncertain',reason:'Original suggestion reason 原文',narrowed_statement:'',limitations:['Original limitation'],evidence_ids:[]}}/>)
 expect(screen.getByText(language==='en'?/Model suggestion, pending manual decision/:/模型建议，尚非人工决定/)).toBeTruthy();expect(screen.getByText('Original suggestion reason 原文')).toBeTruthy()
})
it.each([['zh-CN','en'],['en','zh-CN']] as const)('keeps claim limits and exhausted supplementary guidance in saved %s / %s language',(ui,language)=>{
 setLocale(ui);const claim={id:'claim1',project_id:'p1',revision:1,content:'Original user claim 原文',context:'',output_language:language,created_at:stamp,updated_at:stamp,versions:[{revision:1,content:'Original user claim 原文',output_language:language,created_at:stamp}],is_current:true,supplement:{task_id:'search1',round:1,limit:20}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.includes('/claims/claim1?')?claim:url.includes('/claims?')?page([claim]):page([]))))
 render(<LiteratureClaims projectId="p1" referenceId="ref1" source={null} onDenied={vi.fn()} onSelection={vi.fn()}/>);
 return (async()=>{await screen.findByRole('option',{name:'Original user claim 原文'});fireEvent.change(screen.getByLabelText(ui==='en'?'Choose claim':'选择论述'),{target:{value:'claim1'}})
 expect(await screen.findByText(language==='en'?'If evidence remains insufficient after one supplementary search (up to 20 candidates), add actual materials, narrow the claim and review it again; no further search is added automatically.':'补搜一轮（最多 20 篇）后仍不足时，请补充实际材料、收窄论述并重新人工核验；不会自动追加补搜。')).toBeTruthy()
 expect((screen.getByRole('button',{name:ui==='en'?'Create supplementary search':'创建补搜任务'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.change(screen.getByLabelText(ui==='en'?'Claim output language':'论述输出语言'),{target:{value:language==='en'?'zh-CN':'en'}})
 expect(screen.getByText(language==='en'?'Abstract evidence cannot establish full text details. Successful parsing does not establish claim support.':'仅摘要证据不能证明全文细节；解析成功不代表支持论述。')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:ui==='en'?'Narrow claim':'收窄论述'}));expect(document.activeElement).toBe(screen.getByLabelText(ui==='en'?'Claim text':'论述文本'))
 fireEvent.click(screen.getByRole('button',{name:ui==='en'?'Review manually again':'重新人工核验'}));expect(document.activeElement).toBe(screen.getByLabelText(ui==='en'?'Manual review reason':'人工核验理由'))
 })()
})
it.each([['zh-CN','en'],['en','zh-CN']] as const)('uses saved suggestion language even after changing the unsaved task language (%s / %s)',async(ui,language)=>{
 setLocale(ui);const task={...literatureTask,id:'assist1',task_type:'literature_assistance',phase:'plan',input_version:{kind:'literature_assistance',workflow_version:'literature_assistance_v1',assistance_kind:'search_plan',input_digest:'a'.repeat(64),output_language:language}}
 const assistance={task,kind:'search_plan',input_version:task.input_version,result:null,real_calls_enabled:false}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/assist1')?assistance:page([assistance]))))
 render(<LiteratureAssistance projectId="p1" researchTopic="Original topic" referenceId="" selection={null} onDenied={vi.fn()}/>);fireEvent.click(await screen.findByRole('button',{name:ui==='en'?'View suggestion and wait status':'查看建议与等待状态'}))
 const expected=language==='en'?'No model suggestion is available. Check the waiting or failure status.':'当前任务尚无模型建议，请查看等待或失败状态。'
 expect(await screen.findByText(expected)).toBeTruthy();fireEvent.change(screen.getByLabelText(ui==='en'?'Model task output language':'模型任务输出语言'),{target:{value:language==='en'?'zh-CN':'en'}});expect(screen.getByText(expected)).toBeTruthy()
})
it('keeps saved citation explanations in their version language while the editable language changes',async()=>{
 const draft={id:'draft1',version_id:'version1',project_id:'p1',revision:1,current_revision:1,is_current:true,created_at:stamp,current_changes:[],snapshot:{schema_version:1,draft_id:'draft1',version_id:'version1',project_id:'p1',revision:1,title:'Original draft',output_language:'en',format:'nlm_numeric_journal_v1',paragraphs:[{id:'p1',fragments:[{kind:'text',text:'Frozen original paragraph'}]}],output:{text:'Frozen original paragraph',paragraphs:[{id:'p1',text:'Frozen original paragraph'}],references:[]}}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/config')?{project_id:'p1',format:'nlm_numeric_journal_v1',real_model_calls:false}:url.endsWith('/drafts/draft1')?draft:page(url.includes('/drafts?')?[draft]:[]))))
 render(<CitationWorkspace projectId="p1" onDenied={vi.fn()} onVerify={vi.fn()}/>);fireEvent.click(await screen.findByRole('button',{name:'打开样稿'}));await screen.findByLabelText('样稿输出语言');fireEvent.change(screen.getByLabelText('样稿输出语言'),{target:{value:'zh-CN'}})
 await waitFor(()=>expect(screen.getByText('The text and references below come from this frozen version; save a new version to update them.')).toBeTruthy());expect(screen.getByText('Frozen original paragraph',{selector:'.citation-output'})).toBeTruthy()
})
