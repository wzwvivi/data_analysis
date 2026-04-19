import axios from 'axios'

export const TOKEN_KEY = 'tsn_access_token'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

api.interceptors.request.use((config) => {
  const t = localStorage.getItem(TOKEN_KEY)
  if (t) {
    config.headers.Authorization = `Bearer ${t}`
  }
  return config
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  }
)

export const authApi = {
  /** 支持 login(u, p) 或 login({ username, password })，避免旧代码或缓存导致错误请求体 */
  login: (usernameOrCreds, password) => {
    const payload =
      usernameOrCreds != null &&
      typeof usernameOrCreds === 'object' &&
      !Array.isArray(usernameOrCreds) &&
      'username' in usernameOrCreds
        ? {
            username: usernameOrCreds.username,
            password: usernameOrCreds.password,
          }
        : { username: usernameOrCreds, password }
    return api.post('/auth/login', payload)
  },
  me: () => api.get('/auth/me'),
  permissions: () => api.get('/auth/permissions'),
  listRoles: () => api.get('/auth/roles'),
  listUsers: () => api.get('/auth/users'),
  listLegacyRoleUsers: () => api.get('/auth/users/legacy-role'),
  createUser: (data) => api.post('/auth/users', data),
  deleteUser: (userId) => api.delete(`/auth/users/${userId}`),
  updateUserRole: (userId, role) => api.put(`/auth/users/${userId}/role`, { role }),
  resetPassword: (userId, newPassword) => api.put(`/auth/users/${userId}/reset-password`, { new_password: newPassword }),
  changePassword: (oldPassword, newPassword) => api.put('/auth/password', { old_password: oldPassword, new_password: newPassword }),
}

export const roleConfigApi = {
  listRoles: () => api.get('/role-config/roles'),
  getRolePorts: (role, protocolVersionId) =>
    api.get(`/role-config/${role}/ports`, { params: { protocol_version_id: protocolVersionId } }),
  setRolePorts: (role, protocolVersionId, ports) =>
    api.put(`/role-config/${role}/ports`, { protocol_version_id: protocolVersionId, ports }),
}

/** 平台共享数据（管理员按试验架次上传，全员可选用） */
export const sharedTsnApi = {
  list: () => api.get('/shared-tsn'),
  /** 按试验架次分组的树结构 */
  listSorties: () => api.get('/shared-tsn/sorties'),
  assetKinds: () => api.get('/shared-tsn/asset-kinds'),
  createSortie: (body) => api.post('/shared-tsn/sorties', body),
  updateSortie: (sortieId, body) => api.patch(`/shared-tsn/sorties/${sortieId}`, body),
  deleteSortie: (sortieId) => api.delete(`/shared-tsn/sorties/${sortieId}`),
  upload: (formData, onUploadProgress) =>
    api.post('/shared-tsn/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
      onUploadProgress,
    }),
  /** HEVC→H.264 后台转码进度（轮询） */
  videoJob: (sharedId) => api.get(`/shared-tsn/files/${sharedId}/video-job`),
  update: (id, body) => api.patch(`/shared-tsn/${id}`, body),
  remove: (id) => api.delete(`/shared-tsn/${id}`),
}

/** 协议管理（设备树、Label、版本）— 写操作需管理员 */
export const protocolManagerApi = {
  getDeviceTree: () => api.get('/protocol-manager/device-tree'),
  createSystem: (body) => api.post('/protocol-manager/systems', body),
  createDevice: (body) => api.post('/protocol-manager/devices', body),
  deleteDevice: (deviceId) => api.delete(`/protocol-manager/devices/${encodeURIComponent(deviceId)}`),
  setActiveVersion: (deviceId, currentVersionName) =>
    api.put(`/protocol-manager/devices/${encodeURIComponent(deviceId)}/active-version`, {
      current_version_name: currentVersionName,
    }),
  getLabels: (deviceId, protocolVersionId) =>
    api.get(`/protocol-manager/devices/${encodeURIComponent(deviceId)}/labels`, {
      params: protocolVersionId != null ? { protocol_version_id: protocolVersionId } : {},
    }),
  saveLabels: (deviceId, body) =>
    api.post(`/protocol-manager/devices/${encodeURIComponent(deviceId)}/labels`, body),
  deleteLabel: (deviceId, labelId) =>
    api.delete(`/protocol-manager/devices/${encodeURIComponent(deviceId)}/labels/${labelId}`),
  listProtocolVersions: (deviceId) =>
    api.get(`/protocol-manager/devices/${encodeURIComponent(deviceId)}/versions`),
  listHistory: (deviceId, limit = 50) =>
    api.get(`/protocol-manager/devices/${encodeURIComponent(deviceId)}/history`, { params: { limit } }),
  getSnapshotLabels: (deviceId, version) =>
    api.get(
      `/protocol-manager/devices/${encodeURIComponent(deviceId)}/versions/${encodeURIComponent(version)}/labels`
    ),
  restoreVersion: (deviceId, version) =>
    api.post(
      `/protocol-manager/devices/${encodeURIComponent(deviceId)}/versions/${encodeURIComponent(version)}/restore`
    ),
}

// 向后兼容旧命名，避免其他页面暂时引用失败
export const arinc429Api = protocolManagerApi

// 协议（网络配置）相关API
export const protocolApi = {
  // 获取协议列表（含嵌套版本）
  list: () => api.get('/protocols'),
  
  // 获取协议详情
  get: (id) => api.get(`/protocols/${id}`),
  
  // 创建协议
  create: (data) => api.post('/protocols', data),
  
  // 导入ICD文件
  import: (formData) => api.post('/protocols/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  }),
  
  // 获取所有网络配置版本（扁平列表，供上传页选择）
  listVersions: () => api.get('/protocols/versions'),
  
  // 获取版本下的端口
  getPorts: (versionId) => api.get(`/protocols/versions/${versionId}/ports`),
  
  // 获取端口详情
  getPortDetail: (versionId, portNumber) => 
    api.get(`/protocols/versions/${versionId}/ports/${portNumber}`),
  
  // 获取版本下的设备列表（按设备聚合端口）
  getDevices: (versionId) => api.get(`/protocols/versions/${versionId}/devices`),
}

// 解析任务相关API
export const parseApi = {
  // 获取解析版本列表
  getProfiles: () => api.get('/parse/profiles'),
  
  // 获取解析版本详情
  getProfile: (profileId) => api.get(`/parse/profiles/${profileId}`),
  
  // 上传并解析
  upload: (formData, onUploadProgress) => api.post('/parse/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000,
    onUploadProgress
  }),

  /** 使用平台共享 TSN 创建解析任务 */
  uploadFromShared: (formData, onUploadProgress) =>
    api.post('/parse/upload-from-shared', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
      onUploadProgress,
    }),
  
  // 获取任务列表
  listTasks: (page = 1, pageSize = 20) => 
    api.get('/parse/tasks', { params: { page, page_size: pageSize } }),
  
  // 获取任务详情
  getTask: (taskId) => api.get(`/parse/tasks/${taskId}`),
  
  // 获取解析数据
  getData: (taskId, portNumber, params = {}) => 
    api.get(`/parse/tasks/${taskId}/data/${portNumber}`, { params }),
  
  // 获取时序数据
  getTimeSeries: (taskId, portNumber, fieldName, params = {}) =>
    api.get(`/parse/tasks/${taskId}/timeseries/${portNumber}/${fieldName}`, { params }),
  
  // 导出数据
  exportData: (taskId, portNumber, format = 'csv', params = {}) =>
    api.get(`/parse/tasks/${taskId}/export/${portNumber}`, {
      params: { format, ...params },
      responseType: 'blob',
      timeout: 300000,
    }),

  // 批量导出多端口到一个 ZIP（每端口一个 CSV）
  exportBatch: (taskId, ports, parserIds = [], includeTextColumns = true) =>
    api.get(`/parse/tasks/${taskId}/export-batch`, {
      params: {
        ports: ports.join(','),
        parser_ids: parserIds.join(','),
        include_text_columns: includeTextColumns,
      },
      responseType: 'blob',
      timeout: 120000,
    }),

  /** 端口异常分析：数值字段与默认跳变阈值（%） */
  getAnomalyDefaults: (taskId, portNumber, params = {}) =>
    api.get(`/parse/tasks/${taskId}/anomaly/${portNumber}/defaults`, { params }),

  /** 端口异常分析：跳变 / 卡死 */
  analyzeAnomaly: (taskId, portNumber, body) =>
    api.post(`/parse/tasks/${taskId}/anomaly/${portNumber}/analyze`, body, {
      timeout: 300000,
    }),
}

// 事件分析相关API
export const eventAnalysisApi = {
  // 运行事件分析
  run: (parseTaskId, ruleTemplate = 'default_v1') =>
    api.post(`/event-analysis/tasks/${parseTaskId}/run`, null, {
      params: { rule_template: ruleTemplate }
    }),
  
  // 获取分析任务状态
  getTask: (parseTaskId) => api.get(`/event-analysis/tasks/${parseTaskId}`),
  
  // 获取检查单结果列表
  getCheckResults: (parseTaskId) =>
    api.get(`/event-analysis/tasks/${parseTaskId}/check-results`),
  
  // 获取单个检查项详情
  getCheckDetail: (parseTaskId, checkId) =>
    api.get(`/event-analysis/tasks/${parseTaskId}/check-results/${checkId}`),
  
  // 获取事件时间线
  getTimeline: (parseTaskId) =>
    api.get(`/event-analysis/tasks/${parseTaskId}/timeline`),

  /** 单个 xlsx：概览、检查结果、时间线 三个 Sheet */
  exportResults: (parseTaskId) =>
    api.get(`/event-analysis/tasks/${parseTaskId}/export`, {
      responseType: 'blob',
      timeout: 120000,
    }),
}

/** 独立事件分析（直接上传 pcap，不依赖解析任务） */
export const standaloneEventApi = {
  upload: (formData, onUploadProgress) =>
    api.post('/event-analysis/standalone/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
      onUploadProgress,
    }),

  fromShared: (formData) =>
    api.post('/event-analysis/standalone/from-shared', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    }),
  listTasks: (page = 1, pageSize = 20) =>
    api.get('/event-analysis/standalone/tasks', {
      params: { page, page_size: pageSize },
    }),
  getTask: (analysisTaskId) =>
    api.get(`/event-analysis/standalone/tasks/${analysisTaskId}`),
  getCheckResults: (analysisTaskId) =>
    api.get(`/event-analysis/standalone/tasks/${analysisTaskId}/check-results`),
  getCheckDetail: (analysisTaskId, checkId) =>
    api.get(`/event-analysis/standalone/tasks/${analysisTaskId}/check-results/${checkId}`),
  getTimeline: (analysisTaskId) =>
    api.get(`/event-analysis/standalone/tasks/${analysisTaskId}/timeline`),

  exportResults: (analysisTaskId) =>
    api.get(`/event-analysis/standalone/tasks/${analysisTaskId}/export`, {
      responseType: 'blob',
      timeout: 120000,
    }),
}

/** 飞控事件分析（FCC Event Analysis） */
export const fccEventAnalysisApi = {
  upload: (formData, onUploadProgress) =>
    api.post('/fcc-event-analysis/standalone/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
      onUploadProgress,
    }),

  fromShared: (formData) =>
    api.post('/fcc-event-analysis/standalone/from-shared', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    }),

  listTasks: (page = 1, pageSize = 20) =>
    api.get('/fcc-event-analysis/standalone/tasks', {
      params: { page, page_size: pageSize },
    }),

  getTask: (taskId) =>
    api.get(`/fcc-event-analysis/standalone/tasks/${taskId}`),

  getCheckResults: (taskId) =>
    api.get(`/fcc-event-analysis/standalone/tasks/${taskId}/check-results`),

  getCheckDetail: (taskId, checkId) =>
    api.get(`/fcc-event-analysis/standalone/tasks/${taskId}/check-results/${checkId}`),

  getTimeline: (taskId) =>
    api.get(`/fcc-event-analysis/standalone/tasks/${taskId}/timeline`),

  exportResults: (taskId) =>
    api.get(`/fcc-event-analysis/standalone/tasks/${taskId}/export`, {
      responseType: 'blob',
      timeout: 120000,
    }),
}

/** 自动飞行性能分析（Auto Flight Performance Analysis） */
export const autoFlightAnalysisApi = {
  upload: (formData, onUploadProgress) =>
    api.post('/auto-flight-analysis/standalone/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
      onUploadProgress,
    }),

  fromShared: (formData) =>
    api.post('/auto-flight-analysis/standalone/from-shared', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    }),

  fromParseTask: (formData) =>
    api.post('/auto-flight-analysis/from-parse-task', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    }),

  listTasks: (page = 1, pageSize = 20) =>
    api.get('/auto-flight-analysis/tasks', {
      params: { page, page_size: pageSize },
    }),

  getTask: (taskId) =>
    api.get(`/auto-flight-analysis/tasks/${taskId}`),

  getTouchdowns: (taskId) =>
    api.get(`/auto-flight-analysis/tasks/${taskId}/touchdowns`),

  getTouchdownDetail: (taskId, tdId) =>
    api.get(`/auto-flight-analysis/tasks/${taskId}/touchdowns/${tdId}`),

  getSteadyStates: (taskId) =>
    api.get(`/auto-flight-analysis/tasks/${taskId}/steady-states`),

  getSteadyStateDetail: (taskId, ssId) =>
    api.get(`/auto-flight-analysis/tasks/${taskId}/steady-states/${ssId}`),

  exportResults: (taskId) =>
    api.get(`/auto-flight-analysis/tasks/${taskId}/export`, {
      responseType: 'blob',
      timeout: 120000,
    }),
}

// TSN数据异常检查（双交换机比对）相关 API
export const compareApi = {
  // 上传两个文件并创建比对任务
  upload: (formData, onUploadProgress) => api.post('/compare/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000,
    onUploadProgress,
  }),
  
  // 获取比对任务列表
  listTasks: (page = 1, pageSize = 20) =>
    api.get('/compare/tasks', { params: { page, page_size: pageSize } }),
  
  // 获取比对任务详情
  getTask: (taskId) => api.get(`/compare/tasks/${taskId}`),
  
  // 获取端口比对结果列表
  getPortResults: (taskId) => api.get(`/compare/tasks/${taskId}/ports`),
  
  // 获取丢包记录列表
  getGaps: (taskId, port = null) =>
    api.get(`/compare/tasks/${taskId}/gaps`, { params: port ? { port } : {} }),
  
  // 获取端口周期正确性与抖动分析结果
  getTimingResults: (taskId, port = null, switchIndex = null) =>
    api.get(`/compare/tasks/${taskId}/timing`, { 
      params: { 
        ...(port ? { port } : {}),
        ...(switchIndex ? { switch: switchIndex } : {})
      } 
    }),
  
  // 导出比对报告
  exportReport: (taskId) =>
    api.get(`/compare/tasks/${taskId}/export`, {
      responseType: 'blob',
      timeout: 120000,
    }),
}

/** 平台总览仪表盘 */
export const dashboardApi = {
  getOverview: () => api.get('/dashboard/overview'),
}

/** 试验工作台（按架次） */
export const workbenchApi = {
  getSortie: (sortieId) => api.get(`/workbench/sorties/${sortieId}`),
}

export default api
