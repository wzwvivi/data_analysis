import { PAGE_FLIGHT_ASSISTANT } from '../constants/roles'

export const MODULE_GROUPS = [
  { key: 'common', title: '常用入口', desc: '登录后最常进入的核心模块。', order: 10 },
  { key: 'analysis', title: '专项分析', desc: '面向异常定位与性能复盘的专项能力。', order: 20 },
  { key: 'governance', title: '配置与管理', desc: '用于配置治理与系统管理。', order: 30 },
]

export const MODULE_REGISTRY = [
  {
    key: 'dashboard',
    group: 'common',
    icon: 'dashboard',
    title: '平台仪表盘',
    summary: '查看关键指标、趋势图和最新任务动态。',
    path: '/dashboard',
    permissionAny: ['dashboard'],
  },
  {
    key: 'upload',
    group: 'common',
    icon: 'upload',
    title: '上传解析',
    summary: '上传 TSN 数据并绑定协议版本后启动解析。',
    path: '/upload',
    permissionAny: ['upload'],
  },
  {
    key: 'tasks',
    group: 'common',
    icon: 'tasks',
    title: '任务中心',
    summary: '筛选任务、追踪进度并进入结果分析。',
    path: '/tasks',
    permissionAny: ['tasks'],
  },
  {
    key: 'workbench',
    group: 'common',
    icon: 'workbench',
    title: '试验工作台',
    summary: '按架次聚合任务数据并快速联查。',
    path: '/workbench',
    permissionAny: ['workbench'],
  },
  {
    key: 'workbench-compare',
    group: 'analysis',
    icon: 'swap',
    title: '跨架次对比',
    summary: '对比多个架次的指标与事件数量，偏复盘（需先在工作台选择架次）。',
    path: '/workbench',
    permissionAny: ['workbench'],
  },
  {
    key: 'fms-event-analysis',
    group: 'analysis',
    icon: 'search',
    title: '飞管事件分析',
    summary: '追踪飞管事件触发链路与诊断结果。',
    path: '/fms-event-analysis',
    permissionAny: ['fms-event-analysis', 'event-analysis'],
  },
  {
    key: 'fcc-event-analysis',
    group: 'analysis',
    icon: 'search',
    title: '飞控事件分析',
    summary: '定位飞控事件与关键参数变化。',
    path: '/fcc-event-analysis',
    permissionAny: ['fcc-event-analysis'],
  },
  {
    key: 'auto-flight-analysis',
    group: 'analysis',
    icon: 'linechart',
    title: '自动飞行性能分析',
    summary: '评估自动飞行阶段性能与趋势。',
    path: '/auto-flight-analysis',
    permissionAny: ['auto-flight-analysis'],
  },
  {
    key: 'compare',
    group: 'analysis',
    icon: 'swap',
    title: 'TSN 异常检查',
    summary: '对两份抓包做时间同步、端口覆盖与周期抖动检查。',
    path: '/compare',
    permissionAny: ['compare'],
  },
  {
    key: 'flight-assistant',
    group: 'analysis',
    icon: 'assistant',
    title: 'CSV 架次分析',
    summary: '打开飞行助手服务进行 CSV 架次分析。',
    externalConfigKey: 'flight_assistant_url',
    permissionAny: [PAGE_FLIGHT_ASSISTANT],
  },
  {
    key: 'network-config',
    group: 'governance',
    icon: 'network',
    title: 'TSN 网络配置管理',
    summary: '在模块内维护网络侧协议与版本的草稿、审批与发布。',
    path: '/network-config',
    permissionAny: ['network-config'],
  },
  {
    key: 'device-protocol',
    group: 'governance',
    icon: 'protocol',
    title: '设备协议管理',
    summary: '管理设备协议定义与版本发布。',
    path: '/device-protocol',
    permissionAny: ['device-protocol'],
  },
  {
    key: 'platform-data',
    group: 'governance',
    icon: 'database',
    title: '平台共享数据',
    summary: '管理共享文件与视频预处理状态。',
    path: '/admin/platform-data',
    adminOnly: true,
  },
  {
    key: 'configurations',
    group: 'governance',
    icon: 'setting',
    title: '构型管理',
    summary: '维护系统级配置项与运行策略。',
    path: '/admin/configurations',
    adminOnly: true,
  },
  {
    key: 'users',
    group: 'governance',
    icon: 'team',
    title: '用户管理',
    summary: '配置账号角色与页面权限映射。',
    path: '/admin/users',
    adminOnly: true,
  },
]

function canViewModule(module, context) {
  const { isAdmin, hasPageAccess, publicConfig } = context

  if (module.adminOnly) {
    return Boolean(isAdmin)
  }

  if (module.permissionAny?.length) {
    const matched = module.permissionAny.some((pageKey) => hasPageAccess(pageKey))
    if (!matched) return false
  }

  if (module.externalConfigKey) {
    const raw = publicConfig?.[module.externalConfigKey]
    return typeof raw === 'string' && raw.trim().length > 0
  }

  return true
}

function resolveExternalUrl(module, publicConfig) {
  if (!module.externalConfigKey) return ''
  const raw = publicConfig?.[module.externalConfigKey]
  return typeof raw === 'string' ? raw.trim() : ''
}

export function getVisibleModuleSections(context) {
  return MODULE_GROUPS
    .map((group) => {
      const modules = MODULE_REGISTRY
        .filter((module) => module.group === group.key)
        .filter((module) => canViewModule(module, context))
        .map((module) => ({
          ...module,
          externalUrl: resolveExternalUrl(module, context.publicConfig),
        }))
      return { ...group, modules }
    })
    .filter((group) => group.modules.length > 0)
    .sort((a, b) => a.order - b.order)
}
