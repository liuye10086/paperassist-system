import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ResearchFindings from './ResearchFindings'
import {setApiSession,clearApiSession} from '../../shared/api/client'
afterEach(()=>{cleanup();vi.unstubAllGlobals();clearApiSession()})
it('returns to the exact older finding version and sends it to writing',async()=>{
 setApiSession('csrf','owner')
 const finding={id:'f-old',set_id:'set1',revision:1,content:{title:'Old finding',sources:[],facts:[],claims:[],conflicts:[],reviews:[],notes:'',methods:[],gaps:[],limitations:[],warnings:[]}}
 const fetch=vi.fn(async(url:string,_init?:RequestInit)=>{
  if(url.endsWith('/research-findings/set1/versions/f-old'))return Response.json(finding)
  if(url.endsWith('/research-findings'))return Response.json({items:[{id:'set1',title:'New finding',revision:2,current_version_id:'f-new'}]})
  return Response.json({items:[],total:0,page:1,page_size:25})
 });vi.stubGlobal('fetch',fetch)
 const onWriting=vi.fn();render(<ResearchFindings projectId="p1" active initialFindingSetId="set1" initialFindingVersionId="f-old" onWriting={onWriting}/>);await screen.findByDisplayValue('Old finding');await screen.findByText('当前类型还没有固定来源。');fireEvent.click(screen.getByRole('button',{name:'用于写作'}));expect(onWriting).toHaveBeenCalledWith({kind:'research_finding_version',id:'f-old',setId:'set1'});expect(fetch.mock.calls.every(([,init])=>!init?.method||init.method==='GET')).toBe(true)
})
it('keeps finding edits while switching between facts, claims and review modules',async()=>{
 setApiSession('csrf','owner')
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[]})))
 const {container}=render(<ResearchFindings projectId="tabs" active/>)
 fireEvent.change(screen.getByLabelText('发现集合标题'),{target:{value:'保留发现草稿'}})
 fireEvent.click(screen.getByRole('button',{name:'研究主张与冲突'}))
 fireEvent.click(screen.getByRole('button',{name:'添加研究主张'}))
 fireEvent.change(screen.getByLabelText('主张文字'),{target:{value:'保留人工主张'}})
 fireEvent.click(screen.getByRole('button',{name:'人工核对意见'}))
 fireEvent.change(screen.getByLabelText('核对依据与意见'),{target:{value:'尚未记录的核对意见'}})
 fireEvent.click(screen.getByRole('button',{name:'研究主张与冲突'}))
 expect(screen.getByLabelText('主张文字')).toHaveProperty('value','保留人工主张')
 fireEvent.click(screen.getByRole('button',{name:'人工核对意见'}))
 expect(screen.getByLabelText('核对依据与意见')).toHaveProperty('value','尚未记录的核对意见')
 expect(screen.getByRole('button',{name:'保存研究发现版本'})).toBeTruthy()
 expect(container.querySelector('details')).toBeNull()
})
