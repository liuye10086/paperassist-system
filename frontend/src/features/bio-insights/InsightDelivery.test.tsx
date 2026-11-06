import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import InsightDelivery from './InsightDelivery'
import type {Result} from './contracts'
import {apiFetch} from '../../shared/api/client'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner',captureApiSession:()=>()=>{},onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
const result={id:'topic',kind:'integration',summary:{topic_method:'cellchat'},methods:{},manifest:{},manifest_sha256:'a'.repeat(64),task:{id:'task',status:'succeeded'},members:[]} as unknown as Result
it('selects a separately rendered figure for Word without changing the fixed result',async()=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json({items:[{id:'plot',title:'可读通讯图',figure_type:'topic_cellchat',manifest_sha256:'b'.repeat(64)}]}))
 render(<InsightDelivery projectId="p1" result={result}/> )
 fireEvent.click(await screen.findByLabelText('可读通讯图'))
 expect(screen.getByRole('link',{name:'下载 Word 分析报告'}).getAttribute('href')).toBe('/api/v1/projects/p1/bio-insight-results/topic/report.docx?figure_version_ids=plot')
 expect(screen.getByRole('link',{name:'下载离线复现包'}).getAttribute('href')).toBe('/api/v1/projects/p1/bio-insight-results/topic/reproducibility-package')
 expect(screen.getByRole('link',{name:'可读通讯图：下载重绘复现包'}).getAttribute('href')).toBe('/api/v1/projects/p1/bio-insight-results/plot/reproducibility-package')
 expect(result.members).toEqual([])
})
it('keeps the original Word and full members available when no replacement figures exist',async()=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json({items:[]}))
 render(<InsightDelivery projectId="p1" result={result}/> )
 expect(screen.getByRole('link',{name:'下载 Word 分析报告'}).getAttribute('href')).toBe('/api/v1/projects/p1/bio-insight-results/topic/report.docx')
 expect(screen.queryByText(/PDF/)).toBeNull()
})
it('allows at most ten selected figures and lets the user change the selection',async()=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json({items:Array.from({length:11},(_,i)=>({id:'plot'+i,title:'图'+i,figure_type:'topic_cellchat',manifest_sha256:'b'.repeat(64)}))}))
 render(<InsightDelivery projectId="p1" result={result}/> )
 await screen.findByLabelText('图0')
 for(let i=0;i<10;i++)fireEvent.click(screen.getByLabelText('图'+i))
 expect(screen.getByLabelText('图10')).toHaveProperty('disabled',true)
 fireEvent.click(screen.getByLabelText('图0'))
 expect(screen.getByLabelText('图10')).toHaveProperty('disabled',false)
 fireEvent.click(screen.getByLabelText('图10'))
 expect(new URL('http://local'+screen.getByRole('link',{name:'下载 Word 分析报告'}).getAttribute('href')).searchParams.getAll('figure_version_ids')).toHaveLength(10)
})
