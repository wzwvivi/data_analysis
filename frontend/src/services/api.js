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

export const configApi = {
  /** 公共配置: 不需要登录即可拉取, 目前只含 flight_assistant_url */
  getPublic: () => api.get('/config'),
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

/** 网络团队配置管理（MR1 只读 + MR2 Draft/审批；MR3 激活闸门） */
export const networkConfigApi = {
  // ── 只读（MR1） ──
  listParserFamilies: () => api.get('/network-config/parser-families'),
  listVersions: (status = null) =>
    api.get('/network-config/versions', {
      params: status ? { status } : {},
    }),
  getVersion: (versionId) =>
    api.get(`/network-config/versions/${versionId}`),
  getVersionPorts: (versionId) =>
    api.get(`/network-config/versions/${versionId}/ports`),
  getPortDetail: (versionId, portNumber) =>
    api.get(`/network-config/versions/${versionId}/ports/${portNumber}`),

  // ── Draft（MR2） ──
  listDrafts: (scope = 'all') => api.get('/network-config/drafts', { params: { scope } }),
  getDraft: (draftId) => api.get(`/network-config/drafts/${draftId}`),
  createDraftFromVersion: (body) => api.post('/network-config/drafts', { source: 'clone', ...body }),
  createDraftFromExcel: (formData) =>
    api.post('/network-config/drafts/from-excel', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    }),
  updateDraft: (draftId, body) => api.patch(`/network-config/drafts/${draftId}`, body),
  deleteDraft: (draftId) => api.delete(`/network-config/drafts/${draftId}`),

  addPort: (draftId, body) => api.post(`/network-config/drafts/${draftId}/ports`, body),
  updatePort: (draftId, portId, body) => api.patch(`/network-config/drafts/${draftId}/ports/${portId}`, body),
  deletePort: (draftId, portId) => api.delete(`/network-config/drafts/${draftId}/ports/${portId}`),
  bulkUpsertPorts: (draftId, rows) => api.post(`/network-config/drafts/${draftId}/bulk-upsert-ports`, rows),

  addField: (draftId, portId, body) => api.post(`/network-config/drafts/${draftId}/ports/${portId}/fields`, body),
  updateField: (draftId, portId, fieldId, body) =>
    api.patch(`/network-config/drafts/${draftId}/ports/${portId}/fields/${fieldId}`, body),
  deleteField: (draftId, portId, fieldId) =>
    api.delete(`/network-config/drafts/${draftId}/ports/${portId}/fields/${fieldId}`),

  checkDraft: (draftId) => api.post(`/network-config/drafts/${draftId}/check`),
  getDraftDiff: (draftId) => api.get(`/network-config/drafts/${draftId}/diff`),
  exportDraftExcel: (draftId) =>
    api.get(`/network-config/drafts/${draftId}/export-excel`, {
      responseType: 'blob',
      timeout: 120000,
    }),
  submitDraft: (draftId, body = {}) => api.post(`/network-config/drafts/${draftId}/submit`, body),

  // ── 审批 Change Request ──
  listChangeRequests: (scope = 'all') =>
    api.get('/network-config/change-requests', { params: { scope } }),
  getChangeRequest: (crId) => api.get(`/network-config/change-requests/${crId}`),
  signOffChangeRequest: (crId, body) =>
    api.post(`/network-config/change-requests/${crId}/sign-off`, body),
  publishChangeRequest: (crId) => api.post(`/network-config/change-requests/${crId}/publish`),

  // ── 版本运维 ──
  deprecateVersion: (versionId, body = {}) =>
    api.post(`/network-config/versions/${versionId}/deprecate`, body),

  // ── MR3 激活闸门 ──
  getActivationReport: (versionId) =>
    api.get(`/network-config/versions/${versionId}/activation-report`),
  refreshActivationReport: (versionId) =>
    api.post(`/network-config/versions/${versionId}/activation-report/refresh`),
  activateVersion: (versionId, body = {}) =>
    api.post(`/network-config/versions/${versionId}/activate`, body),
}

/** 设备协议（ARINC429 / CAN / RS422 …）*/
export const deviceProtocolApi = {
  listFamilies: () => api.get('/device-protocol/families'),
  getTree: ({ family = null, groupBy = 'ata' } = {}) => {
    const params = { group_by: groupBy }
    if (family) params.family = family
    return api.get('/device-protocol/tree', { params })
  },
  listAtaSystems: () => api.get('/device-protocol/ata-systems'),
  getNextDeviceNumber: (ataCode) =>
    api.get('/device-protocol/next-device-number', { params: { ata_code: ataCode } }),
  previewDeviceIdentity: (body) =>
    api.post('/device-protocol/preview-device-identity', body),

  listSpecs: (family = null) =>
    api.get('/device-protocol/specs', { params: family ? { family } : {} }),
  getSpec: (specId, { availabilityStatus } = {}) =>
    api.get(`/device-protocol/specs/${specId}`, {
      params: availabilityStatus ? { availability_status: availabilityStatus } : {},
    }),
  listSpecVersions: (specId, { availabilityStatus } = {}) =>
    api.get(`/device-protocol/specs/${specId}/versions`, {
      params: availabilityStatus ? { availability_status: availabilityStatus } : {},
    }),
  getVersion: (versionId) => api.get(`/device-protocol/versions/${versionId}`),
  /** 仅返回 availability_status=Available 的扁平版本列表（上传页按 parser_family 拉下拉） */
  listAvailableVersions: ({ parserFamily = null, ata = null, protocolFamily = null } = {}) => {
    const params = {}
    if (parserFamily) params.parser_family = parserFamily
    if (ata) params.ata = ata
    if (protocolFamily) params.protocol_family = protocolFamily
    return api.get('/device-protocol/versions/available', { params })
  },
  compareVersions: (specId, versionAId, versionBId) =>
    api.get(`/device-protocol/specs/${specId}/compare`, {
      params: { version_a_id: versionAId, version_b_id: versionBId },
    }),
  getChangelog: (specId) => api.get(`/device-protocol/specs/${specId}/changelog`),
  activateVersion: (versionId, body = {}) =>
    api.post(`/device-protocol/versions/${versionId}/activate`, body),
  deprecateVersion: (versionId, body = {}) =>
    api.post(`/device-protocol/versions/${versionId}/deprecate`, body),
  getActivationReport: (versionId) =>
    api.get(`/device-protocol/versions/${versionId}/activation-report`),
  /** 一键「修改协议」：对某设备自动建/复用一条草稿 */
  editSpec: (specId) => api.post(`/device-protocol/specs/${specId}/edit-draft`),

  listDrafts: (params = {}) => api.get('/device-protocol/drafts', { params }),
  getDraft: (draftId) => api.get(`/device-protocol/drafts/${draftId}`),
  createDraftFromVersion: (body) =>
    api.post('/device-protocol/drafts', { source: 'clone', ...body }),
  createDraftScratch: (body) =>
    api.post('/device-protocol/drafts', { source: 'scratch', ...body }),
  updateDraft: (draftId, body) => api.patch(`/device-protocol/drafts/${draftId}`, body),
  deleteDraft: (draftId) => api.delete(`/device-protocol/drafts/${draftId}`),
  checkDraft: (draftId) => api.post(`/device-protocol/drafts/${draftId}/check`),
  getDraftDiff: (draftId) => api.get(`/device-protocol/drafts/${draftId}/diff`),
  submitDraft: (draftId, body = {}) =>
    api.post(`/device-protocol/drafts/${draftId}/submit`, body),

  listChangeRequests: ({ scope, family, ...rest } = {}) => {
    const params = { ...rest }
    if (scope) params.scope = scope
    if (family) params.family = family
    return api.get('/device-protocol/change-requests', { params })
  },
  getChangeRequest: (crId) => api.get(`/device-protocol/change-requests/${crId}`),
  signOffChangeRequest: (crId, body) =>
    api.post(`/device-protocol/change-requests/${crId}/sign-off`, body),
  publishChangeRequest: (crId) =>
    api.post(`/device-protocol/change-requests/${crId}/publish`),
}

/** 站内通知 */
export const notificationApi = {
  list: (params = {}) => api.get('/notifications', { params }),
  markRead: (id) => api.post(`/notifications/${id}/read`),
  markAllRead: () => api.post('/notifications/read-all'),
}

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
  
  // 获取任务列表（支持任务中心的多维过滤：q/status/source/date_from/date_to/tag/protocol_version_id）
  listTasks: (params = {}) => {
    const { page = 1, pageSize = 20, ...rest } = params
    return api.get('/parse/tasks', { params: { page, page_size: pageSize, ...rest } })
  },

  // 编辑任务元数据（重命名 / 打标签）
  updateTaskMeta: (taskId, body) => api.patch(`/parse/tasks/${taskId}`, body),

  // 删除任务
  deleteTask: (taskId) => api.delete(`/parse/tasks/${taskId}`),

  // 批量删除
  bulkDeleteTasks: (taskIds) => api.post('/parse/tasks/bulk-delete', { task_ids: taskIds }),

  // 取消任务（协作式，后台循环巡检）
  cancelTask: (taskId) => api.post(`/parse/tasks/${taskId}/cancel`),

  // 重新解析（新建任务，复用原始文件 + 设备映射）
  rerunTask: (taskId) => api.post(`/parse/tasks/${taskId}/rerun`),

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

// 飞管事件分析相关API（原 eventAnalysisApi，Phase 1 renamed 到 fmsEventAnalysisApi）
export const fmsEventAnalysisApi = {
  // 运行飞管事件分析
  run: (parseTaskId, ruleTemplate = 'default_v1', bundleVersionId = null) =>
    api.post(`/fms-event-analysis/tasks/${parseTaskId}/run`, null, {
      params: {
        rule_template: ruleTemplate,
        ...(bundleVersionId ? { bundle_version_id: bundleVersionId } : {}),
      },
    }),

  // 获取分析任务状态
  getTask: (parseTaskId) => api.get(`/fms-event-analysis/tasks/${parseTaskId}`),

  // 获取检查单结果列表
  getCheckResults: (parseTaskId) =>
    api.get(`/fms-event-analysis/tasks/${parseTaskId}/check-results`),

  // 获取单个检查项详情
  getCheckDetail: (parseTaskId, checkId) =>
    api.get(`/fms-event-analysis/tasks/${parseTaskId}/check-results/${checkId}`),

  // 获取事件时间线
  getTimeline: (parseTaskId) =>
    api.get(`/fms-event-analysis/tasks/${parseTaskId}/timeline`),

  /** 单个 xlsx：概览、检查结果、时间线 三个 Sheet */
  exportResults: (parseTaskId) =>
    api.get(`/fms-event-analysis/tasks/${parseTaskId}/export`, {
      responseType: 'blob',
      timeout: 120000,
    }),
}

// Phase 1 向后兼容别名
export const eventAnalysisApi = fmsEventAnalysisApi

/** 独立飞管事件分析（直接上传 pcap，不依赖解析任务） */
export const standaloneFmsEventApi = {
  upload: (formData, onUploadProgress) =>
    api.post('/fms-event-analysis/standalone/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
      onUploadProgress,
    }),

  fromShared: (formData) =>
    api.post('/fms-event-analysis/standalone/from-shared', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    }),
  listTasks: (page = 1, pageSize = 20) =>
    api.get('/fms-event-analysis/standalone/tasks', {
      params: { page, page_size: pageSize },
    }),
  getTask: (analysisTaskId) =>
    api.get(`/fms-event-analysis/standalone/tasks/${analysisTaskId}`),
  getCheckResults: (analysisTaskId) =>
    api.get(`/fms-event-analysis/standalone/tasks/${analysisTaskId}/check-results`),
  getCheckDetail: (analysisTaskId, checkId) =>
    api.get(`/fms-event-analysis/standalone/tasks/${analysisTaskId}/check-results/${checkId}`),
  getTimeline: (analysisTaskId) =>
    api.get(`/fms-event-analysis/standalone/tasks/${analysisTaskId}/timeline`),

  exportResults: (analysisTaskId) =>
    api.get(`/fms-event-analysis/standalone/tasks/${analysisTaskId}/export`, {
      responseType: 'blob',
      timeout: 120000,
    }),
}

// Phase 1 向后兼容别名
export const standaloneEventApi = standaloneFmsEventApi

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

/** 构型管理（设备库 / 飞机构型 / 软件构型） */
export const configurationApi = {
  // ── 设备库 ──
  listDevices: (params = {}) => api.get('/configurations/devices', { params }),
  listDeviceTeams: () => api.get('/configurations/devices/teams'),
  createDevice: (body) => api.post('/configurations/devices', body),
  updateDevice: (id, body) => api.put(`/configurations/devices/${id}`, body),
  deleteDevice: (id) => api.delete(`/configurations/devices/${id}`),

  // ── 飞机构型 ──
  listAircraftConfigs: () => api.get('/configurations/aircraft'),
  getAircraftConfig: (id) => api.get(`/configurations/aircraft/${id}`),
  createAircraftConfig: (body) => api.post('/configurations/aircraft', body),
  updateAircraftConfig: (id, body) => api.put(`/configurations/aircraft/${id}`, body),
  deleteAircraftConfig: (id) => api.delete(`/configurations/aircraft/${id}`),

  // ── 软件构型 ──
  listSoftwareConfigs: () => api.get('/configurations/software'),
  getSoftwareConfig: (id) => api.get(`/configurations/software/${id}`),
  createSoftwareConfig: (body) => api.post('/configurations/software', body),
  updateSoftwareConfig: (id, body) => api.put(`/configurations/software/${id}`, body),
  deleteSoftwareConfig: (id) => api.delete(`/configurations/software/${id}`),
  listSoftwareEntries: (id) => api.get(`/configurations/software/${id}/entries`),
  upsertSoftwareEntries: (id, items, replaceAll = false) =>
    api.put(`/configurations/software/${id}/entries`, { items, replace_all: replaceAll }),
  importSoftwareExcel: (formData) =>
    api.post('/configurations/software/import-excel', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    }),

  // ── 选项 ──
  listTsnProtocolVersionOptions: () =>
    api.get('/configurations/options/tsn-protocol-versions'),
  listDeviceProtocolVersionOptions: () =>
    api.get('/configurations/options/device-protocol-versions'),
}

/** 试验工作台（按架次） */
export const workbenchApi = {
  getSortie: (sortieId) => api.get(`/workbench/sorties/${sortieId}`),
  listMatchedTasks: (sortieId) => api.get(`/workbench/sorties/${sortieId}/matched-tasks`),
  getOverview: (sortieId, parseTaskId) =>
    api.get(`/workbench/sorties/${sortieId}/overview`, { params: { parse_task_id: parseTaskId } }),
  getEventsSummary: (sortieId, parseTaskId) =>
    api.get(`/workbench/sorties/${sortieId}/events-summary`, { params: { parse_task_id: parseTaskId } }),
}

export default api
