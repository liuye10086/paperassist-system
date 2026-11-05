import {useEffect,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {useI18n} from '../../shared/i18n'
import {manuscriptBase,validManuscript,type Manuscript} from '../manuscripts/manuscriptTypes'
import {taskRequest} from './taskApi'
import type {TaskWorkspace} from './taskTypes'

type Target={id:string;revision:number}
export default function ManuscriptTaskLinks({workspace,active}:{workspace:TaskWorkspace;active:boolean}){
 const {t}=useI18n(),{task,artifacts}=workspace
 const input=task.input_version
 const supported=['manuscript_writing','manuscript_draft','manuscript_docx'].includes(task.task_type)
 const versionId=input.kind==='manuscript_writing'?input.base_version_id:input.kind==='manuscript'?input.manuscript_version_id:''
 const artifact=artifacts.manuscript
 const direct=task.task_type!=='manuscript_writing'&&artifact&&artifact.version_id===versionId?{id:artifact.id,revision:artifact.revision}:null
 const [target,setTarget]=useState<Target|null>(null),[error,setError]=useState(''),[sessionValid,setSessionValid]=useState(true)
 useEffect(()=>onApiSessionChanged(()=>{setSessionValid(false);setTarget(null)}),[])
 useEffect(()=>{
  setTarget(null);setError('')
  if(!supported||!active||!sessionValid)return
  if(!versionId){setError('任务缺少固定稿件版本，无法定位。');return}
  if(direct){setTarget(direct);return}
  const controller=new AbortController();let live=true
  void taskRequest(manuscriptBase(task.project_id),controller,(v):v is {items:Manuscript[]}=>!!v&&typeof v==='object'&&'items'in v&&Array.isArray(v.items)&&v.items.every(m=>validManuscript(m,task.project_id)),'稿件历史读取失败，请重试。').then(result=>{
   if(!live)return
   const matches=result.items.flatMap(m=>m.versions.filter(v=>v.id===versionId&&(input.kind!=='manuscript_writing'||v.revision===input.base_revision)).map(v=>({id:m.id,revision:v.revision})))
   if(matches.length===1)setTarget(matches[0]);else setError('无法唯一定位任务关联的固定稿件版本。')
  }).catch(()=>{if(live)setError('稿件历史读取失败，请重试。')})
  return()=>{live=false;controller.abort()}
 },[supported,active,sessionValid,task.project_id,task.task_type,versionId,input.kind,input.kind==='manuscript_writing'?input.base_revision:0,artifact?.id,artifact?.version_id,artifact?.revision])
 if(!supported||!sessionValid)return null
 const view=task.task_type==='manuscript_writing'?'writing':task.task_type==='manuscript_docx'?'exports':'body'
 const label=task.task_type==='manuscript_writing'?'返回稿件写作':task.task_type==='manuscript_docx'?'查看此版本的 Word':'查看此版本稿件'
 return <>{error&&<p role="status">{t(error)}</p>}{target&&<p><a href={`#project=${encodeURIComponent(task.project_id)}&section=manuscripts&view=${view}&manuscript=${encodeURIComponent(target.id)}&revision=${target.revision}`}>{t(label)}</a></p>}</>
}
