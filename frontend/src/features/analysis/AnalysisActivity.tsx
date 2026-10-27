import { useCallback, useContext, useLayoutEffect, useRef, type ReactNode } from 'react'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { AnalysisActivityContext } from './analysisActivityContext'

// A file has its own guard scope. Switching files retains the scope; replacing a
// dataset checks only that file, and replacing the project checks every scope.
export function AnalysisActivity({ children, registerLeaveGuard, onCanLeave }: { children: ReactNode; registerLeaveGuard?: RegisterLeaveGuard; onCanLeave?: (guard: () => boolean) => void }) {
  const parent = useContext(AnalysisActivityContext)
  const externalRegister = registerLeaveGuard ?? parent.register
  const guards = useRef(new Set<() => boolean>())
  const register = useCallback<RegisterLeaveGuard>((guard, isDirty) => {
    guards.current.add(guard)
    const unregister = externalRegister?.(guard, isDirty)
    return () => { guards.current.delete(guard); unregister?.() }
  }, [externalRegister])
  const canLeave = useCallback(() => [...guards.current].every(guard => guard()), [])
  useLayoutEffect(() => { onCanLeave?.(canLeave) }, [onCanLeave, canLeave])
  return <AnalysisActivityContext.Provider value={{ register, canLeave }}>{children}</AnalysisActivityContext.Provider>
}
