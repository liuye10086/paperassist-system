import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import InsightImpact from './InsightImpact'
import {apiFetch} from '../../shared/api/client'
import {setLocale,translate} from '../../shared/i18n'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();setLocale('zh-CN');vi.mocked(apiFetch).mockClear()})
it('queries scoped resource impact only on request and displays the immutable notice',async()=>{vi.mocked(apiFetch).mockResolvedValue(Response.json({affected:[{source_kind:'bio_insight_plan_version',source_id:'plan'}],newer_version_id:'v2',affected_truncated:false}));render(<InsightImpact projectId="p1" id="r1" resource/>);expect(apiFetch).not.toHaveBeenCalled();fireEvent.click(screen.getByText('检查下游影响与新版提示'));await screen.findByText(/存在资源新版/);await waitFor(()=>expect(apiFetch).toHaveBeenCalledTimes(1));expect(String(vi.mocked(apiFetch).mock.calls[0][0])).toBe('/api/v1/projects/p1/bio-resources/r1/impact');expect(screen.getByText(/不自动重算或替换/)).toBeTruthy()})
it('translates actual heatmap mean expression without asserting z-score',()=>{setLocale('en');expect(translate('组均值 log1p 表达，未经按基因标准化；非差异效应')).toBe('Group mean log1p expression, without per-gene standardization; not differential effects')})
