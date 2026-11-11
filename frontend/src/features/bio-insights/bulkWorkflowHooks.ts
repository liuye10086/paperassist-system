import {useEffect,useRef,useState} from 'react'
import {onApiSessionChanged} from '../../shared/api/client'
import {safeError} from '../../shared/i18n'
import {insightRequest,jsonRequest} from './api'

export function useBulkRequest<T>() {
  const [data,setData]=useState<{signature:string;value:T}|null>(null)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [valid,setValid]=useState(true)
  const request=useRef<AbortController|null>(null)
  const allowed=useRef(true)
  useEffect(()=>{
    const stop=onApiSessionChanged(()=>{
      allowed.current=false
      request.current?.abort()
      request.current=null
      setValid(false)
      setBusy(false)
      setData(null)
      setError('')
    })
    return ()=>{request.current?.abort();stop()}
  },[])

  async function submit(url:string,body:unknown,signature:string) {
    if(request.current||!allowed.current) return
    const controller=new AbortController()
    request.current=controller
    setBusy(true)
    setData(null)
    setError('')
    try {
      const value=await insightRequest<T>(url,{...jsonRequest(body),signal:controller.signal},true)
      if(controller.signal.aborted) return
      setData({signature,value})
      return value
    } catch(cause) {
      if(!controller.signal.aborted) setError(safeError(cause,'读取失败，请刷新固定版本。'))
    } finally {
      if(request.current===controller) {
        request.current=null
        if(!controller.signal.aborted) setBusy(false)
      }
    }
  }
  function cancel() {
    request.current?.abort()
    request.current=null
    setBusy(false)
  }
  return {data,error,busy,valid,submit,cancel}
}
