import { expect, it, vi } from 'vitest'
import { captureProjectAccess, watchProjectAccess } from './projectAccess'

it('permanently invalidates the captured instance before notifying', () => {
  let captured!: ReturnType<typeof captureProjectAccess>
  const notify = vi.fn(() => expect(() => captured.check()).toThrow())
  const stop = watchProjectAccess('p1', notify)
  captured = captureProjectAccess('/api/v1/projects/p1/files?download=true')
  captured.check(); captured.unavailable(); captured.unavailable()
  expect(notify).toHaveBeenCalledTimes(1)
  const stopNew = watchProjectAccess('p1', vi.fn())
  expect(() => captured.check()).toThrow()
  captureProjectAccess('/api/v1/projects/p1').check()
  stop(); captureProjectAccess('/api/v1/projects/p1').check(); stopNew()
})
it('keeps unregistered and lookalike paths as no-ops', () => {
  const notify = vi.fn(); const stop = watchProjectAccess('p1', notify)
  for (const path of ['/api/v1/projects', '/api/v1/projects/p10', '/other/api/v1/projects/p1', 'https://evil.test/api/v1/projects/p1']) {
    const captured = captureProjectAccess(path); captured.check(); captured.unavailable()
  }
  expect(notify).not.toHaveBeenCalled(); stop()
})
