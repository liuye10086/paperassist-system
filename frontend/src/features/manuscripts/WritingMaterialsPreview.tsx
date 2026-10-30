import {useEffect,useRef,useState} from 'react'
import {useI18n,safeError} from '../../shared/i18n'
import {onApiSessionChanged} from '../../shared/api/client'
import {taskRequest} from '../tasks/taskApi'
import {manuscriptBase} from './manuscriptTypes'

type Preview={can_execute:false;scope:'writing_material_preview';materials_sha256:string;materials:Record<string,unknown>}
function valid(v:unknown):v is Preview{return !!v&&typeof v==='object'&&'can_execute'in v&&v.can_execute===false&&'scope'in v&&v.scope==='writing_material_preview'&&'materials_sha256'in v&&typeof v.materials_sha256==='string'&&/^[a-f0-9]{64}$/.test(v.materials_sha256)&&'materials'in v&&!!v.materials&&typeof v.materials==='object'}
export default function WritingMaterialsPreview({projectId,manuscriptId,revision,active}:{projectId:string;manuscriptId:string;revision:number;active:boolean}){
 const {t}=useI18n(),[preview,setPreview]=useState<Preview|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[session,setSession]=useState(true)
 const controller=useRef<AbortController|null>(null)
 useEffect(()=>{const stop=onApiSessionChanged(()=>{controller.current?.abort();setSession(false);setPreview(null)});return()=>{controller.current?.abort();stop()}},[])
 async function read(){if(controller.current||!session)return;const c=new AbortController();controller.current=c;setBusy(true);setError('');try{const value=await taskRequest(`${manuscriptBase(projectId)}/${encodeURIComponent(manuscriptId)}/versions/${revision}/writing-materials`,c,valid,'稿件资料读取失败，请刷新。');if(!c.signal.aborted)setPreview(value)}catch(cause){if(!c.signal.aborted)setError(safeError(cause,'稿件资料读取失败，请刷新。'))}finally{if(controller.current===c)controller.current=null;if(!c.signal.aborted)setBusy(false)}}
 return <section hidden={!active} aria-label={t('固定写作资料预览')}><button type="button" disabled={busy||!session} onClick={()=>void read()}>{t('查看固定写作资料')}</button><p>{t('仅预览所选版本资料，不代表执行授权。')}</p>{error&&<p role="alert">{t(error)}</p>}{preview&&<><p>SHA256 · {preview.materials_sha256}</p><pre>{JSON.stringify(preview.materials,null,2)}</pre></>}</section>
}
