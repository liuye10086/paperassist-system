import {afterEach,expect,it} from 'vitest'
import {setLocale} from './index'
import {protocolLabel,authorizationStates,callStates,writingModes,sourceKinds,inventoryKinds,inventoryScopes,exceptionKinds,sheetStates,severities,quotaScopes,unexecutedStates,guideSourceTypes,guideSourceStates,permissionStates,requirementStates,requirementOrigins,verificationLevels,taskStatusLabel} from './protocolLabels'
afterEach(()=>setLocale('zh-CN'))
it('covers every supported display enum in both languages without leaking unknown protocol values',()=>{
 const maps=[authorizationStates,callStates,writingModes,sourceKinds,inventoryKinds,inventoryScopes,exceptionKinds,sheetStates,severities,quotaScopes,unexecutedStates,guideSourceTypes,guideSourceStates,permissionStates,requirementStates,requirementOrigins,verificationLevels]
 for(const labels of maps){
  for(const [value,source] of Object.entries(labels)){
   setLocale('zh-CN');expect(protocolLabel(labels,value)).toBe(source)
   setLocale('en');expect(protocolLabel(labels,value)).not.toMatch(/[\u3400-\u9fff]/)
  }
  expect(protocolLabel(labels,'PRIVATE_UNEXPECTED_PROTOCOL')).toBe('Unknown status')
  expect(protocolLabel(labels,null,'未知类型')).toBe('Unknown type')
 }
 expect(taskStatusLabel('running')).toBe('Running')
 expect(taskStatusLabel('PRIVATE_UNKNOWN_STATE')).toBe('Unknown status')
})
