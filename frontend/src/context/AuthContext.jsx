import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { authApi, TOKEN_KEY } from '../services/api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(false)

  const refreshMe = useCallback(async () => {
    const t = localStorage.getItem(TOKEN_KEY)
    if (!t) {
      setUser(null)
      setReady(true)
      return
    }
    try {
      const r = await authApi.me()
      setUser(r.data)
    } catch {
      setUser(null)
      localStorage.removeItem(TOKEN_KEY)
    } finally {
      setReady(true)
    }
  }, [])

  useEffect(() => {
    refreshMe()
  }, [refreshMe])

  const login = async (username, password) => {
    const r = await authApi.login(username, password)
    localStorage.setItem(TOKEN_KEY, r.data.access_token)
    setUser(r.data.user)
    return r.data
  }

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY)
    setUser(null)
  }

  const value = {
    user,
    ready,
    login,
    logout,
    refreshMe,
    isAdmin: (user?.role || '') === 'admin',
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return ctx
}
