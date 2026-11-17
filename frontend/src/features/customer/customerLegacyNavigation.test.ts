import { describe, expect, it } from 'vitest'
import { readLegacyCustomerRoute } from './customerLegacyNavigation'

describe('customer links from the previous workbench', () => {
  it.each([
    ['#project=paper&section=manuscripts&manuscript=m1&revision=2', 'manuscripts', { view: 'body', manuscript: 'm1', revision: '2' }],
    ['#project=paper&section=manuscripts&view=exports&manuscript=m1&revision=1', 'word', { view: 'exports', manuscript: 'm1', revision: '1' }],
    ['#project=paper&section=school-templates&view=confirm&template=t2', 'school', { view: 'confirm', template: 't2' }],
    ['#project=paper&section=journals&adaptation=a1', 'journals', { view: 'adaptation', adaptation: 'a1' }],
    ['#project=paper&section=journals&view=submission', 'reviews', { view: 'progress' }],
    ['#project=paper&section=reviews&round=r1&item=i1&reviewRun=v1&reviewDocument=d1', 'reviews',
      { view: 'documents', round: 'r1', item: 'i1', reviewRun: 'v1', reviewDocument: 'd1' }],
    ['#project=paper&section=reviews&view=plan&round=r1&item=f2a6939b-b706-4037-b294-68b106ebd602%3A1', 'reviews',
      { view: 'plan', round: 'r1', item: 'f2a6939b-b706-4037-b294-68b106ebd602:1' }],
    ['#project=paper&section=reviews&reviewManuscript=m1&reviewRevision=2', 'reviews',
      { view: 'create', reviewManuscript: 'm1', reviewRevision: '2' }],
    ['#project=paper&section=tasks&task=k1&view=events', 'tasks', { view: 'events', task: 'k1' }],
    ['#project=paper&section=overview&view=deliveries&delivery=e1&snapshot=s1', 'deliveries', { delivery: 'e1', snapshot: 's1' }],
    ['#project=paper&section=manuscripts&view=research-selection&writingDelivery=e1', 'deliveries', { delivery: 'e1' }],
  ])('preserves the fixed reference in %s', (hash, step, params) => {
    const route = readLegacyCustomerRoute(hash)
    expect(route).toMatchObject({ projectId: 'paper', step })
    expect(Object.fromEntries(route!.params)).toEqual(params)
  })

  it.each([
    '#project=paper&section=manuscripts&manuscript=m1',
    '#project=paper&section=manuscripts&manuscript=m1&revision=0',
    '#project=paper&section=reviews&round=r1&round=r2',
    '#project=paper&section=reviews&round=r1&reviewDocument=d1',
    '#project=paper&section=reviews&view=plan&round=r1&item=source%3A1',
    '#project=paper&section=reviews&view=plan&round=r1&item=f2a6939b-b706-4037-b294-68b106ebd602%3A0',
    '#project=paper&section=reviews&view=plan&round=f2a6939b-b706-4037-b294-68b106ebd602%3A1',
    '#project=paper&section=school-templates&view=rules',
    '#project=paper&section=tasks&task=legacy-plot%3A0123456789',
    '#project=../private&section=overview',
    '#project=paper&section=pdf-exports&export=pdf1',
  ])('ignores malformed, incompatible or retired addresses %s', hash => {
    expect(readLegacyCustomerRoute(hash)).toBeNull()
  })
})
