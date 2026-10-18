import {expect,test} from 'vitest'
import {isProjectUsage} from './modelUsageTypes'
import {usageFixture} from '../tasks/taskFixtures'
test.each(['figure_workbench','figure_explanation'])('usage preserves %s paid call accounting',task_type=>{expect(isProjectUsage({...usageFixture,items:[{...usageFixture.items[0],task_type}]},1)).toBe(true)})
