import { expect, it } from 'vitest'
import { summaryRoute } from './customerWorkspaceApi'

it.each([
  ['school', 'template_needed', 'upload', null, 'schoolView=upload'],
  ['school', 'template_needed', 'detail', 'v2', 'template=v2&schoolView=detail'],
  ['school', 'template_conflicts', 'detail', 'v1', 'template=v1&schoolView=detail'],
  ['details', 'template_conflicts', 'confirm', 'legacy', 'template=legacy&schoolView=detail'],
  ['details', 'template_needed', null, null, 'schoolView=list'],
])('opens the specified template panel for %s/%s/%s', (step, kind, view, template, params) => {
  const value = { project_id:'p', project_type:'thesis', step, kind, target:{view, template_version_id:template} }
  const result = summaryRoute(value, 'p')
  expect(result?.step).toBe('school')
  expect(result?.params.toString()).toBe(params)
})

it('keeps ordinary paper and research destinations unchanged', () => {
  for (const [project_type, step] of [['sci','manuscripts'], ['research','progress'], ['thesis','materials']]) {
    const value = {project_id:'p', project_type, step, target:{}}
    expect(summaryRoute(value,'p')).toEqual({step, params:new URLSearchParams()})
    expect(summaryRoute(value,'other')).toBeNull()
  }
})

it('rejects a school step for the wrong project type and a detail target without a template', () => {
  expect(summaryRoute({project_id:'p', project_type:'sci', step:'school', target:{}},'p')).toBeNull()
  expect(summaryRoute({project_id:'p', project_type:'thesis', step:'school', target:{view:'detail'}},'p')).toBeNull()
})
