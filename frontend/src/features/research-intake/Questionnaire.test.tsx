import {useState} from 'react'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import RequirementForm from './RequirementForm'
import DeclaredField from './DeclaredField'
import {emptyRequirement} from './state'
import type {Content} from './contracts'
afterEach(cleanup)
it('preserves answers and existing scope across steps',()=>{
 let latest:Content=emptyRequirement()
 function Form(){const [value,setValue]=useState<Content>({...emptyRequirement(),scope_items:[{id:'custom',title:'已有范围',delivery_kind:'analysis',status:'completed',source:'客户'}],analysis_request:{notes:'保留说明'}});return <RequirementForm value={value} onChange={next=>{latest=next;setValue(next)}}/>}
 render(<Form/>);fireEvent.click(screen.getByRole('button',{name:'联系与排期'}));fireEvent.change(screen.getByLabelText('联系人'),{target:{value:'客户甲'}});fireEvent.click(screen.getByRole('button',{name:'分析需求'}));fireEvent.click(screen.getByLabelText('差异分析'))
 expect(latest.analysis_request).toEqual({notes:'保留说明'});expect(latest.scope_items).toContainEqual({id:'questionnaire.analysis.differential',title:'差异分析',delivery_kind:'analysis',status:'planned',source:'客户需求分步选择'});expect((latest.scope_items as {id:string}[]).some(x=>x.id==='custom')).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'联系与排期'}));expect((screen.getByLabelText('联系人') as HTMLTextAreaElement).value).toBe('客户甲');fireEvent.click(screen.getByRole('button',{name:'分析需求'}));expect((screen.getByLabelText('差异分析') as HTMLInputElement).checked).toBe(true)
})
it('allows direct input',()=>{let current:unknown;render(<DeclaredField label="研究问题" onChange={v=>{current=v}}/>);expect((screen.getByLabelText('研究问题') as HTMLTextAreaElement).disabled).toBe(false);fireEvent.change(screen.getByLabelText('研究问题'),{target:{value:'问题'}});expect(current).toEqual({state:'known',value:'问题'})})
it('uses a local date picker',()=>{let current:unknown;render(<DeclaredField label="首次交付时间" inputType="datetime-local" onChange={v=>{current=v}}/>);fireEvent.change(screen.getByLabelText('首次交付时间'),{target:{value:'2026-11-03T18:00'}});expect((current as {value:string}).value).toMatch(/(?:Z|[+-]\d\d:\d\d)$/)})
it('shows writing steps only for selected services and retains hidden writing answers',()=>{
 function Form(){const [value,setValue]=useState<Content>({...emptyRequirement(),sci_request:{journal:{state:'known',value:'已有期刊'}}});return <RequirementForm value={value} onChange={setValue}/>}
 render(<Form/>);expect(screen.queryByRole('button',{name:/SCI 需求/})).toBeNull();fireEvent.click(screen.getByLabelText('SCI 稿件'));fireEvent.click(screen.getByRole('button',{name:/SCI 需求/}));expect((screen.getByLabelText('目标期刊与候选') as HTMLTextAreaElement).value).toBe('已有期刊');fireEvent.click(screen.getByLabelText('SCI 稿件'));expect(screen.queryByRole('button',{name:/SCI 需求/})).toBeNull();fireEvent.click(screen.getByLabelText('SCI 稿件'));fireEvent.click(screen.getByRole('button',{name:/SCI 需求/}));expect((screen.getByLabelText('目标期刊与候选') as HTMLTextAreaElement).value).toBe('已有期刊')
})
it('removes the new QC option while preserving historical QC status and provenance',()=>{
 let latest:Content=emptyRequirement();function Form(){const [value,setValue]=useState<Content>({...emptyRequirement(),scope_items:[{id:'questionnaire.analysis.qc',title:'客户定制质控',delivery_kind:'analysis',status:'completed',source:'原有结果'}]});return <RequirementForm value={value} onChange={next=>{latest=next;setValue(next)}}/>};render(<Form/>);fireEvent.click(screen.getByRole('button',{name:'分析需求'}));expect(screen.queryByRole('checkbox',{name:'质量控制'})).toBeNull();fireEvent.click(screen.getByLabelText('差异分析'));expect(latest.scope_items).toContainEqual({id:'questionnaire.analysis.qc',title:'客户定制质控',delivery_kind:'analysis',status:'completed',source:'原有结果'})
})
it('shows research context, progress, optional contact and schedule without disclosure panels',()=>{
 const {container}=render(<RequirementForm value={{...emptyRequirement(),contact:{alias:{state:'known',value:'原有联系人'}},schedule:{priority:{state:'known',value:'先出质控'}}}} onChange={()=>{}}/>);
 expect(screen.queryByRole('heading',{name:'联系信息（选填）'})).toBeNull();expect(screen.getByRole('heading',{name:'现有进度'})).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'联系与排期'}));
 const contact=screen.getByRole('heading',{name:'联系信息（选填）'});screen.getByRole('heading',{name:'交付时间与优先级（选填）'});
 expect(container.querySelector('details,summary')).toBeNull();expect((screen.getByLabelText('联系人') as HTMLTextAreaElement).value).toBe('原有联系人');expect((screen.getByLabelText('优先内容') as HTMLTextAreaElement).value).toBe('先出质控');
 const question=screen.getByLabelText('核心研究问题');expect(question.compareDocumentPosition(contact)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();expect(contact).toBeTruthy()
})
