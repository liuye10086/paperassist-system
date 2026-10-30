import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import {setLocale} from '../../shared/i18n'
import {GuideView} from './JournalFormatPanel'
import type {Guide} from './formatContracts'

afterEach(()=>{cleanup();setLocale('zh-CN')})
const original:Guide={id:'guide-web',project_id:'p1',profile_id:'profile1',name:'Recorded guide',source_type:'official_local',source_text:'Maximum body words: 2500',source_url:'https://source.test/authors',official_url:'https://source.test',source_version:'web-sha256:'+'a'.repeat(64),acquired_on:'2026-10-28',verified_on:'2026-10-23',article_types:['research'],conditions:'Recorded source conditions',permission:'Recorded permission',permission_status:'allowed',source_status:'available',requirements:[],extract:true,requirements_version:'b'.repeat(64),extracted_requirements:[],synthetic:false,verification_level:'user_material_only',created_at:'2026-10-28T03:00:00Z'}
const retrieval={requested_url:'https://source.test/guide',final_url:'https://source.test/authors',fetched_at:'2026-10-28T03:00:00Z',body_sha256:'a'.repeat(64),bytes:1234,content_type:'text/plain',etag:'fixture-etag',last_modified:'Tue, 27 Oct 2026 10:00:00 GMT',official_verification:'not_established' as const}

it.each([
 {locale:'zh-CN' as const,status:'已获取，官方身份未核实',source:'实际获取来源：',time:'获取时间：',checksum:'来源正文 SHA-256：',recordOnly:'URL 仅登记：'},
 {locale:'en' as const,status:'Fetched; official identity unverified',source:'Fetched source:',time:'Fetched at:',checksum:'Source body SHA-256:',recordOnly:'Recorded URLs only:'},
])('shows fetched provenance without claiming official verification in $locale',({locale,status,source,time,checksum,recordOnly})=>{
 setLocale(locale)
 const value={...original,verification_level:'web_fetch_unverified',retrieval};const before=JSON.stringify(value)
 render(<GuideView guide={value} expanded/>)
 expect(screen.getByText((_,node)=>node?.tagName==='P'&&!!node.textContent?.includes(status))).toBeTruthy()
 expect(screen.getByText((_,node)=>node?.tagName==='P'&&!!node.textContent?.includes(source+retrieval.final_url))).toBeTruthy()
 expect(screen.getByText((_,node)=>node?.tagName==='P'&&!!node.textContent?.includes(retrieval.requested_url))).toBeTruthy()
 expect(screen.getByText((_,node)=>node?.tagName==='P'&&!!node.textContent?.includes(time))).toBeTruthy()
 expect(screen.getByText(retrieval.fetched_at).getAttribute('dateTime')).toBe(retrieval.fetched_at)
 expect(screen.getByText((_,node)=>node?.tagName==='P'&&!!node.textContent?.includes(checksum+retrieval.body_sha256))).toBeTruthy()
 expect(screen.getByText(/1234/)).toBeTruthy()
 expect(screen.getByText(/fixture-etag/)).toBeTruthy()
 expect(screen.getByText(/Tue, 27 Oct 2026/)).toBeTruthy()
 expect(screen.queryByText(new RegExp(recordOnly))).toBeNull()
 expect(JSON.stringify(value)).toBe(before)
})

it.each([false,true])('retains the local recorded-URL path for synthetic=%s',synthetic=>{
 const value={...original,synthetic,source_type:synthetic?'synthetic' as const:'user_provided' as const,verification_level:synthetic?'synthetic_material_only':'user_material_only'}
 render(<GuideView guide={value} expanded/>)
 expect(screen.getByText(/URL 仅登记：/).textContent).toContain(original.source_url)
 expect(screen.queryByText(/实际获取来源：/)).toBeNull()
 expect(screen.getByText((_,node)=>node?.tagName==='P'&&!!node.textContent?.includes(synthetic?'仅合成材料':'仅用户提供'))).toBeTruthy()
})
