import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import BioCoordinates from './BioCoordinates'
import {apiFetch} from '../../shared/api/client'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
it('shows raw barcode and unchanged coordinates after selecting a point',async()=>{
 vi.stubGlobal('URL',{...URL,createObjectURL:()=> 'blob:tissue',revokeObjectURL:vi.fn()});vi.mocked(apiFetch).mockImplementation(async url=>String(url).includes('coordinate-preview')?Response.json({image:{id:'im',download_url:'/api/v1/projects/p1/image'},width:100,height:80,scale:0.1,points:[{barcode:'AA-1',in_tissue:1,x:13,y:27}]}):new Response(new Blob(['x'])));render(<BioCoordinates projectId="p1" datasetId="d1" versionId="v1" members={[{id:'im',filename:'tissue.png',role:'tissue_image',verification_state:'verified'}]}/>);fireEvent.click(screen.getByText('读取原图坐标核对'));fireEvent.click(await screen.findByRole('button',{name:'AA-1'}));expect(screen.getByText('AA-1')).toBeTruthy();expect(screen.getByText('13, 27')).toBeTruthy()
})
