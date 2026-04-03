import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import MainLayout from './components/MainLayout'
import UploadPage from './pages/UploadPage'
import TaskListPage from './pages/TaskListPage'
import ResultPage from './pages/ResultPage'
import AnalysisPage from './pages/AnalysisPage'
import EventAnalysisPage from './pages/EventAnalysisPage'
import StandaloneEventPage from './pages/StandaloneEventPage'
import ProtocolPage from './pages/ProtocolPage'
import ComparePage from './pages/ComparePage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<MainLayout />}>
          <Route index element={<Navigate to="/upload" replace />} />
          <Route path="upload" element={<UploadPage />} />
          <Route path="tasks" element={<TaskListPage />} />
          <Route path="tasks/:taskId" element={<ResultPage />} />
          <Route path="tasks/:taskId/analysis" element={<AnalysisPage />} />
          <Route path="tasks/:taskId/event-analysis" element={<EventAnalysisPage />} />
          <Route path="network-config" element={<ProtocolPage />} />
          <Route path="compare" element={<ComparePage />} />
          <Route path="compare/:taskId" element={<ComparePage />} />
          <Route path="event-analysis" element={<StandaloneEventPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
