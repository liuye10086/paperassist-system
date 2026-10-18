import {test,expect} from 'vitest'
import {render,screen} from '@testing-library/react'
import ComparisonResults from './ComparisonResults'
import {comparisonResult} from './comparisonFixtures'
import type {ComparisonResult} from './comparisonResult'
test('comparison exposes check and group summary warning reasons',()=>{const r={...comparisonResult,check:{...comparisonResult.check,warnings:['所选字段缺失，已排除。']},groups:comparisonResult.groups.map(g=>({...g,statistics:{...g.statistics,std:null,warnings:['有效样本不足2条，标准差无法计算。']}}))};render(<ComparisonResults result={r as unknown as ComparisonResult}/>);expect(screen.getAllByText(/标准差无法计算/).length).toBeGreaterThan(0);expect(screen.getByText(/所选字段缺失/)).toBeTruthy()})
