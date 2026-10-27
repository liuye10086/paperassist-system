import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ExternalMaterials from './ExternalMaterials'
import { AnalysisActivity } from '../analysis/AnalysisActivity'

afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks()})
it('registers material title and declaration drafts for project leave and refresh protection',()=>{
  let guard=()=>true,dirty=()=>false
  vi.stubGlobal('fetch',vi.fn(()=>new Promise(()=>{})))
  const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
  render(<AnalysisActivity registerLeaveGuard={(g,d)=>{guard=g;dirty=d??(()=>false);return ()=>{}}}><ExternalMaterials projectId="p1" files={[]}/></AnalysisActivity>)
  expect(dirty()).toBe(false)
  fireEvent.change(screen.getByLabelText('材料标题'),{target:{value:'未保存的材料'}})
  fireEvent.change(screen.getByLabelText('缺项与使用限制'),{target:{value:'待核对'}})
  expect(dirty()).toBe(true);expect(guard()).toBe(false);expect(confirm).toHaveBeenCalledOnce()
  expect((screen.getByLabelText('材料标题') as HTMLInputElement).value).toBe('未保存的材料')
})
