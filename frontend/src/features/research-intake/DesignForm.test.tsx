import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import DesignForm from './DesignForm'
import {emptyDesign} from './state'
import {apiFetch} from '../../shared/api/client'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
const sampleData = {
  ...emptyDesign(),
  groups: [{id:'g1', experiment_id:'trial', name:'对照组'}],
  samples: [{id:'s1', experiment_id:'trial', group_id:'g1', tissue:{state:'known',value:'肺组织'}}],
}

it('lets the customer map samples to a group before an analyst has defined the experiment', async () => {
  const changed = vi.fn()
  vi.mocked(apiFetch).mockResolvedValue(Response.json({samples:sampleData.samples, conflicts:[]}))
  render(<DesignForm projectId="p1" mode="customerSamples" value={sampleData} onChange={changed}/>)
  expect(screen.queryByRole('button', {name:'统计与比较'})).toBeNull()
  fireEvent.click(screen.getByRole('button', {name:'样本表映射'}))
  fireEvent.change(screen.getByRole('combobox', {name:'所属实验'}), {target:{value:'trial'}})
  fireEvent.change(screen.getByLabelText('样本表文本'), {target:{value:'id,group_id\ns1,g1'}})
  fireEvent.click(screen.getByRole('button', {name:'预览样本表映射'}))
  await screen.findByText('预览样本 1 条')
  expect(JSON.parse(String(vi.mocked(apiFetch).mock.calls[0][1]?.body))).toMatchObject({experiment_id:'trial',group_ids:['g1']})
  fireEvent.click(screen.getByRole('button', {name:'将预览样本加入草稿'}))
  expect(changed).toHaveBeenCalledWith(expect.objectContaining({groups:sampleData.groups,samples:sampleData.samples}))
})

it('shows submitted sample facts read only and leaves the assigned analyst in charge of statistical design', () => {
  render(<DesignForm mode="assignedDesign" value={sampleData} onChange={vi.fn()}/>)
  fireEvent.click(screen.getByRole('button', {name:'样本分组'}))
  expect(screen.getByText('对照组')).toBeTruthy()
  expect(screen.queryByRole('textbox', {name:'分组名称'})).toBeNull()
  fireEvent.click(screen.getByRole('button', {name:'样本信息'}))
  expect(screen.getByText('肺组织')).toBeTruthy()
  expect(screen.queryByRole('button', {name:'添加样本信息'})).toBeNull()
  expect(screen.queryByRole('button', {name:'样本表映射'})).toBeNull()
  fireEvent.click(screen.getByRole('button', {name:'统计与比较'}))
  expect(screen.getByLabelText('配对与重复结构')).toHaveProperty('disabled',false)
  expect(screen.getByRole('button', {name:'多组学对应'})).toBeTruthy()
})
it('previews a persisted XLSX sheet before explicitly adding mapped samples',async()=>{
 const sample={id:'s1',experiment_id:'e1',group_id:'g1',donor:{state:'pending',value:null},file_id:'f1'};vi.mocked(apiFetch).mockResolvedValue(Response.json({samples:[sample],conflicts:[],gaps:[],source:{file_id:'f1'}}));const changed=vi.fn();render(<DesignForm projectId="p1" value={{...emptyDesign(),experiments:[{id:'e1',data_type:'visium'}],groups:[{id:'g1',experiment_id:'e1',name:'Control'}]}} onChange={changed} sources={[{kind:'file',id:'f1',name:'samples.xlsx'}]}/>);fireEvent.click(screen.getByRole('button',{name:'样本表映射'}));fireEvent.change(screen.getByRole('combobox',{name:'所属实验'}),{target:{value:'e1'}});fireEvent.change(screen.getByRole('combobox',{name:'样本表来源'}),{target:{value:'f1'}});fireEvent.click(screen.getByText('预览样本表映射'));await screen.findByText('预览样本 1 条');expect(changed).not.toHaveBeenCalled();const body=JSON.parse(String(vi.mocked(apiFetch).mock.calls[0][1]?.body));expect(body).toEqual({file_id:'f1',sheet:0,mapping:{id:'id',group_id:'group_id'},experiment_id:'e1',group_ids:['g1']});fireEvent.click(screen.getByText('将预览样本加入草稿'));await waitFor(()=>expect(changed.mock.lastCall?.[0].samples).toEqual([sample]))
})
