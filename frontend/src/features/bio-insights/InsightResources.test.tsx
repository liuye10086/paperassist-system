import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {useEffect,useState} from 'react'
import {ResourceForm} from './InsightResources'
import {defaultResource} from './state'
import {apiFetch} from '../../shared/api/client'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner',onApiSessionChanged:()=>()=>{}}))
afterEach(cleanup)
it('requires explicit resource provenance and maps only an existing file identity, never server paths',async()=>{vi.mocked(apiFetch).mockResolvedValue(Response.json({items:[{source_kind:'original_file',source_id:'f1',sha256:'a'.repeat(64),title:'local.tsv',filename:'local.tsv',parse_version_id:'parse1'}],total:1,page:1,page_size:20}));let body=defaultResource();function Harness(){const[v,set]=useState(body);useEffect(()=>{body=v},[v]);return <ResourceForm projectId="p1" value={v} onChange={set}/>};render(<Harness/>);await screen.findByRole('option',{name:/local.tsv/});fireEvent.change(screen.getByLabelText('资源文件版本'),{target:{value:'f1'}});fireEvent.click(screen.getByRole('button',{name:'加入资源文件'}));fireEvent.change(screen.getByLabelText('资源 release'),{target:{value:'synthetic-v1'}});fireEvent.change(screen.getByLabelText('使用依据'),{target:{value:'synthetic internal engineering fixture'}});expect(body.files[0]).toMatchObject({file_id:'f1',parse_version_id:'parse1',role:'term_gene',format:'tsv'});expect(body.release).toBe('synthetic-v1');expect(JSON.stringify(body)).not.toContain('path');expect(screen.getByText(/不代表完成序列/)).toBeTruthy()})
