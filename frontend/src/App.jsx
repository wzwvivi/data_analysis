import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import MainLayout from './components/MainLayout'
import LoginPage from './pages/LoginPage'
import UploadPage from './pages/UploadPage'
import TaskListPage from './pages/TaskListPage'
import ResultPage from './pages/ResultPage'
import EventAnalysisPage from './pages/EventAnalysisPage'
import StandaloneEventPage from './pages/StandaloneEventPage'
import StandaloneEventTaskPage from './pages/StandaloneEventTaskPage'
import ProtocolPage from './pages/ProtocolPage'
import ComparePage from './pages/ComparePage'
import AdminPlatformDataPage from './pages/AdminPlatformDataPage'
import AdminUserPage from './pages/AdminUserPage'

function PrivateRoute({ children }) {
  const { user, ready } = useAuth()
  if (!ready) {
    return (
      <div style={{ padding: 100, textAlign: 'center', color: '#8b949e' }}>
        加载中…
      </div>
    )
  }
  if (!user) {
    return <Navigate to="/login" replace />
  }
  return children
}

function AdminRoute({ children }) {
  const { user, ready, isAdmin } = useAuth()
  if (!ready) {
    return (
      <div style={{ padding: 100, textAlign: 'center', color: '#8b949e' }}>
        加载中…
      </div>
    )
  }
  if (!user) {
    return <Navigate to="/login" replace />
  }
  if (!isAdmin) {
    return <Navigate to="/upload" replace />
  }
  return children
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={(
          <PrivateRoute>
            <MainLayout />
          </PrivateRoute>
        )}
      >
        <Route index element={<Navigate to="/upload" replace />} />
        <Route path="upload" element={<UploadPage />} />
        <Route path="tasks" element={<TaskListPage />} />
        <Route path="tasks/:taskId" element={<ResultPage />} />
        <Route path="tasks/:taskId/analysis" element={<ResultPage />} />
        <Route path="tasks/:taskId/event-analysis" element={<EventAnalysisPage />} />
        <Route
          path="network-config"
          element={(
            <AdminRoute>
              <ProtocolPage />
            </AdminRoute>
          )}
        />
        <Route path="compare" element={<ComparePage />} />
        <Route path="compare/:taskId" element={<ComparePage />} />
        <Route path="event-analysis/task/:analysisTaskId" element={<StandaloneEventTaskPage />} />
        <Route path="event-analysis" element={<StandaloneEventPage />} />
        <Route
          path="admin/platform-data"
          element={(
            <AdminRoute>
              <AdminPlatformDataPage />
            </AdminRoute>
          )}
        />
        <Route
          path="admin/users"
          element={(
            <AdminRoute>
              <AdminUserPage />
            </AdminRoute>
          )}
        />
      </Route>
    </Routes>
  )
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
