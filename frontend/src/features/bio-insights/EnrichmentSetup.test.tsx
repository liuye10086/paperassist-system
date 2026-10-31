import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import {useEffect,useState} from 'react'
import EnrichmentSetup from './EnrichmentSetup'
import {defaultConfig} from './state'
afterEach(cleanup)
it('uses explicit correction family and preserves zero thresholds',()=>{let c=defaultConfig('ora');function Harness(){const[v,set]=useState(c);useEffect(()=>{c=v},[v]);return <EnrichmentSetup config={v} onChange={set} sources={[]}/>};render(<Harness/>);fireEvent.change(screen.getByLabelText('q 值口径'),{target:{value:'original_q'}});fireEvent.change(screen.getByLabelText('q 阈值'),{target:{value:'0'}});expect(c.q_column).toBe('original_q');expect(c.q_threshold).toBe(0);expect(screen.getByText(/KEGG.*资源未配置/)).toBeTruthy()})
