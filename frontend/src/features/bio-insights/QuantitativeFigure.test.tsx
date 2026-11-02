import {useState} from 'react'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {apiFetch} from '../../shared/api/client'
import FigureSetup from './FigureSetup'
import {defaultConfig} from './state'
import type {Config,Source} from './contracts'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
const sources:Source[]=[{source_kind:'bio_processed_dataset_version',source_id:'proc',role:'processed',sha256:'a'.repeat(64),locator:{kind:'object'}}]
it('freezes sample heatmap groups without averaging spots or applying an implicit log',async()=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json({items:[{sample_id:'sample1',condition:'A',retained:true},{sample_id:'sample2',condition:'A',retained:false}],total:2,observation_level:'sample'}))
 let current:Config={...defaultConfig('figure'),figure_type:'heatmap',processed_source_id:'proc',sample_groups:[],expression_groups:[]};function Harness(){const[c,set]=useState(current);current=c;return <FigureSetup projectId="p" config={c} onChange={set} sources={sources}/>}
 render(<Harness/>);fireEvent.click(screen.getByText('读取热图／分布图固定样本'));await screen.findByRole('option',{name:'A'})
 fireEvent.change(screen.getByLabelText('图件样本分组值'),{target:{value:'A'}});fireEvent.click(screen.getByText('加入图件样本组'))
 expect(current.sample_groups).toEqual([{label:'A',sample_keys:[{processed_version_id:'proc',sample_id:'sample1'}]}]);expect(screen.queryByText(/组均值 log1p 表达/)).toBeNull()
 fireEvent.click(screen.getByLabelText('显式按特征 z-score（仅改变热图显示）'));expect(current.z_score).toBe(true)
})
it('switches to an actual one-feature distribution and clears incompatible spatial groups and z-score',()=>{
 let current:Config={...defaultConfig('figure'),figure_type:'heatmap',expression_groups:[{label:'old',observation_keys:[]}],z_score:true};function Harness(){const[c,set]=useState(current);current=c;return <FigureSetup projectId="p" config={c} onChange={set} sources={sources}/>}
 render(<Harness/>);fireEvent.change(screen.getByLabelText('图型'),{target:{value:'distribution'}})
 expect(current).toMatchObject({figure_type:'distribution',sample_groups:[],expression_groups:[],z_score:false,analysis_layer:'analysis'})
 fireEvent.change(screen.getByLabelText('固定特征 ID（分布图须恰好一个，每行一个）'),{target:{value:'protein-unknown'}});expect(current.feature_ids).toEqual(['protein-unknown'])
 expect(screen.queryByLabelText('显式按特征 z-score（仅改变热图显示）')).toBeNull();expect(screen.getByText('箱线与全部实测点来自一个固定特征；保留缺失、各组实际 n 和原尺度。')).toBeTruthy()
})
