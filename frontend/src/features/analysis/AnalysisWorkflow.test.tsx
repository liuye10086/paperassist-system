import { useEffect, useState } from 'react'
import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WorkflowProvider, WorkflowStage, WorkflowNavigation } from './AnalysisWorkflow'

afterEach(cleanup)

test('stages stay mounted and retain drafts while navigation changes visibility', async () => {
  const mounted = vi.fn()
  const unmounted = vi.fn()
  function Draft() {
    const [text, setText] = useState('')
    useEffect(() => { mounted(); return unmounted }, [])
    return <input aria-label="draft" value={text} onChange={event => setText(event.target.value)} />
  }
  const user = userEvent.setup()
  render(<WorkflowProvider><WorkflowNavigation /><WorkflowStage stage="setup"><Draft /></WorkflowStage><WorkflowStage stage="statistics"><p>stats</p></WorkflowStage></WorkflowProvider>)
  const draft = screen.getByLabelText('draft') as HTMLInputElement
  await user.type(draft, '研究数据')
  await user.click(screen.getByRole('button', { name: '描述统计' }))
  expect(draft.closest('[hidden]')).toBeTruthy()
  expect(screen.getByText('stats').closest('[hidden]')).toBeNull()
  await user.click(screen.getByRole('button', { name: '字段配置' }))
  expect(screen.getByLabelText('draft')).toBe(draft)
  expect(draft.value).toBe('研究数据')
  expect(mounted).toHaveBeenCalledOnce()
  expect(unmounted).not.toHaveBeenCalled()
})

test('independent panels display children without a workflow provider', () => {
  render(<WorkflowStage stage="report"><p>independent report</p></WorkflowStage>)
  expect(screen.getByText('independent report').closest('[hidden]')).toBeNull()
})
