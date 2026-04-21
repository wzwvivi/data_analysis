export const ROLE_LABELS = {
  admin: '管理员',
  user: '普通用户(兼容)',
  data_manager_tsn: '数据管理(TSN记录器)',
  data_manager_fcc: '数据管理(飞控记录器)',
  data_manager_ground: '数据管理(地面网联)',
  leader: '领导/试飞团队',
  dev_fcc: '开发团队(飞控)',
  dev_fms: '开发团队(飞管)',
  dev_auto_flight: '开发团队(自动飞行)',
  device_team: '设备团队',
  network_team: 'TSN/网络团队',
}

// 已下线角色 → 当前角色 的兼容映射（仅用于展示侧的兜底）
export const LEGACY_ROLE_ALIASES = {
  dev_tsn: 'network_team',
}

export const ROLE_OPTIONS = Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))

// 页面权限 key: 与后端 backend/app/permissions.py 的 PAGE_* 常量保持一致。
// 目前只显式导出需要在菜单等处引用的 key; 历史代码仍以字符串字面量为主。
export const PAGE_FLIGHT_ASSISTANT = 'flight-assistant'
