import {act,cleanup,renderHook} from '@testing-library/react'
import {afterEach,beforeEach,expect,it} from 'vitest'
import {useState} from 'react'
import {clearApiSession,setApiSession} from '../../shared/api/client'
import useManuscriptPendingRequest from './useManuscriptPendingRequest'

const scope={projectId:'p1',manuscriptId:'m1',versionId:'v1',operation:'exports'}
beforeEach(()=>{sessionStorage.clear();setApiSession('csrf','owner')})
afterEach(()=>{cleanup();clearApiSession();sessionStorage.clear()})
it('persists the exact request before sending and restores it without adopting edited input',()=>{
 const first=renderHook(()=>{const [,setBusy]=useState(false);return {...useManuscriptPendingRequest(scope),setBusy}});let key=''
 act(()=>{first.result.current.setBusy(true);const request=first.result.current.begin('/exports',{language:'en'});key=request!.key
  expect(Object.values(sessionStorage).some(raw=>raw.includes(key))).toBe(true)
  expect(first.result.current.begin('/exports',{language:'zh-CN'})).toBeNull()
 })
 first.unmount();const again=renderHook(()=>useManuscriptPendingRequest(scope))
 expect(again.result.current.pending).toMatchObject({key,url:'/exports',body:'{"language":"en"}',phase:'unknown'})
 act(()=>expect(again.result.current.begin('/exports',{language:'en'})?.key).toBe(key))
 act(()=>again.result.current.complete())
 expect(again.result.current.pending).toBeNull()
})
it('isolates fixed versions and rejects operations after the session changes',()=>{
 const first=renderHook(()=>useManuscriptPendingRequest(scope))
 act(()=>{first.result.current.begin('/exports',{})})
 const other=renderHook(()=>useManuscriptPendingRequest({...scope,versionId:'v2'}))
 expect(other.result.current.pending).toBeNull()
 act(()=>setApiSession('other','another-owner'))
 act(()=>expect(first.result.current.begin('/exports',{})).toBeNull())
 expect(first.result.current.pending).toBeNull()
})
