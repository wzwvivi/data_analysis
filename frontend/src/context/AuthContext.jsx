import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { authApi, configApi, TOKEN_KEY } from '../services/api'

const AuthContext = createContext(null)

const EMPTY_PUBLIC_CONFIG = { flight_assistant_url: '' }

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [permissions, setPermissions] = useState({ pages: [], visible_ports: {} })
  const [publicConfig, setPublicConfig] = useState(EMPTY_PUBLIC_CONFIG)
  const [ready, setReady] = useState(false)

  const loadPermissions = useCallback(async () => {
    try {
      const r = await authApi.permissions()
      setPermissions({
        pages: r.data?.pages || [],
        visible_ports: r.data?.visible_ports || {},
      })
      return r.data
    } catch {
      setPermissions({ pages: [], visible_ports: {} })
      return null
    }
  }, [])

  const loadPublicConfig = useCallback(async () => {
    try {
      const r = await configApi.getPublic()
      setPublicConfig({
        flight_assistant_url: (r.data?.flight_assistant_url || '').trim(),
      })
    } catch {
      setPublicConfig(EMPTY_PUBLIC_CONFIG)
    }
  }, [])

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
      await loadPermissions()
    } catch {
      setUser(null)
      setPermissions({ pages: [], visible_ports: {} })
      localStorage.removeItem(TOKEN_KEY)
    } finally {
      setReady(true)
    }
  }, [])

  useEffect(() => {
    refreshMe()
    loadPublicConfig()
  }, [refreshMe, loadPublicConfig])

  const login = async (username, password) => {
    const r = await authApi.login(username, password)
    localStorage.setItem(TOKEN_KEY, r.data.access_token)
    setUser(r.data.user)
    await loadPermissions()
    return r.data
  }

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY)
    setUser(null)
    setPermissions({ pages: [], visible_ports: {} })
  }

  const hasPageAccess = useCallback((pageKey) => {
    if (!user) return false
    if ((user?.role || '') === 'admin') return true
    const pages = permissions?.pages || []
    return pages.includes('*') || pages.includes(pageKey)
  }, [permissions?.pages, user])

  const hasPortAccess = useCallback((protocolVersionId, portNumber) => {
    if (!user) return false
    if ((user?.role || '') === 'admin') return true
    const key = String(protocolVersionId ?? '')
    const ports = permissions?.visible_ports?.[key] || []
    return ports.includes(Number(portNumber))
  }, [permissions?.visible_ports, user])

  const value = {
    user,
    permissions,
    publicConfig,
    ready,
    login,
    logout,
    refreshMe,
    refreshPermissions: loadPermissions,
    refreshPublicConfig: loadPublicConfig,
    hasPageAccess,
    hasPortAccess,
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
