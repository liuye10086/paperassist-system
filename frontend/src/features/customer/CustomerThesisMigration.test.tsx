import { expect, it } from 'vitest'
import { customerManuscriptNavigation } from './customerPaperNavigation'

it('reads the migration target only on the template migration view', () => {
  const read = (query: string) => customerManuscriptNavigation(new URLSearchParams(query), false, true).target
  expect(read('manuscript=m1&revision=3&view=school&target=confirm2')).toBe('confirm2')
  expect(read('manuscript=m1&revision=3&view=body&target=confirm2')).toBeUndefined()
  expect(read('manuscript=m1&revision=3&view=school&target=not%20an%20id')).toBeUndefined()
  expect(read('view=school&target=confirm2')).toBeUndefined()
  expect(customerManuscriptNavigation(new URLSearchParams('manuscript=m1&revision=3&view=school&target=confirm2'), true, true).target).toBeUndefined()
})
