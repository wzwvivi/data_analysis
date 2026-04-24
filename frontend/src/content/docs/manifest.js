import overviewRaw from './overview.md?raw'
import quickstartRaw from './quickstart.md?raw'
import glossaryRaw from './glossary.md?raw'
import uploadRaw from './upload.md?raw'
import tasksRaw from './tasks.md?raw'
import resultAnalysisRaw from './result-analysis.md?raw'
import networkConfigRaw from './network-config.md?raw'
import deviceProtocolRaw from './device-protocol.md?raw'
import fmsEventRaw from './fms-event-analysis.md?raw'
import fccEventRaw from './fcc-event-analysis.md?raw'
import autoFlightRaw from './auto-flight-analysis.md?raw'
import compareRaw from './compare.md?raw'
import workbenchRaw from './workbench.md?raw'
import workbenchCompareRaw from './workbench-compare.md?raw'
import flightAssistantRaw from './flight-assistant.md?raw'
import platformDataRaw from './platform-data.md?raw'
import configurationsRaw from './configurations.md?raw'
import usersRaw from './users.md?raw'
import faqRaw from './faq.md?raw'
import changelogRaw from './changelog.md?raw'

export const DOC_GROUPS = [
  { key: 'overview', title: '总览', order: 10 },
  { key: 'network', title: '网络数据分析', order: 20 },
  { key: 'events', title: '专项分析', order: 30 },
  { key: 'workbench', title: '工作台', order: 40 },
  { key: 'assistant', title: '飞行助手', order: 50 },
  { key: 'system', title: '系统管理', order: 60 },
  { key: 'appendix', title: '附录', order: 70 },
]

export const DOCS = [
  {
    key: 'overview',
    group: 'overview',
    order: 1,
    title: '平台介绍',
    summary: '了解网络数据分析平台的定位、能力边界与推荐工作流。',
    raw: overviewRaw,
  },
  {
    key: 'quickstart',
    group: 'overview',
    order: 2,
    title: '快速开始',
    summary: '用 10 分钟完成首次登录、上传解析、任务查看与结果联动。',
    raw: quickstartRaw,
  },
  {
    key: 'glossary',
    group: 'overview',
    order: 3,
    title: '术语说明',
    summary: '统一任务、版本、端口、架次等核心概念，降低沟通成本。',
    raw: glossaryRaw,
  },
  {
    key: 'upload',
    group: 'network',
    order: 1,
    title: '上传解析',
    summary: '上传 TSN 数据文件并选择协议版本、端口范围启动解析。',
    raw: uploadRaw,
  },
  {
    key: 'tasks',
    group: 'network',
    order: 2,
    title: '任务中心',
    summary: '统一查看解析任务状态、结果入口和失败原因。',
    raw: tasksRaw,
  },
  {
    key: 'result-analysis',
    group: 'network',
    order: 3,
    title: '结果分析',
    summary: '查看解析后的表格、趋势图与异常分析结果。',
    raw: resultAnalysisRaw,
  },
  {
    key: 'network-config',
    group: 'network',
    order: 4,
    title: 'TSN 网络配置',
    summary: '管理网络配置草稿、审批流与发布版本，保障配置可追踪。',
    raw: networkConfigRaw,
  },
  {
    key: 'device-protocol',
    group: 'network',
    order: 5,
    title: '设备协议管理',
    summary: '维护设备协议定义与版本，供上传解析页面选择并绑定。',
    raw: deviceProtocolRaw,
  },
  {
    key: 'fms-event-analysis',
    group: 'events',
    order: 1,
    title: '飞管事件分析',
    summary: '从解析结果中抽取飞管事件并追踪任务级诊断信息。',
    raw: fmsEventRaw,
  },
  {
    key: 'fcc-event-analysis',
    group: 'events',
    order: 2,
    title: '飞控事件分析',
    summary: '分析飞控事件、告警触发链路与关键参数变化。',
    raw: fccEventRaw,
  },
  {
    key: 'auto-flight-analysis',
    group: 'events',
    order: 3,
    title: '自动飞行性能分析',
    summary: '评估自动飞行阶段性能指标与任务趋势。',
    raw: autoFlightRaw,
  },
  {
    key: 'compare',
    group: 'events',
    order: 4,
    title: 'TSN 异常检查',
    summary: '执行任务间差异比对，定位异常变化点。',
    raw: compareRaw,
  },
  {
    key: 'workbench',
    group: 'workbench',
    order: 1,
    title: '试验工作台',
    summary: '按架次聚合数据，完成跨任务联查与快速下钻。',
    raw: workbenchRaw,
  },
  {
    key: 'workbench-compare',
    group: 'workbench',
    order: 2,
    title: '架次比对',
    summary: '在工作台上下文中比较两次架次关键指标差异。',
    raw: workbenchCompareRaw,
  },
  {
    key: 'flight-assistant',
    group: 'assistant',
    order: 1,
    title: 'CSV 架次分析',
    summary: '通过飞行助手外链完成 CSV 架次级分析与导出。',
    raw: flightAssistantRaw,
  },
  {
    key: 'platform-data',
    group: 'system',
    order: 1,
    title: '平台共享数据',
    summary: '统一管理跨任务共享文件与视频预处理状态（管理员）。',
    raw: platformDataRaw,
  },
  {
    key: 'configurations',
    group: 'system',
    order: 2,
    title: '构型管理',
    summary: '维护系统级配置项、公开参数与运行策略（管理员）。',
    raw: configurationsRaw,
  },
  {
    key: 'users',
    group: 'system',
    order: 3,
    title: '用户管理',
    summary: '管理账号、角色与页面权限映射（管理员）。',
    raw: usersRaw,
  },
  {
    key: 'faq',
    group: 'appendix',
    order: 1,
    title: '常见问题',
    summary: '汇总上线后的高频问答与排错建议。',
    raw: faqRaw,
  },
  {
    key: 'changelog',
    group: 'appendix',
    order: 2,
    title: '版本变更记录',
    summary: '记录平台版本迭代内容，便于发布说明与回溯。',
    raw: changelogRaw,
  },
]

export const DOC_MAP = DOCS.reduce((acc, doc) => {
  acc[doc.key] = doc
  return acc
}, {})

export function getDocGroups() {
  return DOC_GROUPS
    .map((group) => ({
      ...group,
      docs: DOCS.filter((doc) => doc.group === group.key).sort((a, b) => a.order - b.order),
    }))
    .filter((group) => group.docs.length > 0)
    .sort((a, b) => a.order - b.order)
}
