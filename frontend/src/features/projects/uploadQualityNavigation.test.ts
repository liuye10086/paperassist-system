import { expect, test } from 'vitest'
import { homeRoute, parseNavigation, serializeNavigation } from './projectNavigation'

test.each([
  '#project=p1&section=files&view=quality',
  '#project=p1&section=files&view=quality&file=f1',
  '#project=p1&section=files&view=quality&quality=bio-datasets',
  '#project=p1&section=files&view=quality&quality=bio-import&import=i1',
  '#project=p1&section=files&view=quality&quality=bio-dataset&dataset=d1&version=v1',
  '#project=p1&section=files&view=quality&quality=bio-analysis-setup&setup=s1',
  '#project=p1&section=files&view=quality&quality=bio-analysis&run=r1',
  '#project=p1&section=files&view=quality&quality=bio-result&processed=pv1&tab=qc',
])('restores upload quality destinations independently from requirements: %s', hash => {
  const parsed = parseNavigation(hash)
  expect(parsed).not.toBeNull()
  expect(parsed?.section).toBe('files')
  expect(parsed?.resourceNavigation.view).toBe('quality')
  expect(parsed?.analysisNavigation).toEqual(homeRoute().analysisNavigation)
  expect(serializeNavigation(parsed!)).toBe(hash)
})

test.each([
  '#project=p1&section=files&view=upload&quality=bio-datasets',
  '#project=p1&section=files&view=quality&quality=overview',
  '#project=p1&section=files&view=quality&quality=bio-import',
  '#project=p1&section=files&view=quality&quality=bio-dataset&dataset=d1',
  '#project=p1&section=files&view=quality&file=f1&quality=bio-datasets',
  '#project=p1&section=files&view=quality&quality=bio-result&processed=pv1&tab=invalid',
  '#project=p1&section=files&view=quality&quality=bio-datasets&requirement=req1&scope=qc',
  '#project=p1&section=files&view=quality&dataset=d1',
])('rejects incomplete or mixed quality destinations: %s', hash => {
  expect(parseNavigation(hash)).toBeNull()
})
