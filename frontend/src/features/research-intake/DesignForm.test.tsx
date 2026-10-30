import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import DesignForm from './DesignForm'
import {emptyDesign} from './state'
import {apiFetch} from '../../shared/api/client'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
it('previews a persisted XLSX sheet before explicitly adding mapped samples',async()=>{
 const sample={id:'s1',experiment_id:'e1',group_id:'g1',donor:{state:'pending',value:null},file_id:'f1'};vi.mocked(apiFetch).mockResolvedValue(Response.json({samples:[sample],conflicts:[],gaps:[],source:{file_id:'f1'}}));const changed=vi.fn();render(<DesignForm projectId="p1" value={{...emptyDesign(),experiments:[{id:'e1',data_type:'visium'}],groups:[{id:'g1',experiment_id:'e1',name:'Control'}]}} onChange={changed} sources={[{kind:'file',id:'f1',name:'samples.xlsx'}]}/>);fireEvent.change(screen.getByRole('combobox',{name:'所属实验'}),{target:{value:'e1'}});fireEvent.change(screen.getByRole('combobox',{name:'样本表来源'}),{target:{value:'f1'}});fireEvent.click(screen.getByText('预览样本表映射'));await screen.findByText('预览样本 1 条');expect(changed).not.toHaveBeenCalled();const body=JSON.parse(String(vi.mocked(apiFetch).mock.calls[0][1]?.body));expect(body).toEqual({file_id:'f1',sheet:0,mapping:{id:'id',group_id:'group_id'},experiment_id:'e1',group_ids:['g1']});fireEvent.click(screen.getByText('将预览样本加入草稿'));await waitFor(()=>expect(changed.mock.lastCall?.[0].samples).toEqual([sample]))
})
