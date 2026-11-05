import {useState} from 'react'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import AnalysisRequestOptions from './AnalysisRequestOptions'
import DesignForm from './DesignForm'
import {emptyDesign,emptyRequirement} from './state'
import type {Content} from './contracts'
afterEach(cleanup)

it('browses research depth without changing requirements and preserves selections across levels',()=>{
 const change=vi.fn();let latest:Content=emptyRequirement()
 function Form(){const [value,setValue]=useState<Content>({...emptyRequirement(),scope_items:[{id:'custom',title:'自定义范围',delivery_kind:'analysis',status:'completed',source:'已有结果'}]});return <AnalysisRequestOptions value={value} disabled={false} onChange={v=>{change(v);latest=v;setValue(v)}}/>}
 render(<Form/>);fireEvent.click(screen.getByRole('button',{name:'综合研究'}));expect(change).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('checkbox',{name:'多组学整合'}));fireEvent.click(screen.getByRole('button',{name:'基础分析'}));fireEvent.click(screen.getByRole('checkbox',{name:'差异分析'}))
 fireEvent.click(screen.getByRole('button',{name:'综合研究'}));expect((screen.getByRole('checkbox',{name:'多组学整合'}) as HTMLInputElement).checked).toBe(true)
 expect(latest.scope_items).toContainEqual({id:'custom',title:'自定义范围',delivery_kind:'analysis',status:'completed',source:'已有结果'})
 expect(latest.scope_items).toHaveLength(3)
})
it('keeps common capabilities available independently of research depth',()=>{
 render(<AnalysisRequestOptions value={emptyRequirement()} disabled={false} onChange={()=>{}}/>)
 fireEvent.click(screen.getByRole('button',{name:'通用需求'}));expect(screen.getByRole('checkbox',{name:'qPCR / 统计复核'})).toBeTruthy()
 expect(screen.queryByRole('checkbox',{name:'质量控制'})).toBeNull()
})
it('adds common experiments once, retains custom experiments and preserves a draft across modules',()=>{
 let latest:Content=emptyDesign();function Form(){const [value,setValue]=useState<Content>({...emptyDesign(),experiments:[{id:'custom',data_type:'原有实验'}]});return <DesignForm value={value} onChange={v=>{latest=v;setValue(v)}}/>}
 const {container}=render(<Form/>);fireEvent.click(screen.getByRole('button',{name:'添加 qPCR / RT-qPCR'}))
 expect((latest.experiments as {data_type:string}[]).map(e=>e.data_type)).toEqual(['原有实验','qPCR / RT-qPCR'])
 expect((screen.getByRole('button',{name:'已添加 qPCR / RT-qPCR'}) as HTMLButtonElement).disabled).toBe(true)
 const panel=container.querySelector('.intake-module-content') as HTMLDivElement;panel.scrollTop=120
 fireEvent.click(screen.getByRole('button',{name:'样本分组'}));expect(panel.scrollTop).toBe(0);panel.scrollTop=30;expect(screen.queryByRole('button',{name:'已添加 qPCR / RT-qPCR'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'通用实验'}));expect(panel.scrollTop).toBe(120);expect((screen.getAllByRole('textbox',{name:'数据类型'})[0] as HTMLInputElement).value).toBe('原有实验')
 expect(container.querySelector('details,summary')).toBeNull()
})
