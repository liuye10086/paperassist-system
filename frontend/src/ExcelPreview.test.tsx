import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const workbook = {
  filename: '研究.xlsx',
  sheets: [
    { name: '研究数据', columns: ['编号', '值'], row_count: 25, column_count: 2,
      preview_rows: Array.from({ length: 20 }, (_, i) => [`S${i}`, i]), warnings: [] },
    { name: '空表', columns: [], row_count: 0, column_count: 0, preview_rows: [], warnings: ['这是空表，没有可预览的数据。'] },
  ],
}

function mockApi(uploadResponse: () => Promise<Response> = async () => Response.json(workbook)) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith('/health')) return Response.json({ status: 'ok', service: 'paperassist-system' })
    if (url.endsWith('/config')) return Response.json({ max_upload_bytes: 1024, preview_row_limit: 20 })
    return uploadResponse()
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

test('uploads a real File using FormData, shows twenty rows and switches sheets', async () => {
  const fetchMock = mockApi()
  const user = userEvent.setup()
  render(<App />)
  expect(await screen.findByText('后端连接成功')).toBeTruthy()
  const input = await screen.findByLabelText('选择 Excel 文件')
  const file = new File(['sample'], '研究.xlsx')
  await user.upload(input, file)
  await user.click(screen.getByRole('button', { name: '上传并预览' }))
  const table = await screen.findByRole('table')
  expect(within(table).getAllByRole('row')).toHaveLength(21)
  expect(screen.getByText('25 行 × 2 列')).toBeTruthy()
  const uploadCall = fetchMock.mock.calls.find(([url]) => url.endsWith('/preview'))
  const options = (uploadCall as unknown as [string, RequestInit])[1]
  expect((options.body as FormData).get('file')).toBe(file)
  await user.selectOptions(screen.getByLabelText('工作表'), '1')
  expect(await screen.findByText('这是空表，没有可预览的数据。')).toBeTruthy()
  expect(screen.queryByRole('table')).toBeNull()
})

test('validates extension and size before sending', async () => {
  const fetchMock = mockApi()
  const user = userEvent.setup({ applyAccept: false })
  render(<App />)
  await screen.findByText('后端连接成功')
  const input = screen.getByLabelText('选择 Excel 文件')
  await user.upload(input, new File(['bad'], 'data.xls'))
  expect((await screen.findByRole('alert')).textContent).toContain('.xlsx')
  await user.upload(input, new File(['x'.repeat(1025)], 'large.xlsx'))
  expect((await screen.findByRole('alert')).textContent).toContain('超过')
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/preview'))).toBe(false)
})

test('shows server errors and allows retrying the same file', async () => {
  let attempts = 0
  mockApi(async () => ++attempts === 1
    ? Response.json({ detail: { code: 'parse_failed', message: '解析失败，请检查文件。' } }, { status: 422 })
    : Response.json(workbook))
  const user = userEvent.setup()
  render(<App />)
  await screen.findByText('后端连接成功')
  await user.upload(screen.getByLabelText('选择 Excel 文件'), new File(['x'], '研究.xlsx'))
  await user.click(screen.getByRole('button', { name: '上传并预览' }))
  expect((await screen.findByRole('alert')).textContent).toContain('解析失败')
  await user.click(screen.getByRole('button', { name: '上传并预览' }))
  expect(await screen.findByRole('table')).toBeTruthy()
  expect(screen.queryByRole('alert')).toBeNull()
})

test('clears stale preview when another file is selected and handles network failure', async () => {
  let attempts = 0
  mockApi(async () => { if (++attempts === 1) return Response.json(workbook); throw new TypeError('network') })
  const user = userEvent.setup()
  render(<App />)
  await screen.findByText('后端连接成功')
  await user.upload(screen.getByLabelText('选择 Excel 文件'), new File(['x'], '研究.xlsx'))
  await user.click(screen.getByRole('button', { name: '上传并预览' }))
  await screen.findByRole('table')
  await user.upload(screen.getByLabelText('选择 Excel 文件'), new File(['y'], '第二份.xlsx'))
  expect(screen.queryByRole('table')).toBeNull()
  await user.click(screen.getByRole('button', { name: '上传并预览' }))
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('无法连接'))
})

test('prevents duplicate submission while parsing', async () => {
  let finish: (response: Response) => void = () => {}
  const fetchMock = mockApi(() => new Promise(resolve => { finish = resolve }))
  const user = userEvent.setup()
  render(<App />)
  await screen.findByText('后端连接成功')
  const input = screen.getByLabelText('选择 Excel 文件') as HTMLInputElement
  await user.upload(input, new File(['x'], '研究.xlsx'))
  await user.click(screen.getByRole('button', { name: '上传并预览' }))
  const button = screen.getByRole('button', { name: '正在上传并解析……' }) as HTMLButtonElement
  expect(button.disabled).toBe(true)
  expect(input.disabled).toBe(true)
  await user.click(button)
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/preview'))).toHaveLength(1)
  finish(Response.json(workbook))
  await screen.findByRole('table')
})

test('configuration failure offers a working retry', async () => {
  let configAttempts = 0
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/health')) return Response.json({ status: 'ok', service: 'paperassist-system' })
    if (++configAttempts === 1) throw new TypeError('offline')
    return Response.json({ max_upload_bytes: 1024, preview_row_limit: 20 })
  }))
  const user = userEvent.setup()
  render(<App />)
  expect((await screen.findByRole('alert')).textContent).toContain('无法读取上传限制')
  expect((screen.getByLabelText('选择 Excel 文件') as HTMLInputElement).disabled).toBe(true)
  await user.click(screen.getByRole('button', { name: '重试读取配置' }))
  await waitFor(() => expect((screen.getByLabelText('选择 Excel 文件') as HTMLInputElement).disabled).toBe(false))
  expect(screen.queryByRole('alert')).toBeNull()
})

test('rejects an empty file without uploading', async () => {
  const fetchMock = mockApi()
  const user = userEvent.setup()
  render(<App />)
  await screen.findByText('后端连接成功')
  await user.upload(screen.getByLabelText('选择 Excel 文件'), new File([], 'empty.xlsx'))
  expect((await screen.findByRole('alert')).textContent).toContain('为空')
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/preview'))).toBe(false)
})

test('renders null, zero, false and header-only sheet without losing values', async () => {
  mockApi(async () => Response.json({ filename: 'types.xlsx', sheets: [
    { name: '类型', columns: ['空', '零', '否'], row_count: 1, column_count: 3, preview_rows: [[null, 0, false]], warnings: [] },
    { name: '仅表头', columns: ['字段'], row_count: 0, column_count: 1, preview_rows: [], warnings: ['此工作表只有表头，没有数据行。'] },
  ] }))
  const user = userEvent.setup()
  render(<App />)
  await screen.findByText('后端连接成功')
  await user.upload(screen.getByLabelText('选择 Excel 文件'), new File(['x'], 'types.xlsx'))
  await user.click(screen.getByRole('button', { name: '上传并预览' }))
  const table = await screen.findByRole('table')
  expect(within(table).getByRole('cell', { name: '—' })).toBeTruthy()
  expect(within(table).getByRole('cell', { name: '0' })).toBeTruthy()
  expect(within(table).getByRole('cell', { name: 'FALSE' })).toBeTruthy()
  await user.selectOptions(screen.getByLabelText('工作表'), '1')
  expect(screen.getByText('此工作表只有表头，没有数据行。')).toBeTruthy()
  expect(screen.getByRole('columnheader', { name: '字段' })).toBeTruthy()
})
