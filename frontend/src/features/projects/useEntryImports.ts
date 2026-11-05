import {useEffect,useState} from 'react'
import {projectBase,researchRequest} from '../research-results/api'
import type {TaskPage} from '../tasks/taskTypes'
import type {EntryImport} from './analysisEntryState'

// Read only metadata from the existing paginated task list. Never start an import here.
export default function useEntryImports(projectId:string,active:boolean,location=''){
 const [data,setData]=useState<EntryImport[]|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false),[attempt,setAttempt]=useState(0)
 useEffect(()=>{
  if(!active)return
  const controller=new AbortController();let live=true
  setLoading(true);setError('')
  async function read(){
   const entries:EntryImport[]=[];let page=1,total=0
   do{
    const value=await researchRequest<TaskPage>(`${projectBase(projectId)}/tasks?task_type=bio_import&page=${page}&page_size=50`,{signal:controller.signal})
    if(!live)return
    for(const {task} of value.items){const input=task.input_version;if(task.project_id===projectId&&input.kind==='bio_import')entries.push({id:input.import_id,status:task.status,fileIds:input.source_file_ids,datasetId:input.dataset_id,versionId:task.result_bio_dataset_version_id??undefined,createdAt:task.created_at})}
    total=value.total;page++
   }while((page-1)*50<total)
   if(live)setData(entries)
  }
  void read().catch(()=>{if(live)setError('已有导入记录读取失败，请重试。')}).finally(()=>{if(live)setLoading(false)})
  return()=>{live=false;controller.abort()}
 },[projectId,active,attempt,location])
 return {data,error,loading,unknown:active&&(data===null||loading||!!error),refresh:()=>setAttempt(n=>n+1)}
}
