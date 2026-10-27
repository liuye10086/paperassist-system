import { useContext, type ReactNode } from 'react'
import type { RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { LiteratureActivityContext } from './literatureActivityContext'
export function LiteratureActivity({ active, register, children }: { active: boolean; register?: RegisterLeaveGuard; children: ReactNode }) {
 const parent = useContext(LiteratureActivityContext)
 return <LiteratureActivityContext.Provider value={{ active: parent.active && active, register: register ?? parent.register }}>{children}</LiteratureActivityContext.Provider>
}
