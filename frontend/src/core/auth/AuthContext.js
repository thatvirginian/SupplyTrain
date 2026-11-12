// =============================================================================
// core/auth/AuthContext.js
// =============================================================================
// The logged-in user and their role flags (isAdmin, isGM, isStoreUser, ...).
// <AuthContext.Provider> is rendered in App.jsx; pages read it with useAuth().
// =============================================================================
import { createContext, useContext } from 'react'

export const AuthContext = createContext(null)
export const useAuth = () => useContext(AuthContext)
