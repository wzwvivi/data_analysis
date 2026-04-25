import React from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation, useParams } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import MainLayout from './components/MainLayout'
import LoginPage from './pages/LoginPage'
import UploadPage from './pages/UploadPage'
import TaskListPage from './pages/TaskListPage'
import ResultPage from './pages/ResultPage'
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

function DocsRedirect() {
  const location = useLocation()
  const { moduleKey } = useParams()
  const currentKey = moduleKey || 'overview'
  const target = `/help/${currentKey}${location.search}${location.hash}`
  return <Navigate to={target} replace />
}

function EventAnalysisLegacyRedirect() {
  const location = useLocation()
  const nextPath = location.pathname.replace('/event-analysis', '/fms-event-analysis')
  const target = `${nextPath}${location.search}${location.hash}`
  return <Navigate to={target} replace />
}

// 旧路径 /tasks/:taskId/analysis 统一重定向到 /tasks/:taskId?tab=analysis
// 保留书签兼容；ResultPage 内部仍识别末尾 /analysis 做向前兼容。
function TaskAnalysisLegacyRedirect() {
  const location = useLocation()
  const { taskId } = useParams()
  const qs = new URLSearchParams(location.search)
  if (!qs.get('tab')) qs.set('tab', 'analysis')
  const target = `/tasks/${taskId}?${qs.toString()}${location.hash}`
  return <Navigate to={target} replace />
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      {/* /docs/* 原本是匿名可看的营销文档；现改为强制登录后查看。保留路径兼容旧链接，登录后跳到对应 /help 页 */}
      <Route path="/docs" element={<DocsRedirect />} />
      <Route path="/docs/:moduleKey" element={<DocsRedirect />} />
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
        <Route path="/tasks/:taskId/analysis" element={<PermissionRoute requiredPage="tasks/:taskId/analysis"><TaskAnalysisLegacyRedirect /></PermissionRoute>} />
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
        <Route path="/event-analysis/task/:analysisTaskId" element={<EventAnalysisLegacyRedirect />} />
        <Route path="/event-analysis" element={<EventAnalysisLegacyRedirect />} />
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
