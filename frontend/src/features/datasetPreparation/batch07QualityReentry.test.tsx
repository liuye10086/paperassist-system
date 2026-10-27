import {cleanup,render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {afterEach,expect,test,vi} from 'vitest'
import PreparedHistory from './PreparedHistory'
import DatasetProfile from '../datasetProfile/DatasetProfile'
import {baseVersion,qualityCounts,qualityRecipe,qualityReview,qualityTask,qualityVersion} from './batch07Fixtures'
import {profile} from '../datasetProfile/profileFixtures'

afterEach(()=>{cleanup();vi.unstubAllGlobals()})
test.each(['history','profile'])('%s allows a fresh quality draft from the same parent after publication',async entry=>{
 const fetch=vi.fn(async(url:string)=>{
  if(url.endsWith('/profile'))return Response.json({...profile,source:baseVersion.source})
  if(url.includes('prepared-dataset-versions?'))return Response.json({items:[baseVersion],total:1,page:1,page_size:5})
  if(url.endsWith('/prepared-dataset-versions/pd1'))return Response.json(baseVersion)
  if(url.endsWith('/quality-defaults'))return Response.json({source:baseVersion.source,recipe:qualityRecipe,summary:qualityCounts,sheet:qualityVersion.sheet})
  if(url.includes('/rows?'))return Response.json({dataset:baseVersion,start_row:2,limit:20,has_more:false,rows:[{row:2,cells:[]}]})
  if(url.endsWith('/dataset-quality-preparations'))return Response.json(qualityTask)
  if(url.endsWith('/dataset-preparation'))return Response.json({...qualityReview,task:{...qualityTask,status:'succeeded'},wait:null,result:qualityVersion})
  if(url.includes('/impacts?'))return Response.json({items:[],total:0,page:1,page_size:20})
  throw new Error(url)
 });vi.stubGlobal('fetch',fetch)
 if(entry==='history')render(<PreparedHistory projectId="p1" fileId="f1"/>)
 else render(<DatasetProfile projectId="p1" base="/api/v1/projects/p1/files/f1" binding={{...baseVersion.source,source:baseVersion.source}}/>)
 const user=userEvent.setup()
 await user.click(await screen.findByRole('button',{name:'按此版本处理质量问题'}))
 await user.click(await screen.findByRole('button',{name:'生成质量预览'}))
 await screen.findByText('已发布：原始数据 v1 · 整理数据 v2')
 await user.click(screen.getByRole('button',{name:entry==='history'?'按原规则新建整理任务':'按此版本处理质量问题'}))
 await waitFor(()=>expect(screen.getByRole('button',{name:'生成质量预览'})).toBeTruthy())
 expect(screen.queryByText('已发布：原始数据 v1 · 整理数据 v2')).toBeNull()
 expect(fetch.mock.calls.filter(([url])=>url.endsWith('/dataset-quality-preparations'))).toHaveLength(1)
})
