import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import JournalSourceForm from './JournalSourceForm'
import type {Profile} from './contracts'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
const profile:Profile={id:'p-old',project_id:'p1',created_at:'2026-10-23T00:00:00Z',name:'synthetic test',source_type:'synthetic',source_text:'Cancer. Fee USD 100.',official_url:'',source_url:'',source_status:'available',verified_on:'2026-10-23',conditions:'local test',permission:'user provided',fields:{},synthetic:true,verification_level:'synthetic_material_only'}
it('previews selected public material with item IDs for verbatim field evidence',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({source:{},items:[{id:'paragraph-1',kind:'paragraph',text:'Original public scope.',location:{page:1}}],page:1,page_size:20,total:1})))
 render(<JournalSourceForm projectId="p1" profiles={[]} materials={[{kind:'document_version',id:'d1',file_id:'f1',label:'Public source'}]} busy={false} onSave={vi.fn()}/>)
 fireEvent.change(screen.getByLabelText('来源公共资料（可选）'),{target:{value:'document_version:d1'}})
 expect(await screen.findByText('Original public scope.')).toBeTruthy();expect(screen.getByText('paragraph-1')).toBeTruthy()
})
it('sends structured numeric fee applicability and rejects non-verbatim quotations',async()=>{
 const save=vi.fn(async(_value:import('./contracts').ProfileRequest)=>false);render(<JournalSourceForm projectId="p1" profiles={[profile]} materials={[]} busy={false} onSave={save}/>);fireEvent.change(screen.getByLabelText('以已有资料另存新版本'),{target:{value:'p-old'}})
 const detail=screen.getByText('费用 · 未知').closest('details')!;fireEvent.click(within(detail).getByText('费用 · 未知'));fireEvent.change(screen.getByLabelText('费用状态'),{target:{value:'verified'}})
 fireEvent.change(within(detail).getByLabelText('费用金额'),{target:{value:'100'}});fireEvent.change(within(detail).getByLabelText('逐字原文引文'),{target:{value:'Made up fee'}});fireEvent.change(within(detail).getByLabelText('原文位置 / 材料条目 ID'),{target:{value:'paragraph 1'}})
 fireEvent.click(screen.getByRole('button',{name:'保存期刊资料新版本'}));expect(await screen.findByRole('alert')).toBeTruthy();expect(save).not.toHaveBeenCalled()
 fireEvent.change(within(detail).getByLabelText('逐字原文引文'),{target:{value:'Fee USD 100.'}});fireEvent.change(within(detail).getByLabelText('费用适用文章类型'),{target:{value:'research'}});fireEvent.change(within(detail).getByLabelText('费用适用 OA'),{target:{value:'true'}});fireEvent.click(screen.getByRole('button',{name:'保存期刊资料新版本'}));await waitFor(()=>expect(save).toHaveBeenCalledTimes(1));expect(save.mock.calls[0][0].fields.fee).toMatchObject({value:{amount:100,currency:'USD'},applicability:{article_types:['research'],oa:true}})
})

it('recovers a failed public material preview without changing the selected frozen version',async()=>{
 const fetch=vi.fn().mockResolvedValueOnce(Response.json({}, {status:503})).mockResolvedValueOnce(Response.json({items:[{id:'fixed-item',text:'Recovered fixed original'}],total:1}));vi.stubGlobal('fetch',fetch);render(<JournalSourceForm projectId="p1" profiles={[]} materials={[{kind:'document_version',id:'d1',file_id:'f1',label:'Public source'}]} busy={false} onSave={vi.fn()}/>);fireEvent.change(screen.getByLabelText('来源公共资料（可选）'),{target:{value:'document_version:d1'}});await screen.findByRole('alert');fireEvent.click(screen.getByRole('button',{name:'重试读取来源材料'}));await screen.findByText('Recovered fixed original');expect(fetch.mock.calls[1][0]).toBe(fetch.mock.calls[0][0]);expect(screen.queryByRole('alert')).toBeNull()
})
