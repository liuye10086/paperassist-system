import { createContext } from 'react'
/** Identity confirmed by AuthBoundary's session restoration or login response. */
export type AuthIdentity = { id: string; email: string; role: string }
export const AuthIdentityContext = createContext<AuthIdentity | null>(null)
