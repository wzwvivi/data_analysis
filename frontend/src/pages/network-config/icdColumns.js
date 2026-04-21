// ──────────────────────────────────────────────────────────────────────
// ICD 6.0.x 原表头常量（草稿编辑器 / 已发布版本只读查看 共享）
//
// - DIRECTION_TABS / ICD_COLUMN_SETS 对齐 ICD 6.0.2 Excel。
// - 编辑场景会额外补「协议族（平台扩展）」「字段详情」「操作」等列，在各自页面内本地拼接。
// - 过滤时把列中出现过的非空值聚合成 Ant Design filters 选项。
// ──────────────────────────────────────────────────────────────────────

export const DIRECTION_TABS = [
  { key: 'uplink', label: '上行', icon: '↑' },
  { key: 'downlink', label: '下行', icon: '↓' },
  { key: 'network', label: '网络交互', icon: '⇄' },
]

export const ICD_COLUMN_SETS = {
  uplink: [
    { title: '消息编号',       dataIndex: 'message_id',          width: 110 },
    { title: '上网设备消息名称', dataIndex: 'message_name',        width: 210 },
    { title: '消息源设备名称',   dataIndex: 'source_device',       width: 150 },
    { title: '消息源端接口编号', dataIndex: 'source_interface_id', width: 130 },
    { title: 'UDP端口',        dataIndex: 'port_number',         width: 100, inputType: 'number', fixed: 'left', sort: true },
    { title: '组播组IP',        dataIndex: 'multicast_ip',        width: 140 },
    { title: 'DIU编号',        dataIndex: 'diu_id',              width: 100 },
    { title: '消息周期',        dataIndex: 'period_ms',           width: 100, inputType: 'number' },
    { title: '备注',           dataIndex: 'description',         width: 200, ellipsis: true },
    { title: 'PortID',         dataIndex: 'port_id_label',       width: 100 },
  ],
  downlink: [
    { title: '消息编号',             dataIndex: 'message_id',          width: 110 },
    { title: '待转换TSN设备消息名称', dataIndex: 'message_name',        width: 220 },
    { title: '待转换TSN源端',         dataIndex: 'source_device',       width: 150 },
    { title: 'DataSet目的端设备名称', dataIndex: 'target_device',       width: 170 },
    { title: 'DataSet传递路径',       dataIndex: 'dataset_path',        width: 150 },
    { title: 'DIU编号集合',           dataIndex: 'diu_id_set',          width: 120 },
    { title: 'DIU消息接收形式',       dataIndex: 'diu_recv_mode',       width: 140 },
    { title: 'TSN消息源端IP',         dataIndex: 'tsn_source_ip',       width: 140 },
    { title: '承接转换的DIU IP',      dataIndex: 'diu_ip',              width: 140 },
    { title: 'UDP端口',              dataIndex: 'port_number',         width: 100, inputType: 'number', fixed: 'left', sort: true },
    { title: '组播组IP',              dataIndex: 'multicast_ip',        width: 140 },
    { title: '消息周期',              dataIndex: 'period_ms',           width: 100, inputType: 'number' },
    { title: '备注',                 dataIndex: 'description',         width: 200, ellipsis: true },
    { title: '数据实际路径',          dataIndex: 'data_real_path',      width: 140 },
    { title: 'DIU编号',              dataIndex: 'diu_id',              width: 100 },
    { title: '最终接收端设备',        dataIndex: 'final_recv_device',   width: 150 },
  ],
  network: [
    { title: '消息编号',       dataIndex: 'message_id',          width: 110 },
    { title: '上网设备消息名称', dataIndex: 'message_name',        width: 210 },
    { title: '消息源设备名称',   dataIndex: 'source_device',       width: 150 },
    { title: '消息源端接口编号', dataIndex: 'source_interface_id', width: 130 },
    { title: 'UDP端口',        dataIndex: 'port_number',         width: 100, inputType: 'number', fixed: 'left', sort: true },
    { title: '组播组IP',        dataIndex: 'multicast_ip',        width: 140 },
    { title: 'DIU编号',        dataIndex: 'diu_id',              width: 100 },
    { title: '消息周期',        dataIndex: 'period_ms',           width: 100, inputType: 'number' },
    { title: '备注',           dataIndex: 'description',         width: 200, ellipsis: true },
    { title: 'PortID',         dataIndex: 'port_id_label',       width: 100 },
    { title: '消息目的设备',   dataIndex: 'target_device',       width: 150 },
  ],
}

/** 把某列出现过的所有非空值聚合成 Ant Design filters 选项 */
export function buildFilters(rows, key) {
  const set = new Set()
  for (const r of rows || []) {
    const v = r?.[key]
    if (v !== null && v !== undefined && String(v) !== '') {
      set.add(String(v))
    }
  }
  return Array.from(set)
    .sort((a, b) => a.localeCompare(b, 'zh-Hans', { numeric: true }))
    .map((v) => ({ text: v, value: v }))
}

/** 全局搜索（所有 ICD 字段 + 平台扩展的协议族） */
export function matchPortKeyword(p, keyword) {
  const kw = (keyword || '').trim().toLowerCase()
  if (!kw) return true
  const bag = [
    p.port_number, p.message_name, p.source_device, p.target_device,
    p.multicast_ip, p.description, p.protocol_family, p.protocol_family_resolved,
    p.port_role,
    p.message_id, p.source_interface_id, p.port_id_label, p.diu_id, p.diu_id_set,
    p.diu_recv_mode, p.tsn_source_ip, p.diu_ip, p.dataset_path,
    p.data_real_path, p.final_recv_device,
  ].map((v) => (v == null ? '' : String(v).toLowerCase())).join(' ')
  return bag.includes(kw)
}
