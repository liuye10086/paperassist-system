import { createContext, useContext } from 'react'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
export const LiteratureActivityContext = createContext<{ active: boolean; register?: RegisterLeaveGuard }>({ active: true })
export function useLiteratureActive() { return useContext(LiteratureActivityContext).active }
export function useLiteratureRegister() { return useContext(LiteratureActivityContext).register }
export function useLiteratureLeaveGuard(dirty: boolean, pending: boolean) {
 useDraftLeaveGuard(useLiteratureRegister(), dirty, pending)
}
