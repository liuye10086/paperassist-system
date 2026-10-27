import {expect,it} from 'vitest'
import {parseNavigation,serializeNavigation} from './projectNavigation'
it.each([
 ['#project=p1&section=reviews','list'],
 ['#project=p1&section=reviews&round=r1','items'],
 ['#project=p1&section=reviews&round=r1&reviewRun=run1','revision'],
 ['#project=p1&section=reviews&round=r1&reviewRun=run1&reviewDocument=d1','documents'],
 ['#project=p1&section=reviews&reviewManuscript=m1&reviewRevision=2','create'],
])('restores old review destination %s', (hash,view)=>expect(parseNavigation(hash)?.reviewView).toBe(view))
it.each([
 '#project=p1&section=reviews&view=plan&item=i1&round=r1',
 '#project=p1&section=reviews&view=response&round=r1&reviewRun=run1&reviewDocument=d1',
 '#project=p1&section=reviews&view=progress',
 '#project=p1&section=tasks&view=actions&task=t1',
 '#project=p1&section=tasks&view=events&task=legacy-plot%3Ab2xk',
])('round trips a task view: %s', hash=>{const route=parseNavigation(hash);expect(route).not.toBeNull();expect(serializeNavigation(route!)).toBe(hash)})
it.each(['reviews&view=no','reviews&view=plan','reviews&view=create&round=r1','reviews&item=i1','reviews&round=r1&item=../x','tasks&view=actions','tasks&task=t1&view=no','reviews&view=plan&view=items&round=r1'])('rejects malformed layered destination %s',suffix=>expect(parseNavigation('#project=p1&section='+suffix)).toBeNull())
