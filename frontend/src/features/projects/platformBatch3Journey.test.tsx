import {act, cleanup, fireEvent, render, renderHook, screen, waitFor} from '@testing-library/react'
import {afterEach, expect, it, vi} from 'vitest'
import { ProjectJourneyNextAction } from './ProjectJourney'
import ProjectDetails from './ProjectDetails'
import useProjectSelection from './useProjectSelection'
import {flowBlockReason} from './useProjectFlow'
import {setApiSession} from '../../shared/api/client'
import type {Project} from './projectTypes'

const project:Project={id:'p1',name:'项目',research_topic:'主题',project_type:'research',file_count:1,created_at:'',updated_at:''}
afterEach(()=>{cleanup();vi.unstubAllGlobals();sessionStorage.clear();window.history.replaceState(null,'','/')})

it('offers a next upload action from project information',()=>{
 const onUpload=vi.fn();render(<ProjectJourneyNextAction onUpload={onUpload}/>)
 fireEvent.click(screen.getByRole('button',{name:'下一步：上传矩阵与样本材料'}));expect(onUpload).toHaveBeenCalledTimes(1)
})
it('keeps result viewing separate from whether a working page was visited',()=>{
 expect(flowBlockReason(4,{hasFiles:false,requirementSaved:false,reached:0,existingResults:false})).toBe('')
 expect(flowBlockReason(3,{hasFiles:false,requirementSaved:false,reached:4,existingResults:true})).toContain('选择并保存需求')
})
it('preserves a material detail when history returns through another section',async()=>{
 window.history.replaceState(null,'','/#project=p1&section=files&view=detail&file=f1')
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json(project)))
 const {result}=renderHook(()=>useProjectSelection(vi.fn(),vi.fn()));await waitFor(()=>expect(result.current.project).toBeTruthy())
 act(()=>result.current.changeSection('analysis'));act(()=>result.current.changeOverviewView('settings'))
 act(()=>window.history.back());await waitFor(()=>expect(result.current.section).toBe('analysis'))
 expect(result.current.resourceNavigation).toEqual({view:'detail',fileId:'f1'})
})
it('restores project text drafts after remount and keeps cancel independent without writing',()=>{
 setApiSession('test','owner');const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher)
 const first=render(<ProjectDetails project={project} onUpdated={vi.fn()}/>);fireEvent.change(screen.getByLabelText('修改项目名称'),{target:{value:'名称草稿'}});fireEvent.change(screen.getByLabelText('修改研究主题'),{target:{value:'主题草稿'}});first.unmount()
 const second=render(<ProjectDetails project={project} onUpdated={vi.fn()}/>);expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe('名称草稿');expect((screen.getByLabelText('修改研究主题') as HTMLTextAreaElement).value).toBe('主题草稿')
 fireEvent.click(screen.getByRole('button',{name:'取消修改：项目名称'}));second.unmount();render(<ProjectDetails project={project} onUpdated={vi.fn()}/>);expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe(project.name);expect((screen.getByLabelText('修改研究主题') as HTMLTextAreaElement).value).toBe('主题草稿');expect(fetcher).not.toHaveBeenCalled()
})
it('keeps a project save interrupted by reload read-only until its saved value is checked',()=>{
 setApiSession('test','owner');const fetcher=vi.fn(()=>new Promise<Response>(()=>{}));vi.stubGlobal('fetch',fetcher)
 const first=render(<ProjectDetails project={project} onUpdated={vi.fn()}/>);fireEvent.change(screen.getByLabelText('修改项目名称'),{target:{value:'待核对名称'}});fireEvent.submit(screen.getByRole('button',{name:'保存修改：项目名称'}).closest('form')!);first.unmount()
 render(<ProjectDetails project={project} onUpdated={vi.fn()}/>);expect(screen.getByRole('button',{name:'重新读取项目'})).toBeTruthy();expect((screen.getByRole('button',{name:'保存修改：项目名称'}) as HTMLButtonElement).disabled).toBe(true);expect(fetcher).toHaveBeenCalledTimes(1)
})
