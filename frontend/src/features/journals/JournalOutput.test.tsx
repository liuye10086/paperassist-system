import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import JournalOutput from './JournalOutput'
import {manuscriptFixture,snapshotFixture} from '../manuscripts/manuscriptFixtures'
import {clearApiSession} from '../../shared/api/client'
const output={manuscript_id:'m1',version_id:'v3',revision:3,parent_version_id:'v1',task_id:'new-task'}
const version={...manuscriptFixture.versions[0],id:'v3',revision:3,parent_version_id:'v1',task_id:'new-task',exports:[],snapshot:{...snapshotFixture,journal_adaptation_provenance:{adaptation_id:'a1',base_version_id:'v1',input_sha256:'a'.repeat(64),display_version:'journal_display_v1'}}}
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals()})
it('waits on exact queued public output then reuses fixed-revision DOCX and successful-DOCX PDF exports',async()=>{
 let published=false;const calls:{url:string;body:unknown}[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
 calls.push({url,body:init?.body?JSON.parse(String(init.body)):null})
 if(url.endsWith('/versions/3'))return Response.json({...version,status:published?'published':'pending'})
 if(url.endsWith('/versions/3/exports'))return Response.json({items:[],pdf_status:'not_requested'})
 return Response.json({items:[]})
 }));const view=render(<JournalOutput projectId="p1" adaptationId="a1" output={output} active onUnavailable={vi.fn()}/>)
 await screen.findByText('公共新稿待发布；DOCX/PDF 尚未生成。');expect(screen.queryByRole('button',{name:'生成 DOCX'})).toBeNull()
 published=true;fireEvent.click(screen.getByRole('button',{name:'刷新固定新稿'}));await screen.findByRole('button',{name:'生成 DOCX'})
 expect(calls.some(c=>c.url.endsWith('/manuscripts/m1/versions/3/exports'))).toBe(true)
 expect(calls.every(c=>!c.url.endsWith('/versions/2/exports'))).toBe(true)
 view.rerender(<JournalOutput projectId="p1" adaptationId="a1" output={output} active={false} onUnavailable={vi.fn()}/>);const count=calls.length;await act(async()=>{});expect(calls).toHaveLength(count)
})
it('rejects a different version response and clears the exact output on session loss',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/versions/3')?{...version,id:'v4'}:{items:[]})))
 const view=render(<JournalOutput projectId="p1" adaptationId="a1" output={output} active onUnavailable={vi.fn()}/>)
 await screen.findByRole('alert');expect(screen.queryByRole('button',{name:'生成 DOCX'})).toBeNull()
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/versions/3')?version:{items:[],pdf_status:'not_requested'})))
 fireEvent.click(screen.getByRole('button',{name:'刷新固定新稿'}));await screen.findByRole('button',{name:'生成 DOCX'})
 act(()=>clearApiSession());await waitFor(()=>expect(screen.queryByRole('button',{name:'生成 DOCX'})).toBeNull());view.unmount()
})
