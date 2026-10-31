import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import {useEffect,useState} from 'react'
import CandidateRecipe from './CandidateRecipe'
import {defaultConfig} from './state'
import type {CandidateStep} from './contracts'
afterEach(cleanup)
it('preserves ordered steps when adding, moving and changing explicit exclusions',()=>{let c=defaultConfig('candidate');function Harness(){const[v,set]=useState(c);useEffect(()=>{c=v},[v]);return <CandidateRecipe config={v} onChange={set} sources={[]}/>};render(<Harness/>);fireEvent.click(screen.getByRole('button',{name:'添加筛选步骤'}));fireEvent.change(screen.getByLabelText('步骤 2 操作'),{target:{value:'exclude'}});fireEvent.change(screen.getByLabelText('步骤 2 特征 ID'),{target:{value:'GENE_0\nGENE_NA'}});fireEvent.click(screen.getByRole('button',{name:'上移步骤 2'}));expect((c.steps as CandidateStep[])[0]).toMatchObject({operation:'exclude',feature_ids:['GENE_0','GENE_NA']});expect(screen.getByText(/支持来源数不等于独立实验数/)).toBeTruthy()})
