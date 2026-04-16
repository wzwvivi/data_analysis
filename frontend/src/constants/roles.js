export const ROLE_LABELS = {
  admin: '管理员',
  user: '普通用户(兼容)',
  data_manager_tsn: '数据管理(TSN记录器)',
  data_manager_fcc: '数据管理(飞控记录器)',
  data_manager_ground: '数据管理(地面网联)',
  leader: '领导/试飞团队',
  dev_fcc: '开发团队(飞控)',
  dev_auto_flight: '开发团队(自动飞行)',
  dev_tsn: '开发团队(TSN)',
  device_team: '设备团队',
  network_team: '网络团队',
}

export const ROLE_OPTIONS = Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))
