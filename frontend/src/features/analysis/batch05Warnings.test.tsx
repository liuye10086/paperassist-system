import {afterEach, expect, test} from 'vitest'
import {cleanup, render, screen} from '@testing-library/react'
import {setLocale} from '../../shared/i18n'
import CorrelationResults from './CorrelationResults'
import ModelResults from './ModelResults'
import {correlationResult} from './correlationFixtures'
import {modelingRocFixture} from './modelFixtures'
import type {ModelResult} from './modelResult'
import type {CorrelationResult} from './correlationResult'
afterEach(()=>{cleanup();setLocale('zh-CN')})
test('correlation retains checked missing-record and unit warnings in English',()=>{
 setLocale('en')
 render(<CorrelationResults result={{...correlationResult,check:{...correlationResult.check,warnings:['缺失行按共同完整记录规则排除，原数据保留。','请确认单位仅为声明，不转换数值。']}} as CorrelationResult}/>)
 expect(screen.getByText('Rows with missing values are excluded using common complete records; original data are retained.')).toBeTruthy()
 expect(screen.getByText('Confirm that units are declarations only; values are not converted.')).toBeTruthy()
})
test('model check warnings retain specific exclusion and unit semantics',()=>{
 setLocale('en')
 render(<ModelResults result={{...modelingRocFixture,check:{...modelingRocFixture.check,warnings:['完整记录缺失排除保留来源审计。','非参与组排除；不会作为缺失记录。','声明单位仅为标签，不转换数值。']}} as unknown as ModelResult}/>)
 expect(screen.getByText('Excluded incomplete records retain source-row audit.')).toBeTruthy()
 expect(screen.getByText('Nonparticipating groups are excluded separately from missing records.')).toBeTruthy()
 expect(screen.getByText('Declared units are labels only; numeric values are not converted.')).toBeTruthy()
})
