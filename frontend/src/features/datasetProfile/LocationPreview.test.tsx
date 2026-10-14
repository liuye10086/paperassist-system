import { afterEach, expect, test, vi } from 'vitest'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import LocationPreview from './LocationPreview'
import { profile, issue, rowResponse } from './profileFixtures'
import { columnLetter } from '../datasetPreparation/preparationApi'

const originalScroll = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView')
afterEach(() => {
 cleanup(); vi.unstubAllGlobals()
 if (originalScroll) Object.defineProperty(Element.prototype, 'scrollIntoView', originalScroll)
 else Reflect.deleteProperty(Element.prototype, 'scrollIntoView')
})

function observeScroll() {
 const scroll = vi.fn(function (this: Element, options: ScrollIntoViewOptions) {
  expect(this.isConnected).toBe(true)
  return { target: this, options }
 })
 Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: scroll })
 return scroll
}

test('after loading a page-end row, scrolls its far-column cell into view on both axes', async () => {
 const scroll = observeScroll(); let finish!: (response: Response) => void
 vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
 const fields = Array.from({ length: 80 }, (_, index) => ({ ...profile.fields[0], column: index + 1, letter: columnLetter(index + 1) }))
 render(<LocationPreview base="/api/v1/projects/p1/files/f1" profile={{ ...profile, fields, data_range: 'A2:CB50' }} item={{ ...issue, row: 39, column: 80, coordinate: 'CB39' }} />)
 expect(screen.getByRole('status')).toBeTruthy(); expect(scroll).not.toHaveBeenCalled()
 const response = rowResponse(21)
 await act(async () => finish(Response.json({ ...response, dataset: { ...response.dataset, column_count: 80 } })))
 const table = await screen.findByRole('table')
 await waitFor(() => expect(scroll).toHaveBeenCalledTimes(1))
 const result = scroll.mock.results[0].value
 expect(result.target).toBe(table.querySelector('[data-coordinate="CB39"]'))
 expect(result.target.className).toContain('profile-cell-selected')
 expect(result.options).toMatchObject({ block: 'nearest', inline: 'nearest' })
})

test('duplicate row locations scroll the first displayed cell rather than the page start', async () => {
 const scroll = observeScroll(); vi.stubGlobal('fetch', vi.fn(async () => Response.json(rowResponse(41))))
 render(<LocationPreview base="/api/v1/projects/p1/files/f1" profile={profile} item={{ ...issue, row: 48, column: null, coordinate: null, group_first_row: 27, group_size: 2 }} />)
 const table = await screen.findByRole('table')
 await waitFor(() => expect(scroll).toHaveBeenCalledTimes(1))
 expect(scroll.mock.results[0].value.target).toBe(table.querySelector('[data-coordinate="C48"]'))
})

test('failed row loads do not scroll; retry scrolls only the validated target', async () => {
 const scroll = observeScroll(); const fetch = vi.fn()
 fetch.mockResolvedValueOnce(Response.json({ private: 'server error' }, { status: 500 }))
 fetch.mockResolvedValueOnce(Response.json(rowResponse(21)))
 vi.stubGlobal('fetch', fetch)
 render(<LocationPreview base="/api/v1/projects/p1/files/f1" profile={profile} item={issue} />)
 await screen.findByRole('alert'); expect(scroll).not.toHaveBeenCalled()
 await userEvent.setup().click(screen.getByRole('button', { name: '重试位置读取' }))
 const table = await screen.findByRole('table')
 await waitFor(() => expect(scroll).toHaveBeenCalledTimes(1))
 expect(scroll.mock.results[0].value.target).toBe(table.querySelector('[data-coordinate="C27"]'))
})
