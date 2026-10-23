import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import ReviewTaskOutcome from './ReviewTaskOutcome'
import {taskFixture} from '../tasks/taskFixtures'
afterEach(cleanup)
it('returns an independent document task to its own immutable document and revision',()=>{render(<ReviewTaskOutcome task={{...taskFixture,task_type:'review_document_export',input_version:{kind:'review_document_export',document_id:'d1',revision_id:'run1',round_id:'r1',export_id:'e1',document_sha256:'a'.repeat(64),workflow_version:'review_document_export_v1'}} as never}/>);expect(screen.getByRole('link',{name:'查看此份固定成果'}).getAttribute('href')).toBe('#project=p1&section=reviews&round=r1&reviewRun=run1&reviewDocument=d1')})
it('does not describe a successful revision coordinator as a completed public manuscript',()=>{render(<ReviewTaskOutcome task={{...taskFixture,task_type:'review_revision',status:'succeeded',input_version:{kind:'review_revision',revision_id:'run1',round_id:'r1',base_version_id:'v1',workflow_version:'review_revision_v1'}} as never}/>);expect(screen.getByText('请在固定修改批次核对公共新稿任务、实际变化与待补事项。')).toBeTruthy();expect(screen.queryByText('公共新稿已完成')).toBeNull()})
