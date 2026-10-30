import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import BioMatrixPreview from './BioMatrixPreview'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
it('loads the explicitly selected processed layer while retaining stable feature identity',async()=>{vi.mocked(apiFetch).mockResolvedValue(Response.json({features:[{id:'ENSG1',symbol:'DUP'},{id:'ENSG2',symbol:'DUP'}],observations:['AA-1'],values:[[0,2.5]]}));render(<BioMatrixPreview projectId="p1" processedId="processed1"/>);fireEvent.change(screen.getByLabelText('有界矩阵数据层'),{target:{value:'normalized'}});fireEvent.click(screen.getByText('读取处理层有界预览'));await screen.findByText('ENSG2');expect(vi.mocked(apiFetch).mock.calls[0][0]).toContain('layer=normalized');expect(screen.getByText('2.5')).toBeTruthy();expect(screen.getAllByText('DUP')).toHaveLength(2)})
