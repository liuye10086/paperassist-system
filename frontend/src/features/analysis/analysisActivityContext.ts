import { createContext, useContext, useLayoutEffect } from 'react'
import { useI18n } from '../../shared/i18n'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'

export const AnalysisActivityContext = createContext<{ register?: RegisterLeaveGuard; canLeave: () => boolean }>({ canLeave: () => true })
export function useAnalysisRegisterLeaveGuard() { return useContext(AnalysisActivityContext).register }
export function useAnalysisCanLeave() { return useContext(AnalysisActivityContext).canLeave }
export function useAnalysisLeaveGuard(dirty: boolean | (() => boolean), pending: boolean | (() => boolean)) {
  const register = useAnalysisRegisterLeaveGuard()
  const { t } = useI18n()
  useLayoutEffect(() => {
    const isPending = () => typeof pending === 'function' ? pending() : pending
    const isDirty = () => typeof dirty === 'function' ? dirty() : dirty
    return register?.(() => {
      if (isPending()) { window.alert(t('当前保存请求尚未完成或结果待确认，请先核对保存结果。')); return false }
      return !isDirty() || window.confirm(t('当前项目有未保存的修改。离开并放弃这些修改？'))
    }, () => isDirty() || isPending())
  }, [register, dirty, pending, t])
}
