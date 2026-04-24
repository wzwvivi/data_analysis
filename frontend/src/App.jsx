import React from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation, useParams } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import MainLayout from './components/MainLayout'
import LoginPage from './pages/LoginPage'
import UploadPage from './pages/UploadPage'
import TaskListPage from './pages/TaskListPage'
import ResultPage from './pages/ResultPage'
import FmsEventAnalysisPage from './pages/FmsEventAnalysisPage'
import StandaloneFmsEventPage from './pages/StandaloneFmsEventPage'
import StandaloneFmsEventTaskPage from './pages/StandaloneFmsEventTaskPage'
import FccEventAnalysisPage from './pages/FccEventAnalysisPage'
import FccEventAnalysisTaskPage from './pages/FccEventAnalysisTaskPage'
import AutoFlightAnalysisPage from './pages/AutoFlightAnalysisPage'
import AutoFlightAnalysisTaskPage from './pages/AutoFlightAnalysisTaskPage'
import ComparePage from './pages/ComparePage'
import AdminPlatformDataPage from './pages/AdminPlatformDataPage'
import AdminUserPage from './pages/AdminUserPage'
import ConfigurationManagerPage from './pages/ConfigurationManagerPage'
import NetworkConfigPage from './pages/NetworkConfigPage'
import DraftEditorPage from './pages/network-config/DraftEditorPage'
import ChangeRequestPage from './pages/network-config/ChangeRequestPage'
import VersionViewerPage from './pages/network-config/VersionViewerPage'
import DeviceProtocolPage from './pages/DeviceProtocolPage'
import DeviceDraftJsonEditorPage from './pages/device-protocol/DraftJsonEditorPage'
import DeviceChangeRequestPage from './pages/device-protocol/ChangeRequestPage'
import DeviceVersionViewerPage from './pages/device-protocol/VersionViewerPage'
import DashboardPage from './pages/DashboardPage'
import WorkbenchPage from './pages/WorkbenchPage'
import WorkbenchComparePage from './pages/WorkbenchComparePage'
import LandingPage from './pages/LandingPage'
import HelpCenterPage from './pages/HelpCenterPage'
import ModuleHubPage from './pages/ModuleHubPage'
import { Result } from 'antd'

function PrivateRoute({ children }) {
  const location = useLocation()
  const { user, ready } = useAuth()
  if (!ready) {
    return (
      <div style={{ padding: 100, textAlign: 'center', color: '#a1a1aa' }}>
        加载中…
      </div>
    )
  }
  if (!user) {
    const from = `${location.pathname}${location.search}${location.hash}`
    return <Navigate to="/login" replace state={{ from }} />
  }
  return children
}

function AdminRoute({ children }) {
  const location = useLocation()
  const { user, ready, isAdmin } = useAuth()
  if (!ready) {
    return (
      <div style={{ padding: 100, textAlign: 'center', color: '#a1a1aa' }}>
        加载中…
      </div>
    )
  }
  if (!user) {
    const from = `${location.pathname}${location.search}${location.hash}`
    return <Navigate to="/login" replace state={{ from }} />
  }
  if (!isAdmin) {
    return <Navigate to="/upload" replace />
  }
  return children
}

function PermissionDenied({ pageKey }) {
  return (
    <Result
      status="403"
      title="无权访问"
      subTitle={`当前账号没有访问该页面的权限（${pageKey}）`}
    />
  )
}

function PermissionRoute({ children, requiredPage }) {
  const location = useLocation()
  const { user, ready, hasPageAccess } = useAuth()
  if (!ready) {
    return (
      <div style={{ padding: 100, textAlign: 'center', color: '#a1a1aa' }}>
        加载中…
      </div>
    )
  }
  if (!user) {
    const from = `${location.pathname}${location.search}${location.hash}`
    return <Navigate to="/login" replace state={{ from }} />
  }
  if (requiredPage && !hasPageAccess(requiredPage)) {
    return <PermissionDenied pageKey={requiredPage} />
  }
  return children
}

const PUBLIC_DOC_KEYS = new Set(['overview', 'quickstart', 'faq', 'changelog'])

function PublicDocRoute() {
  const { moduleKey } = useParams()
  const currentKey = moduleKey || 'overview'

  if (!PUBLIC_DOC_KEYS.has(currentKey)) {
    return <Navigate to={`/help/${currentKey}`} replace />
  }

  return <HelpCenterPage />
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/docs" element={<PublicDocRoute />} />
      <Route path="/docs/:moduleKey" element={<PublicDocRoute />} />
      <Route
        path="/modules"
        element={(
          <PrivateRoute>
            <ModuleHubPage />
          </PrivateRoute>
        )}
      />
      <Route
        element={(
          <PrivateRoute>
            <MainLayout />
          </PrivateRoute>
        )}
      >
        <Route path="/dashboard" element={<PermissionRoute requiredPage="dashboard"><DashboardPage /></PermissionRoute>} />
        <Route path="/workbench" element={<PermissionRoute requiredPage="workbench"><WorkbenchPage /></PermissionRoute>} />
        <Route path="/workbench/compare" element={<PermissionRoute requiredPage="workbench"><WorkbenchComparePage /></PermissionRoute>} />
        <Route path="/workbench/:sortieId" element={<PermissionRoute requiredPage="workbench"><WorkbenchPage /></PermissionRoute>} />
        <Route path="/help" element={<HelpCenterPage />} />
        <Route path="/help/:moduleKey" element={<HelpCenterPage />} />
        <Route path="/upload" element={<PermissionRoute requiredPage="upload"><UploadPage /></PermissionRoute>} />
        <Route path="/tasks" element={<PermissionRoute requiredPage="tasks"><TaskListPage /></PermissionRoute>} />
        <Route path="/tasks/:taskId" element={<PermissionRoute requiredPage="tasks/:taskId"><ResultPage /></PermissionRoute>} />
        <Route path="/tasks/:taskId/analysis" element={<PermissionRoute requiredPage="tasks/:taskId/analysis"><ResultPage /></PermissionRoute>} />
        <Route path="/tasks/:taskId/event-analysis" element={<PermissionRoute requiredPage="tasks/:taskId/event-analysis"><FmsEventAnalysisPage /></PermissionRoute>} />
        <Route path="/tasks/:taskId/fms-event-analysis" element={<PermissionRoute requiredPage="tasks/:taskId/event-analysis"><FmsEventAnalysisPage /></PermissionRoute>} />
        <Route path="/network-config" element={<PermissionRoute requiredPage="network-config"><NetworkConfigPage /></PermissionRoute>} />
        <Route path="/network-config/versions/:id" element={<PermissionRoute requiredPage="network-config"><VersionViewerPage /></PermissionRoute>} />
        <Route path="/network-config/drafts/:id" element={<PermissionRoute requiredPage="network-config"><DraftEditorPage /></PermissionRoute>} />
        <Route path="/network-config/change-requests/:id" element={<PermissionRoute requiredPage="network-config"><ChangeRequestPage /></PermissionRoute>} />
        <Route path="/device-protocol" element={<PermissionRoute requiredPage="device-protocol"><DeviceProtocolPage /></PermissionRoute>} />
        <Route path="/device-protocol/drafts/:id" element={<PermissionRoute requiredPage="device-protocol"><DeviceDraftJsonEditorPage /></PermissionRoute>} />
        <Route path="/device-protocol/change-requests/:id" element={<PermissionRoute requiredPage="device-protocol"><DeviceChangeRequestPage /></PermissionRoute>} />
        <Route path="/device-protocol/versions/:id" element={<PermissionRoute requiredPage="device-protocol"><DeviceVersionViewerPage /></PermissionRoute>} />
        <Route path="/compare" element={<PermissionRoute requiredPage="compare"><ComparePage /></PermissionRoute>} />
        <Route path="/compare/:taskId" element={<PermissionRoute requiredPage="compare/:taskId"><ComparePage /></PermissionRoute>} />
        {/* 飞管事件分析（Phase 1 renamed，旧 /event-analysis 路径保留一段兼容期） */}
        <Route path="/fms-event-analysis/task/:analysisTaskId" element={<PermissionRoute requiredPage="fms-event-analysis/task/:analysisTaskId"><StandaloneFmsEventTaskPage /></PermissionRoute>} />
        <Route path="/fms-event-analysis" element={<PermissionRoute requiredPage="fms-event-analysis"><StandaloneFmsEventPage /></PermissionRoute>} />
        <Route path="/event-analysis/task/:analysisTaskId" element={<PermissionRoute requiredPage="fms-event-analysis/task/:analysisTaskId"><StandaloneFmsEventTaskPage /></PermissionRoute>} />
        <Route path="/event-analysis" element={<PermissionRoute requiredPage="fms-event-analysis"><StandaloneFmsEventPage /></PermissionRoute>} />
        <Route path="/fcc-event-analysis/task/:analysisTaskId" element={<PermissionRoute requiredPage="fcc-event-analysis/task/:analysisTaskId"><FccEventAnalysisTaskPage /></PermissionRoute>} />
        <Route path="/fcc-event-analysis" element={<PermissionRoute requiredPage="fcc-event-analysis"><FccEventAnalysisPage /></PermissionRoute>} />
        <Route path="/auto-flight-analysis/task/:taskId" element={<PermissionRoute requiredPage="auto-flight-analysis/task/:taskId"><AutoFlightAnalysisTaskPage /></PermissionRoute>} />
        <Route path="/auto-flight-analysis" element={<PermissionRoute requiredPage="auto-flight-analysis"><AutoFlightAnalysisPage /></PermissionRoute>} />
        <Route
          path="/admin/platform-data"
          element={(
            <AdminRoute>
              <AdminPlatformDataPage />
            </AdminRoute>
          )}
        />
        <Route
          path="/admin/configurations"
          element={(
            <AdminRoute>
              <ConfigurationManagerPage />
            </AdminRoute>
          )}
        />
        <Route
          path="/admin/users"
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
