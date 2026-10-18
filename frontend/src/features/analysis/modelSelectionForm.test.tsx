import {render,screen} from '@testing-library/react'
import {it,expect} from 'vitest'
import AnalysisPlanLauncher from '../analysisPlan/AnalysisPlanLauncher'
import {reviewFixture} from '../analysisPlan/analysisPlanFixtures'
import type {PreparedDatasetAnalysisSource} from './datasetSource'
const preparedSource=reviewFixture.source as PreparedDatasetAnalysisSource
it('offers all four approved modeling methods',()=>{render(<AnalysisPlanLauncher projectId="p" fileId="f" source={preparedSource} selection={{task_type:'descriptive_boxplot',sheet_name:'Sheet1',numeric_column:'A',group_column:null,unit:'',missing_policy:'exclude_selected_missing'}} setupRevision={1} disabled onPublished={()=>{}}/>);expect(screen.getByRole('option',{name:'OLS 线性回归'})).toBeTruthy();expect(screen.getByRole('option',{name:'二元 Logistic 回归'})).toBeTruthy();expect(screen.getByRole('option',{name:'ROC / AUC'})).toBeTruthy();expect(screen.getByRole('option',{name:'Kaplan–Meier 生存分析'})).toBeTruthy()})
