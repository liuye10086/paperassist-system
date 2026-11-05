import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import UploadQuality from './UploadQuality'
import type {ProjectFile} from '../files/fileLibraryApi'

afterEach(cleanup)
const file=(id:string,type:string,status:ProjectFile['parse_status']='parsed'):ProjectFile=>({id,filename:id+'.'+type,file_type:type,parse_status:status,size_bytes:1,uploaded_at:'',error:null})
const base={loading:false,error:'',onReload:vi.fn()}
it('opens existing quality workflows before requirements and blocks unparsed tables',()=>{
 const navigate=vi.fn()
 const {container}=render(<UploadQuality {...base} files={[file('table','xlsx'),file('pending','xlsx','queued'),file('raw','bio_bundle','stored')]} onNavigate={navigate}/>)
 expect((screen.getByRole('button',{name:'检查表格 pending.xlsx'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'检查表格 table.xlsx'}))
 expect(navigate).toHaveBeenLastCalledWith({view:'quality',fileId:'table'})
 fireEvent.click(screen.getByRole('button',{name:'进入生信质量控制'}))
 expect(navigate).toHaveBeenLastCalledWith({view:'quality',fileId:'',bio:{view:'bio-datasets',fileId:''}})
 expect(container.querySelector('details,summary')).toBeNull()
})
it('keeps stale data inaccessible during a failed refresh and provides recovery',()=>{
 const reload=vi.fn()
 render(<UploadQuality {...base} files={[file('old','xlsx')]} error="读取失败" onReload={reload} onNavigate={vi.fn()}/>)
 expect(screen.queryByRole('button',{name:'检查表格 old.xlsx'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'重新读取材料'}));expect(reload).toHaveBeenCalledOnce()
})
it('directs an empty project to upload',()=>{
 const navigate=vi.fn();render(<UploadQuality {...base} files={[]} onNavigate={navigate}/>)
 fireEvent.click(screen.getByRole('button',{name:'上传文件'}));expect(navigate).toHaveBeenCalledWith({view:'upload',fileId:''})
})
