import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import {
  Card, Table, Tabs, Tag, Button, Space, message, Statistic, Row, Col,
  Spin, Empty, Select, Radio, Checkbox, Alert, Progress, InputNumber, Divider, Segmented,
  Modal, Collapse, Tooltip,
} from 'antd'
import {
  DownloadOutlined, LineChartOutlined, ReloadOutlined,
  DatabaseOutlined, ApiOutlined, RocketOutlined,
  DesktopOutlined, FilterOutlined,
  BarChartOutlined, SwapOutlined, WarningOutlined,
  SettingOutlined, PushpinOutlined, AppstoreOutlined,
  PlusOutlined, DeleteOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import * as echarts from 'echarts'
import { parseApi, protocolApi } from '../services/api'
import dayjs from 'dayjs'

const { Option } = Select

const CHART_COLORS = [
  '#8b5cf6', '#a78bfa', '#5fd068', '#d4a843', '#f05050',
  '#14b8a6', '#d4a843', '#f05050', '#6366f1', '#84cc16'
]

const SKIP_FIELDS = new Set([
  'timestamp', 'raw_data', 'packet_size', 'ssm_status',
  'work_status_raw', 'nav_integrity_raw', 'smode_addr_low_raw',
  'smode_addr_high_raw', 'intruder_nac_raw', 'intruder_nic_raw',
  'intruder_status_raw', 'intruder_ts1_raw', 'intruder_ts2_raw',
  'intruder_flt1_raw', 'intruder_flt2_raw', 'intruder_flt3_raw',
  'intruder_flt4_raw', 'intruder_lat_h_raw', 'intruder_lat_l_raw',
  'intruder_lon_h_raw', 'intruder_lon_l_raw', 'intruder_addr_h_raw',
  'intruder_addr_l_raw', 'start_stop_raw',
])

const FIELD_EXACT_CN = {
  timestamp: '时间戳（秒）',
  beijingdatetime: '北京时间',
  beijing_time: '北京时间',
  packet_size: '报文长度',
  source_port: '源端口',
  can_id_hex: 'CAN 标识',
  msg_type: '消息类型',
  msg_name: '消息名称',
  pack_id: '电池包编号',
  frame_count: '帧计数',
  device_id: '设备编号',
  device_name_enum: '设备名称',
  unit_id: '设备单元号',
  unit_id_cn: '设备单元中文标识',
  adru_id: 'ADRU 单元号',
  adru_id_cn: 'ADRU 单元中文标识',
  ra_id: '无线电高度表单元号',
  ra_id_cn: '无线电高度表单元中文标识',
  scu_id: '转弯控制单元号',
  scu_id_cn: '转弯控制单元中文标识',
  sdi: 'SDI 源/目的标识',
  ssm: 'SSM 状态矩阵',
  ssm_enum: 'SSM 中文状态',
  parity: '奇偶校验',
  latitude: '纬度',
  longitude: '经度',
  altitude: '高度',
  heading: '航向',
  pitch: '俯仰角',
  roll: '横滚角',
  ground_speed: '地速',
  true_heading: '真航向',
  track_angle: '航迹角',
  vertical_velocity: '垂直速度',
  north_velocity: '北向速度',
  east_velocity: '东向速度',
  geometric_height: '几何高度',
  sw_version: '软件版本',
  hw_version: '硬件版本',
  crc_valid: 'CRC校验有效',
  work_mode: '工作模式',
  nav_mode: '导航模式',
  align_status: '对准状态',
  align_mode: '对准模式',
  sat_source: '卫导来源',
  utc_time: 'UTC 时间',
  utc_date: 'UTC 日期',
  hpl: '水平保护级',
  vpl: '垂直保护级',
  hdop: '水平精度因子',
  vdop: '垂直精度因子',
  hfom: '水平估计误差',
  vfom: '垂直估计误差',
  main_fcc: '主飞控',
  source_fcc: '源飞控',
  fcc_vote_bits: '飞控表决位',
  irs_channel_name: 'IRS通道',
}

const FIELD_TOKEN_CN = {
  lh: '左',
  rh: '右',
  nlg: '前起落架',
  mlg: '主起落架',
  lg: '起落架',
  lgcu: '起落架控制单元',
  wow: '空重信号',
  woffw: '空重/离地信号',
  dnlk: '下锁',
  dnlock: '下锁',
  uplk: '上锁',
  uplock: '上锁',
  prox: '接近开关',
  mon: '监控',
  cons: '综合',
  sys: '系统',
  fault: '故障',
  status: '状态',
  cmd: '指令',
  retract: '收起',
  extend: '放下',
  auto: '自动',
  flight: '飞行',
  mode: '模式',
  lock: '锁定',
  down: '放下',
  up: '收起',
  work: '工作',
  state: '状态',
  steer: '转弯',
  brake: '刹车',
  park: '停留',
  control: '控制',
  zero: '调零',
  pedal: '脚蹬',
  release: '释放',
  sw: '软件',
  version: '版本',
  major: '主版本',
  minor: '子版本',
  check: '检测',
  valid: '有效',
  invalid: '无效',
  bit: '自检位',
  maint: '维护',
  word: '字',
  spare: '保留位',
  op: '反向/互补位',
  label: '标签',
  voted: '表决',
  src: '源',
  abs: '绝对',
  alt: '高度',
  qnh: 'QNH',
  qfe: 'QFE',
  mach: '马赫数',
  ias: '指示空速',
  cas: '校准空速',
  tas: '真空速',
  aoa: '迎角',
  aos: '侧滑角',
  speed: '速度',
  wheel: '轮',
  tire: '轮胎',
  pressure: '压力',
  temp: '温度',
  force: '力',
  feedback: '反馈',
  throttle: '油门',
  handwheel: '手轮',
  angle: '角度',
  offset: '偏移',
  fail: '失效',
  left: '左',
  right: '右',
  inside: '内侧',
  outside: '外侧',
  main: '主',
  copilot: '副驾驶',
  avg: '平均',
  total: '总',
  pwr: '功率',
  vlt: '电压',
  volt: '电压',
  crnt: '电流',
  curr: '电流',
  current: '电流',
  soc: '荷电状态',
  soe: '能量状态',
  energy: '能量',
  charge: '充电',
  chrg: '充电',
  dschrg: '放电',
  bus: '母线',
  hv: '高压',
  lv: '低压',
  isol: '绝缘',
  stat: '状态',
  type: '类型',
  code: '代码',
  serial: '序列号',
  number: '编号',
  num: '编号',
  count: '计数',
  time: '时间',
  date: '日期',
  msg: '消息',
  can: 'CAN',
  id: 'ID',
  source: '源端口',
  port: '端口',
  frame: '帧',
  sdi: 'SDI',
  ssm: 'SSM',
  parity: '奇偶校验',
  enum: '文本说明',
  irs: '惯导',
  rtk: 'RTK',
  gps: 'GPS',
  utc: 'UTC',
  gyro: '陀螺',
  accelerometer: '加速度计',
  acceleration: '加速度',
  angular: '角',
  velocity: '速度',
  heading: '航向',
  pitch: '俯仰',
  roll: '横滚',
  latitude: '纬度',
  longitude: '经度',
  geometric: '几何',
  height: '高度',
  hpl: '水平保护级',
  vpl: '垂直保护级',
  hdop: '水平精度因子',
  vdop: '垂直精度因子',
  hfom: '水平估计误差',
  vfom: '垂直估计误差',
  sat: '卫星',
  gnss: 'GNSS',
  fix: '定位',
  pos: '位置',
  position: '位置',
  locate: '定位',
  scene: '场景',
  phase: '阶段',
  runway: '跑道',
  aircraft: '飞机',
  weight: '重量',
  leg: '航段',
  fms: '飞管',
  fcc: '飞控',
  rwy: '跑道',
  pbit: '上电自检',
  cbit: '周期自检',
  adc: '大气数据计算机',
  adru: 'ADRU',
  ra: '无线电高度表',
  bms: 'BMS',
  bmu: 'BMU',
  cmu: 'CMU',
  pcb: '电路板',
  hvil: '高压互锁',
  supl: '供电',
  clnt: '冷却液',
  cnctr: '接触器',
  ckt: '电路',
  opn: '开路',
  short: '短路',
  over: '过高',
  under: '过低',
  overtemp: '过温',
  overvoltage: '过压',
  undervoltage: '欠压',
  timeout: '超时',
}

const ASCII_ONLY_RE = /^[\x00-\x7F]+$/
const COMPACT_TOKEN_RE = /^[a-z0-9]+$/
const COMPACT_SEGMENT_CN = {
  bms: 'BMS',
  bmu: 'BMU',
  cmu: 'CMU',
  can: 'CAN',
  msg: '消息',
  id: 'ID',
  stat: '状态',
  status: '状态',
  valid: '有效',
  invalid: '无效',
  inv: '无效',
  flt: '故障',
  fault: '故障',
  fail: '失效',
  ckt: '电路',
  circ: '回路',
  cnctr: '接触器',
  pwr: '电源',
  supl: '供电',
  supply: '供电',
  volt: '电压',
  vlt: '电压',
  crnt: '电流',
  curr: '电流',
  temp: '温度',
  tmpt: '温度',
  cell: '电芯',
  pack: '电池包',
  soc: '荷电状态',
  soe: '能量状态',
  chrg: '充电',
  dschrg: '放电',
  hv: '高压',
  lv: '低压',
  bus: '母线',
  hi: '高',
  lo: '低',
  max: '最大',
  min: '最小',
  avg: '平均',
  num: '编号',
  cnt: '计数',
  cntctr: '接触器',
  ext: '外部',
  int: '内部',
  clnt: '冷却液',
  rcpt: '充电口',
  station: '站',
  aux: '辅助',
  brnch: '支路',
  branch: '支路',
  can1: 'CAN1',
  can2: 'CAN2',
  busoff: '总线关闭',
  timeout: '超时',
  overtemp: '过温',
  overvolt: '过压',
  undervolt: '欠压',
  opn: '开路',
  short: '短路',
  cktopn: '电路开路',
  cktstg: '电路短接',
  pcb: '电路板',
  hvil: '高压互锁',
  dcdc: 'DCDC',
  kl15: 'KL15',
  fmc: '飞管计算机',
  fcc: '飞控计算机',
  irs: '惯导',
  rtk: 'RTK',
  gps: 'GPS',
  utc: 'UTC',
  hpl: '水平保护级',
  vpl: '垂直保护级',
  hdop: '水平精度因子',
  vdop: '垂直精度因子',
  hfom: '水平估计误差',
  vfom: '垂直估计误差',
  aoa: '迎角',
  aos: '侧滑角',
  ias: '指示空速',
  cas: '校准空速',
  tas: '真空速',
  qnh: 'QNH',
  qfe: 'QFE',
  pbit: '上电自检',
  cbit: '周期自检',
  sdi: 'SDI',
  ssm: 'SSM',
  crc: 'CRC',
  rwy: '跑道',
  tempdiff: '温差',
  rem: '剩余',
  enrgy: '能量',
  pwrup: '上电',
  wakeup: '唤醒',
  pln: '飞机',
  loc: '位置',
  info: '信息',
  over: '过高',
  under: '过低',
}
const COMPACT_SEGMENT_KEYS = Object.keys(COMPACT_SEGMENT_CN).sort((a, b) => b.length - a.length)

function splitFieldParts(coreName) {
  if (!coreName) return []
  const base = String(coreName)
    .replace(/\./g, '_')
    .replace(/([a-z])([A-Z])/g, '$1_$2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1_$2')
    .toLowerCase()
  return base.split('_').filter(Boolean)
}

function translateCompactToken(token) {
  if (!token || !COMPACT_TOKEN_RE.test(token)) return null
  const out = []
  let i = 0
  let mappedCount = 0
  while (i < token.length) {
    let hit = null
    for (const key of COMPACT_SEGMENT_KEYS) {
      if (token.startsWith(key, i)) {
        hit = key
        break
      }
    }
    if (hit) {
      out.push(COMPACT_SEGMENT_CN[hit])
      mappedCount += 1
      i += hit.length
      continue
    }
    if (/\d/.test(token[i])) {
      let j = i + 1
      while (j < token.length && /\d/.test(token[j])) j += 1
      out.push(token.slice(i, j))
      i = j
      continue
    }
    return null
  }
  if (mappedCount === 0) return null
  return out.join(' ')
}

function isLikelyMeaningfulChinese(text) {
  if (!text) return false
  const s = String(text).trim()
  if (!s) return false
  return /[\u4e00-\u9fa5]/.test(s)
}

function binarySearchNearest(data, targetTime) {
  if (!data || data.length === 0) return null
  let lo = 0, hi = data.length - 1
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (data[mid][0] < targetTime) lo = mid + 1
    else hi = mid
  }
  if (lo > 0 && Math.abs(data[lo - 1][0] - targetTime) < Math.abs(data[lo][0] - targetTime)) lo--
  return data[lo]
}

function getResultKey(result) {
  if (result.parser_profile_id) {
    return `${result.port_number}_${result.parser_profile_id}`
  }
  return String(result.port_number)
}

function getResultLabel(result) {
  let label = `${result.port_number}`
  if (result.source_device) label += ` / ${result.source_device}`
  if (result.parser_profile_name) label += ` / ${result.parser_profile_name}`
  return label
}

function buildChineseHintFromField(fieldName) {
  if (!fieldName) return '字段含义'
  const lower = String(fieldName).toLowerCase()
  const noLabelPrefix = lower.includes('.') ? lower.split('.').slice(1).join('.') : lower
  const core = noLabelPrefix.replace(/\./g, '_').replace(/_enum$/, '')
  if (FIELD_EXACT_CN[core]) return FIELD_EXACT_CN[core]

  const parts = splitFieldParts(core)
  if (parts.length === 0) return '字段含义'

  const translated = parts.map((p) => {
    if (/^\d+$/.test(p)) return p
    const compact = translateCompactToken(p)
    if (compact) return compact
    return FIELD_TOKEN_CN[p] || (ASCII_ONLY_RE.test(p) ? p.toUpperCase() : p)
  })
  const joined = translated.join(' ')
  // 若拆分后依然全是英文/缩写，给出中文提示，避免“复制字段名”体验
  if (!/[\u4e00-\u9fa5]/.test(joined)) {
    return '字段中文释义待补充'
  }
  return joined
}

function ResultPage() {
  const { taskId } = useParams()
  const location = useLocation()
  const [task, setTask] = useState(null)
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(true)
  const [activeResult, setActiveResult] = useState(null)
  const [activeFieldDescMap, setActiveFieldDescMap] = useState({})
  const [portData, setPortData] = useState([])
  const [portColumns, setPortColumns] = useState([])
  const [allColumnNames, setAllColumnNames] = useState([])
  const [dataLoading, setDataLoading] = useState(false)
  const [pagination, setPagination] = useState({
    current: 1, pageSize: 100, total: 0,
  })
  const [selectedDevice, setSelectedDevice] = useState(null)
  const [selectedParser, setSelectedParser] = useState(null)
  const [labelFilterValue, setLabelFilterValue] = useState(undefined)

  const [mainTab, setMainTab] = useState('table')

  // ---- Column manager ----
  const [colManagerOpen, setColManagerOpen] = useState(false)
  const [hiddenColumns, setHiddenColumns] = useState(new Set())
  const [pinnedColumns, setPinnedColumns] = useState(new Set(['timestamp', 'BeijingDateTime']))

  // ---- Batch export ----
  const [batchExportOpen, setBatchExportOpen] = useState(false)
  const [batchExportFormat, setBatchExportFormat] = useState('csv')
  const [batchExportSelected, setBatchExportSelected] = useState([])
  const [batchExportIncludeText, setBatchExportIncludeText] = useState(true)
  const [batchExporting, setBatchExporting] = useState(false)
  const [singleExportIncludeText, setSingleExportIncludeText] = useState(true)

  // ---- Port anomaly analysis ----
  const [anomalyDefaultsLoading, setAnomalyDefaultsLoading] = useState(false)
  const [anomalyNumericFields, setAnomalyNumericFields] = useState([])
  const [anomalyDefaultThresholds, setAnomalyDefaultThresholds] = useState({})
  const [anomalyThresholdEdits, setAnomalyThresholdEdits] = useState({})
  const [anomalySelectedFields, setAnomalySelectedFields] = useState([])
  const [anomalyAnalyzing, setAnomalyAnalyzing] = useState(false)
  const [anomalyResult, setAnomalyResult] = useState(null)
  const [anomalyStuckFrames, setAnomalyStuckFrames] = useState(5)
  const [anomalyJumpFieldFilter, setAnomalyJumpFieldFilter] = useState(undefined)
  const [anomalyStuckFieldFilter, setAnomalyStuckFieldFilter] = useState(undefined)

  // ---- Compare analysis state ----
  const [compareMode, setCompareMode] = useState('single_port')
  // single_port mode
  const [spActiveResult, setSpActiveResult] = useState(null)
  const [spAvailableFields, setSpAvailableFields] = useState([])
  const [spSelectedFields, setSpSelectedFields] = useState([])
  const [spChartData, setSpChartData] = useState({})
  const [spPrimaryYField, setSpPrimaryYField] = useState(null)
  const [spChartLayout, setSpChartLayout] = useState('overlay')
  const [spGridCols, setSpGridCols] = useState(2)
  const [spGridPanels, setSpGridPanels] = useState([])
  // cross_port mode
  const [cpSelectedResults, setCpSelectedResults] = useState([])
  const [cpCommonFields, setCpCommonFields] = useState([])
  const [cpSelectedCommonFields, setCpSelectedCommonFields] = useState([])
  const [cpSelectedUniqueFields, setCpSelectedUniqueFields] = useState({})
  const [cpChartData, setCpChartData] = useState({})
  const [cpFieldsPerResult, setCpFieldsPerResult] = useState({})
  const [cpSkippedSeries, setCpSkippedSeries] = useState([])
  const [cpPrimaryYSeries, setCpPrimaryYSeries] = useState(null)
  const [cpChartLayout, setCpChartLayout] = useState('overlay')
  const [cpGridCols, setCpGridCols] = useState(2)
  // shared
  const [chartLoading, setChartLoading] = useState(false)

  const cpUniqueFieldsPerResult = useMemo(() => {
    const map = {}
    for (const [key, fields] of Object.entries(cpFieldsPerResult)) {
      map[key] = fields.filter(f => !cpCommonFields.includes(f))
    }
    return map
  }, [cpFieldsPerResult, cpCommonFields])

  const cpHasSelection = useMemo(() => {
    return cpSelectedCommonFields.length > 0 ||
      Object.values(cpSelectedUniqueFields).some(arr => arr.length > 0)
  }, [cpSelectedCommonFields, cpSelectedUniqueFields])

  const { deviceList, parserList } = useMemo(() => {
    const devices = new Set()
    const parsers = new Map()
    results.forEach(r => {
      if (r.source_device) devices.add(r.source_device)
      if (r.parser_profile_id && r.parser_profile_name)
        parsers.set(r.parser_profile_id, r.parser_profile_name)
    })
    return {
      deviceList: Array.from(devices).sort(),
      parserList: Array.from(parsers.entries()).map(([id, name]) => ({ id, name }))
    }
  }, [results])

  const filteredResults = useMemo(() => {
    return results.filter(r => {
      if (selectedDevice && r.source_device !== selectedDevice) return false
      if (selectedParser && r.parser_profile_id !== selectedParser) return false
      return true
    })
  }, [results, selectedDevice, selectedParser])

  const labelFilterOptions = useMemo(() => {
    const hasCanIdCol = allColumnNames.some(c => /^can[_\s-]*id/i.test(c))
    if (hasCanIdCol) {
      const idCol = allColumnNames.find(c => c === 'can_id_hex') || allColumnNames.find(c => /^can[_\s-]*id/i.test(c))
      if (!idCol) return []
      const unique = [...new Set(portData.map(r => r[idCol]).filter(Boolean).map(String))]
      unique.sort()
      return unique.map(v => ({ label: v, value: v }))
    }
    const labelNums = new Set()
    allColumnNames.forEach(c => {
      const m = c.match(/^label_(\d+)\./i)
      if (m) labelNums.add(m[1])
    })
    if (labelNums.size === 0) return []
    const sorted = [...labelNums].sort((a, b) => parseInt(a, 10) - parseInt(b, 10))
    return sorted.map(n => ({ label: `Label ${n}`, value: n }))
  }, [allColumnNames, portData])

  const filteredPortData = useMemo(() => {
    if (!labelFilterValue) return portData
    const hasCanIdCol = allColumnNames.some(c => /^can[_\s-]*id/i.test(c))
    if (!hasCanIdCol) return portData
    const idCol = allColumnNames.find(c => c === 'can_id_hex') || allColumnNames.find(c => /^can[_\s-]*id/i.test(c))
    if (!idCol) return portData
    return portData.filter(row => String(row[idCol] ?? '') === labelFilterValue)
  }, [portData, labelFilterValue, allColumnNames])

  const displayColumnNames = useMemo(() => {
    const visibleCols = allColumnNames.filter(c => !hiddenColumns.has(c))
    if (!labelFilterValue) {
      const pinned = visibleCols.filter(c => pinnedColumns.has(c))
      const unpinned = visibleCols.filter(c => !pinnedColumns.has(c))
      return [...pinned, ...unpinned]
    }
    const hasCanIdCol = allColumnNames.some(c => /^can[_\s-]*id/i.test(c))
    if (hasCanIdCol) {
      const pinned = visibleCols.filter(c => pinnedColumns.has(c))
      const unpinned = visibleCols.filter(c => !pinnedColumns.has(c))
      return [...pinned, ...unpinned]
    }
    const keepBase = new Set(['timestamp', 'BeijingDateTime'])
    const matched = visibleCols.filter(c => {
      if (keepBase.has(c)) return true
      const m = c.match(/^label_(\d+)\./i)
      return m && m[1] === labelFilterValue
    })
    const pinned = matched.filter(c => pinnedColumns.has(c))
    const unpinned = matched.filter(c => !pinnedColumns.has(c))
    return [...pinned, ...unpinned]
  }, [allColumnNames, hiddenColumns, pinnedColumns, labelFilterValue])

  useEffect(() => {
    if (activeResult) loadPortData()
  }, [activeResult, pagination.current, pagination.pageSize])

  useEffect(() => {
    const loadFieldDescriptions = async () => {
      if (!activeResult || !task?.protocol_version_id) {
        setActiveFieldDescMap({})
        return
      }
      try {
        const res = await protocolApi.getPortDetail(task.protocol_version_id, activeResult.port_number)
        const fields = res.data?.fields || []
        const map = {}
        fields.forEach((f) => {
          if (!f?.field_name || !f?.description) return
          const keyRaw = String(f.field_name).trim()
          const keyLower = keyRaw.toLowerCase()
          map[keyRaw] = String(f.description).trim()
          map[keyLower] = String(f.description).trim()
          const suffix = keyLower.includes('.') ? keyLower.split('.').slice(1).join('.') : keyLower
          map[suffix] = String(f.description).trim()
        })
        setActiveFieldDescMap(map)
      } catch {
        setActiveFieldDescMap({})
      }
    }
    loadFieldDescriptions()
  }, [activeResult, task?.protocol_version_id])

  useEffect(() => {
    setMainTab(location.pathname.endsWith('/analysis') ? 'analysis' : 'table')
  }, [location.pathname])

  useEffect(() => {
    if (allColumnNames.length === 0) return
    setPortColumns(displayColumnNames.map(buildColumnDef))
  }, [allColumnNames, displayColumnNames])

  // ======== Data loading ========

  const loadTask = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const res = await parseApi.getTask(taskId)
      setTask(res.data.task)
      setResults(res.data.results || [])
      if (res.data.results?.length > 0) {
        const first = res.data.results[0]
        setActiveResult(first)
      } else {
        setActiveResult(null)
      }
    } catch (err) {
      if (!silent) message.error('加载任务详情失败')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [taskId])

  useEffect(() => {
    loadTask(false)
  }, [taskId, loadTask])

  useEffect(() => {
    if (!task || (task.status !== 'pending' && task.status !== 'processing')) return undefined
    const id = setInterval(() => loadTask(true), 3000)
    return () => clearInterval(id)
  }, [task?.status, loadTask])

  const buildColumnDef = (col) => ({
    title: col, dataIndex: col, key: col,
    width: col === 'timestamp' ? 160 : col === '核对' ? 560 : 120,
    fixed: pinnedColumns.has(col) ? 'left' : undefined,
    sorter: (a, b) => {
      const va = a[col], vb = b[col]
      if (va == null && vb == null) return 0
      if (va == null) return -1
      if (vb == null) return 1
      if (typeof va === 'number' && typeof vb === 'number') return va - vb
      return String(va).localeCompare(String(vb))
    },
    render: (value) => {
      if (col === 'timestamp') return <span className="mono">{value}</span>
      if (col === '核对') {
        return (
          <span className="mono" style={{ whiteSpace: 'normal', wordBreak: 'break-word', display: 'block', maxWidth: 540, lineHeight: 1.45 }}>
            {value != null ? String(value) : ''}
          </span>
        )
      }
      if (typeof value === 'number') return <span className="mono">{value.toFixed(6)}</span>
      return <span className="mono">{value}</span>
    },
  })

  const loadPortData = async () => {
    if (!activeResult) return
    setDataLoading(true)
    try {
      const params = { page: pagination.current, page_size: pagination.pageSize }
      if (activeResult.parser_profile_id)
        params.parser_id = activeResult.parser_profile_id
      const res = await parseApi.getData(taskId, activeResult.port_number, params)
      setPortData(res.data.data || [])
      setPagination(prev => ({ ...prev, total: res.data.total_records }))
      const rawCols = res.data.columns || []
      setAllColumnNames(rawCols)
      // columns will be recomputed by the displayColumnNames effect
    } catch (err) {
      message.error('加载数据失败')
    } finally {
      setDataLoading(false)
    }
  }

  const handleExport = async (format) => {
    if (!activeResult) {
      message.warning('请先选择一个端口')
      return
    }
    const hide = message.loading(`正在导出 ${format.toUpperCase()} ...`, 0)
    try {
      const params = { include_text_columns: singleExportIncludeText }
      if (activeResult.parser_profile_id) params.parser_id = activeResult.parser_profile_id
      console.log('[Export]', { taskId, port: activeResult.port_number, format, params })
      const res = await parseApi.exportData(taskId, activeResult.port_number, format, params)
      const blob = new Blob([res.data])
      if (blob.size === 0) {
        hide()
        message.error('导出文件为空，请检查数据')
        return
      }
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      const suffix = activeResult.parser_profile_name ? `_${activeResult.parser_profile_name}` : ''
      link.setAttribute('download', `port_${activeResult.port_number}${suffix}.${format}`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
      hide()
      message.success('导出成功')
    } catch (err) {
      hide()
      console.error('[Export Error]', err)
      let detail = err.message || '未知错误'
      if (err.response?.data instanceof Blob) {
        try {
          const text = await err.response.data.text()
          const json = JSON.parse(text)
          detail = json.detail || text
        } catch (_) {
          detail = `HTTP ${err.response?.status}`
        }
      } else if (err.response?.data?.detail) {
        detail = err.response.data.detail
      }
      message.error(`导出失败: ${detail}`)
    }
  }

  const handleBatchExportSubmit = async () => {
    if (batchExportSelected.length === 0) {
      message.warning('请至少选择一个端口')
      return
    }
    setBatchExporting(true)
    const hide = message.loading('正在批量导出，请稍候...', 0)
    try {
      if (batchExportFormat === 'csv') {
        let completed = 0
        for (const key of batchExportSelected) {
          const r = results.find(res => getResultKey(res) === key)
          if (!r) continue
          const params = { include_text_columns: batchExportIncludeText }
          if (r.parser_profile_id) params.parser_id = r.parser_profile_id
          const res2 = await parseApi.exportData(taskId, r.port_number, 'csv', params)
          const blob = new Blob([res2.data])
          if (blob.size > 0) {
            const url = window.URL.createObjectURL(blob)
            const link = document.createElement('a')
            link.href = url
            const suffix = r.parser_profile_name ? `_${r.parser_profile_name}` : ''
            link.setAttribute('download', `port_${r.port_number}${suffix}.csv`)
            document.body.appendChild(link)
            link.click()
            link.remove()
            window.URL.revokeObjectURL(url)
          }
          completed++
        }
        hide()
        message.success(`已导出 ${completed} 个端口的 CSV 文件`)
      } else {
        const selectedResults = batchExportSelected.map(key => results.find(res => getResultKey(res) === key)).filter(Boolean)
        const ports = selectedResults.map(r => r.port_number)
        const parserIds = selectedResults.map(r => r.parser_profile_id ? String(r.parser_profile_id) : '')
        const res = await parseApi.exportBatch(taskId, ports, parserIds, batchExportIncludeText)
        const url = window.URL.createObjectURL(new Blob([res.data]))
        const link = document.createElement('a')
        link.href = url
        link.setAttribute('download', `task_${taskId}_batch.zip`)
        document.body.appendChild(link)
        link.click()
        link.remove()
        window.URL.revokeObjectURL(url)
        hide()
        message.success(`已导出 ${ports.length} 个端口到 ZIP`)
      }
      setBatchExportOpen(false)
    } catch (err) {
      hide()
      let detail = err.message || '未知错误'
      if (err.response?.data instanceof Blob) {
        try { const text = await err.response.data.text(); const json = JSON.parse(text); detail = json.detail || text } catch (_) { detail = `HTTP ${err.response?.status}` }
      } else if (err.response?.data?.detail) { detail = err.response.data.detail }
      message.error(`批量导出失败: ${detail}`)
    } finally {
      setBatchExporting(false)
    }
  }

  const handleDeviceFilter = (value) => {
    setSelectedDevice(value)
    const newFiltered = results.filter(r => {
      if (value && r.source_device !== value) return false
      if (selectedParser && r.parser_profile_id !== selectedParser) return false
      return true
    })
    if (newFiltered.length > 0) {
      setActiveResult(newFiltered[0])
    }
  }

  const handleParserFilter = (value) => {
    setSelectedParser(value)
    const newFiltered = results.filter(r => {
      if (selectedDevice && r.source_device !== selectedDevice) return false
      if (value && r.parser_profile_id !== value) return false
      return true
    })
    if (newFiltered.length > 0) {
      setActiveResult(newFiltered[0])
    }
  }

  const handleLabelFilter = (value) => {
    setLabelFilterValue(value)
    setPagination(prev => ({ ...prev, current: 1 }))
  }

  const loadAnomalyDefaults = useCallback(async () => {
    if (!activeResult || task?.status !== 'completed') return
    setAnomalyDefaultsLoading(true)
    try {
      const params = {}
      if (activeResult.parser_profile_id) params.parser_id = activeResult.parser_profile_id
      const res = await parseApi.getAnomalyDefaults(taskId, activeResult.port_number, params)
      const nf = res.data.numeric_fields || []
      setAnomalyNumericFields(nf)
      const defMap = res.data.default_jump_threshold_pct || {}
      setAnomalyDefaultThresholds(defMap)
      setAnomalyStuckFrames(res.data.stuck_consecutive_frames ?? 5)
      const edits = {}
      nf.forEach((f) => { edits[f] = defMap[f] ?? 5 })
      setAnomalyThresholdEdits(edits)
      setAnomalySelectedFields([...nf])
      setAnomalyResult(null)
      setAnomalyJumpFieldFilter(undefined)
      setAnomalyStuckFieldFilter(undefined)
    } catch (err) {
      const d = err.response?.data?.detail
      message.error(typeof d === 'string' ? d : '加载异常分析字段失败')
      setAnomalyNumericFields([])
      setAnomalySelectedFields([])
      setAnomalyDefaultThresholds({})
      setAnomalyThresholdEdits({})
    } finally {
      setAnomalyDefaultsLoading(false)
    }
  }, [taskId, activeResult, task?.status])

  useEffect(() => {
    if (mainTab !== 'anomaly') return
    if (!activeResult || task?.status !== 'completed') return
    loadAnomalyDefaults()
  }, [mainTab, activeResult, task?.status, loadAnomalyDefaults])

  const runAnomalyAnalyze = async () => {
    if (!activeResult || anomalySelectedFields.length === 0) {
      message.warning('请至少选择一个数值字段')
      return
    }
    setAnomalyAnalyzing(true)
    try {
      const overrides = {}
      anomalySelectedFields.forEach((f) => {
        const v = anomalyThresholdEdits[f]
        if (v != null && v !== '') overrides[f] = Number(v)
      })
      const body = {
        fields: anomalySelectedFields,
        jump_threshold_pct_overrides: Object.keys(overrides).length ? overrides : undefined,
      }
      if (activeResult.parser_profile_id) body.parser_id = activeResult.parser_profile_id
      const res = await parseApi.analyzeAnomaly(taskId, activeResult.port_number, body)
      setAnomalyResult(res.data)
      if (res.data.message) message.info(res.data.message)
    } catch (err) {
      message.error(err.response?.data?.detail || '异常分析失败')
    } finally {
      setAnomalyAnalyzing(false)
    }
  }

  const onAnomalyFieldsChange = (checked) => {
    setAnomalySelectedFields(checked)
    setAnomalyThresholdEdits((prev) => {
      const next = { ...prev }
      checked.forEach((f) => {
        if (next[f] == null || next[f] === '') {
          next[f] = anomalyDefaultThresholds[f] ?? 5
        }
      })
      return next
    })
  }

  const filteredJumpEvents = useMemo(() => {
    if (!anomalyResult?.jump_events) return []
    if (!anomalyJumpFieldFilter) return anomalyResult.jump_events
    return anomalyResult.jump_events.filter((e) => e.field_name === anomalyJumpFieldFilter)
  }, [anomalyResult, anomalyJumpFieldFilter])

  const filteredStuckEvents = useMemo(() => {
    if (!anomalyResult?.stuck_events) return []
    if (!anomalyStuckFieldFilter) return anomalyResult.stuck_events
    return anomalyResult.stuck_events.filter((e) => e.field_name === anomalyStuckFieldFilter)
  }, [anomalyResult, anomalyStuckFieldFilter])

  const anomalyTimelineHints = useMemo(() => {
    if (!anomalyResult) return []
    const s = new Set()
    for (const e of anomalyResult.jump_events || []) {
      if (e.timestamp != null) s.add(e.timestamp)
    }
    for (const e of anomalyResult.stuck_events || []) {
      if (e.start_ts != null) s.add(e.start_ts)
      if (e.end_ts != null) s.add(e.end_ts)
    }
    return Array.from(s).sort((a, b) => a - b).slice(0, 40)
  }, [anomalyResult])

  const jumpFieldFilterOptions = useMemo(() => {
    if (!anomalyResult?.jump_events?.length) return []
    return [...new Set(anomalyResult.jump_events.map((e) => e.field_name))].sort()
  }, [anomalyResult])

  const stuckFieldFilterOptions = useMemo(() => {
    if (!anomalyResult?.stuck_events?.length) return []
    return [...new Set(anomalyResult.stuck_events.map((e) => e.field_name))].sort()
  }, [anomalyResult])

  // ======== Single-port multi-field analysis ========

  const loadSpFields = useCallback(async (result) => {
    if (!result) return
    try {
      const params = { page: 1, page_size: 1 }
      if (result.parser_profile_id) params.parser_id = result.parser_profile_id
      const res = await parseApi.getData(taskId, result.port_number, params)
      const cols = (res.data.columns || []).filter(c => !SKIP_FIELDS.has(c) && !c.endsWith('_enum'))
      setSpAvailableFields(cols)
    } catch {
      setSpAvailableFields([])
    }
  }, [taskId])

  useEffect(() => {
    if (compareMode === 'single_port' && spActiveResult) {
      setSpSelectedFields([])
      setSpChartData({})
      loadSpFields(spActiveResult)
    }
  }, [spActiveResult, compareMode, loadSpFields])

  const loadSpChartData = useCallback(async () => {
    if (!spActiveResult) return
    const panelFields = spGridPanels.flat()
    const allFields = [...new Set([...spSelectedFields, ...panelFields])]
    if (allFields.length === 0) return
    setChartLoading(true)
    try {
      const newData = {}
      await Promise.all(allFields.map(async (field) => {
        if (spChartData[field]) {
          newData[field] = spChartData[field]
          return
        }
        const params = { max_points: 2000 }
        if (spActiveResult.parser_profile_id) params.parser_id = spActiveResult.parser_profile_id
        const res = await parseApi.getTimeSeries(taskId, spActiveResult.port_number, field, params)
        newData[field] = {
          timestamps: res.data.timestamps,
          values: res.data.values,
          enumLabels: res.data.enum_labels || null,
        }
      }))
      setSpChartData(newData)
    } catch {
      message.error('加载时序数据失败')
    } finally {
      setChartLoading(false)
    }
  }, [taskId, spActiveResult, spSelectedFields, spGridPanels, spChartData])

  useEffect(() => {
    if (compareMode === 'single_port' && spSelectedFields.length > 0) {
      loadSpChartData()
    }
  }, [spSelectedFields])

  useEffect(() => {
    if (spPrimaryYField && !spSelectedFields.includes(spPrimaryYField)) {
      setSpPrimaryYField(null)
    }
  }, [spSelectedFields, spPrimaryYField])

  useEffect(() => {
    if (spChartLayout === 'grid' && spGridPanels.length === 0 && spSelectedFields.length > 0) {
      setSpGridPanels(spSelectedFields.map(f => [f]))
    }
  }, [spChartLayout, spSelectedFields, spGridPanels.length])

  useEffect(() => {
    if (compareMode !== 'single_port' || spChartLayout !== 'grid' || !spActiveResult) return
    const panelFields = spGridPanels.flat()
    const missing = panelFields.filter(f => f && !spChartData[f])
    if (missing.length > 0) {
      loadSpChartData()
    }
  }, [spGridPanels])

  const formatValueWithEnum = (val, enumLabel) => {
    if (val == null) return '-'
    if (enumLabel) return `${val} - ${enumLabel}`
    return typeof val === 'number' ? val.toFixed(6) : String(val)
  }

  const getFieldTooltipText = (fieldName) => {
    const keyRaw = String(fieldName)
    const keyLower = keyRaw.toLowerCase()
    const suffix = keyLower.includes('.') ? keyLower.split('.').slice(1).join('.') : keyLower
    const rawDesc = activeFieldDescMap[keyRaw] || activeFieldDescMap[keyLower] || activeFieldDescMap[suffix]
    const desc = rawDesc ? String(rawDesc).trim() : ''
    const normalizedField = keyLower.replace(/\s+/g, '')
    const normalizedDesc = desc.toLowerCase().replace(/\s+/g, '')
    const descLooksLikeFieldName = normalizedDesc === normalizedField || normalizedDesc === suffix
    if (!desc || descLooksLikeFieldName || !isLikelyMeaningfulChinese(desc)) {
      return buildChineseHintFromField(fieldName)
    }
    return desc.length > 64 ? `${desc.slice(0, 64)}...` : desc
  }

  const renderFieldWithTooltip = (fieldName) => (
    <Tooltip title={getFieldTooltipText(fieldName)}>
      <span className="mono" style={{ fontSize: 13, color: '#e4e4e7' }}>{fieldName}</span>
    </Tooltip>
  )

  const formatYAxisTick = (value) => {
    const n = Number(value)
    if (!Number.isFinite(n)) return String(value ?? '')
    const v3 = n.toFixed(3)
    return v3.endsWith('0') ? n.toFixed(2) : v3
  }

  const computeYRange = (seriesMap, targetKeys = null) => {
    const keys = targetKeys && targetKeys.length > 0 ? targetKeys : Object.keys(seriesMap)
    const vals = []
    keys.forEach((k) => {
      const points = seriesMap[k] || []
      points.forEach((p) => {
        const v = p?.[1]
        if (v != null && Number.isFinite(v)) vals.push(v)
      })
    })
    if (vals.length === 0) return { min: undefined, max: undefined }
    const lo = Math.min(...vals)
    const hi = Math.max(...vals)
    const span = hi - lo
    const pad = span > 0 ? span * 0.05 : Math.max(Math.abs(lo) * 0.05, 1)
    return { min: lo - pad, max: hi + pad }
  }

  const getSpFieldColor = useCallback((field) => {
    const idx = spAvailableFields.indexOf(field)
    return CHART_COLORS[(idx >= 0 ? idx : 0) % CHART_COLORS.length]
  }, [spAvailableFields])

  const getSpChartOption = () => {
    if (spSelectedFields.length === 0 || Object.keys(spChartData).length === 0) return {}
    const allSeriesData = {}
    const series = spSelectedFields.map((field) => {
      const data = spChartData[field]
      if (!data) return null
      const el = data.enumLabels
      const points = data.timestamps.map((t, i) => [t * 1000, data.values[i], el ? el[i] : null])
      allSeriesData[field] = points
      const color = getSpFieldColor(field)
      return {
        name: field, type: 'line', data: points,
        smooth: true, symbol: 'circle', symbolSize: 4, showSymbol: false,
        lineStyle: { width: 1.5, color }, itemStyle: { color },
        emphasis: { focus: 'series', lineStyle: { width: 3 }, itemStyle: { borderWidth: 2 } },
      }
    }).filter(Boolean)

    const seriesNames = series.map(s => s.name)

    const spDualAxis = seriesNames.length === 2
    let yAxis
    let chartSeries = series
    if (spDualAxis) {
      const leftName = seriesNames[0]
      const rightName = seriesNames[1]
      const leftRange = computeYRange(allSeriesData, [leftName])
      const rightRange = computeYRange(allSeriesData, [rightName])
      yAxis = [
        {
          type: 'value',
          name: leftName,
          min: leftRange.min,
          max: leftRange.max,
          position: 'left',
          axisLabel: { color: '#a1a1aa', formatter: formatYAxisTick },
          axisLine: { lineStyle: { color: '#27272a' } },
          splitLine: { lineStyle: { color: '#27272a' } },
        },
        {
          type: 'value',
          name: rightName,
          min: rightRange.min,
          max: rightRange.max,
          position: 'right',
          axisLabel: { color: '#a1a1aa', formatter: formatYAxisTick },
          axisLine: { lineStyle: { color: '#27272a' } },
          splitLine: { show: false },
        },
      ]
      chartSeries = series.map((s, idx) => ({ ...s, yAxisIndex: idx }))
    } else {
      const spUsePrimary = !!spPrimaryYField && seriesNames.includes(spPrimaryYField)
      const spRange = computeYRange(allSeriesData, spUsePrimary ? [spPrimaryYField] : null)
      yAxis = {
        type: 'value',
        name: spSelectedFields.length > 1 ? (spUsePrimary ? spPrimaryYField : '自动(全部字段)') : '',
        min: spRange.min,
        max: spRange.max,
        axisLabel: { color: '#a1a1aa', formatter: formatYAxisTick },
        axisLine: { lineStyle: { color: '#27272a' } },
        splitLine: { lineStyle: { color: '#27272a' } },
      }
    }

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis', backgroundColor: '#0f0f12', borderColor: '#27272a',
        textStyle: { color: '#e4e4e7' },
        axisPointer: {
          type: 'cross', snap: true,
          crossStyle: { color: '#a1a1aa' },
          lineStyle: { color: '#8b5cf6', type: 'dashed' },
          label: { backgroundColor: '#18181b', color: '#e4e4e7' },
        },
        formatter: (params) => {
          if (!params || params.length === 0) return ''
          const time = params[0].value[0]
          let html = `<div style="font-weight:600;margin-bottom:8px">${dayjs(time).format('HH:mm:ss.SSS')}</div>`
          const matched = new Set(params.map(p => p.seriesName))
          params.forEach(p => {
            const display = formatValueWithEnum(p.value[1], p.value[2])
            html += `<div style="display:flex;justify-content:space-between;gap:20px">
              <span>${p.marker} ${p.seriesName}</span>
              <span style="font-family:JetBrains Mono">${display}</span>
            </div>`
          })
          seriesNames.forEach((name) => {
            if (matched.has(name)) return
            const entry = binarySearchNearest(allSeriesData[name], time)
            const display = entry ? formatValueWithEnum(entry[1], entry[2]) : '-'
            const color = getSpFieldColor(name)
            html += `<div style="display:flex;justify-content:space-between;gap:20px">
              <span><span style="display:inline-block;margin-right:4px;border-radius:50%;width:10px;height:10px;background:${color}"></span> ${name}</span>
              <span style="font-family:JetBrains Mono">${display}</span>
            </div>`
          })
          return html
        }
      },
      legend: { data: spSelectedFields, textStyle: { color: '#a1a1aa' }, top: 10 },
      grid: { left: 60, right: 40, top: 60, bottom: 70 },
      xAxis: {
        type: 'time',
        axisPointer: { snap: true },
        axisLabel: { color: '#a1a1aa', formatter: (v) => dayjs(v).format('HH:mm:ss'), hideOverlap: true, rotate: 30 },
        axisLine: { lineStyle: { color: '#27272a' } }, splitLine: { show: false }
      },
      yAxis, series: chartSeries,
      dataZoom: [
        { type: 'inside', start: 0, end: 100 },
        { type: 'slider', start: 0, end: 100, height: 20, bottom: 10,
          borderColor: '#27272a', backgroundColor: '#0f0f12',
          fillerColor: 'rgba(139, 92, 246, 0.2)',
          handleStyle: { color: '#8b5cf6' }, textStyle: { color: '#a1a1aa' } }
      ],
      color: CHART_COLORS,
    }
  }

  const getSpPanelChartOption = (panelFields) => {
    const validFields = panelFields.filter(f => spChartData[f])
    if (validFields.length === 0) return {}

    const allSeriesData = {}
    const series = validFields.map((field) => {
      const data = spChartData[field]
      const el = data.enumLabels
      const points = data.timestamps.map((t, i) => [t * 1000, data.values[i], el ? el[i] : null])
      allSeriesData[field] = points
      const color = getSpFieldColor(field)
      return {
        name: field, type: 'line', data: points,
        smooth: true, symbol: 'circle', symbolSize: 4, showSymbol: false,
        lineStyle: { width: 1.5, color }, itemStyle: { color },
        emphasis: { lineStyle: { width: 3 }, itemStyle: { borderWidth: 2 } },
      }
    })

    const titleText = validFields.join(', ')

    let yAxis
    let chartSeries = series
    if (validFields.length === 2) {
      const leftRange = computeYRange(allSeriesData, [validFields[0]])
      const rightRange = computeYRange(allSeriesData, [validFields[1]])
      yAxis = [
        {
          type: 'value', name: validFields[0], min: leftRange.min, max: leftRange.max, position: 'left',
          nameTextStyle: { color: '#a1a1aa', fontSize: 10 },
          axisLabel: { color: '#a1a1aa', formatter: formatYAxisTick },
          axisLine: { lineStyle: { color: '#27272a' } },
          splitLine: { lineStyle: { color: '#27272a' } },
        },
        {
          type: 'value', name: validFields[1], min: rightRange.min, max: rightRange.max, position: 'right',
          nameTextStyle: { color: '#a1a1aa', fontSize: 10 },
          axisLabel: { color: '#a1a1aa', formatter: formatYAxisTick },
          axisLine: { lineStyle: { color: '#27272a' } },
          splitLine: { show: false },
        },
      ]
      chartSeries = series.map((s, idx) => ({ ...s, yAxisIndex: idx }))
    } else {
      const range = computeYRange(allSeriesData, null)
      yAxis = {
        type: 'value', min: range.min, max: range.max,
        axisLabel: { color: '#a1a1aa', formatter: formatYAxisTick },
        axisLine: { lineStyle: { color: '#27272a' } },
        splitLine: { lineStyle: { color: '#27272a' } },
      }
    }

    return {
      backgroundColor: 'transparent',
      title: { text: titleText, left: 'center', top: 4, textStyle: { color: '#e4e4e7', fontSize: 12, fontFamily: 'JetBrains Mono' } },
      tooltip: {
        trigger: 'axis', backgroundColor: '#0f0f12', borderColor: '#27272a',
        textStyle: { color: '#e4e4e7' },
        formatter: (params) => {
          if (!params || params.length === 0) return ''
          const time = params[0].value[0]
          let html = `<div style="font-weight:600;margin-bottom:4px">${dayjs(time).format('HH:mm:ss.SSS')}</div>`
          const matched = new Set(params.map(p => p.seriesName))
          params.forEach(p => {
            const display = formatValueWithEnum(p.value[1], p.value[2])
            html += `<div style="display:flex;justify-content:space-between;gap:16px"><span>${p.marker} ${p.seriesName}</span><span style="font-family:JetBrains Mono">${display}</span></div>`
          })
          validFields.forEach((name) => {
            if (matched.has(name)) return
            const entry = binarySearchNearest(allSeriesData[name], time)
            const display = entry ? formatValueWithEnum(entry[1], entry[2]) : '-'
            const color = getSpFieldColor(name)
            html += `<div style="display:flex;justify-content:space-between;gap:16px"><span><span style="display:inline-block;margin-right:4px;border-radius:50%;width:10px;height:10px;background:${color}"></span> ${name}</span><span style="font-family:JetBrains Mono">${display}</span></div>`
          })
          return html
        },
      },
      legend: validFields.length > 1 ? { data: validFields, textStyle: { color: '#a1a1aa', fontSize: 11 }, top: 20, itemWidth: 14, itemHeight: 8 } : undefined,
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: { left: 56, right: validFields.length === 2 ? 56 : 16, top: validFields.length > 1 ? 44 : 32, bottom: 56 },
      xAxis: {
        type: 'time',
        axisPointer: { snap: true, label: { show: false } },
        axisLabel: { color: '#a1a1aa', formatter: (v) => dayjs(v).format('HH:mm:ss'), hideOverlap: true, rotate: 30 },
        axisLine: { lineStyle: { color: '#27272a' } }, splitLine: { show: false },
      },
      yAxis,
      series: chartSeries,
      dataZoom: [
        { type: 'inside', start: 0, end: 100 },
        { type: 'slider', start: 0, end: 100, height: 16, bottom: 4,
          borderColor: '#27272a', backgroundColor: '#0f0f12',
          fillerColor: 'rgba(139, 92, 246, 0.2)',
          handleStyle: { color: '#8b5cf6' }, textStyle: { color: '#a1a1aa' } }
      ],
      color: CHART_COLORS,
    }
  }

  // ======== Cross-port multi-field analysis ========

  const getCpSeriesColor = useCallback((seriesName) => {
    let hash = 0
    for (let i = 0; i < seriesName.length; i++) hash = seriesName.charCodeAt(i) + ((hash << 5) - hash)
    return CHART_COLORS[Math.abs(hash) % CHART_COLORS.length]
  }, [])

  const loadCpFieldsForResults = useCallback(async (selectedKeys) => {
    const fieldsMap = {}
    await Promise.all(selectedKeys.map(async (key) => {
      const result = results.find(r => getResultKey(r) === key)
      if (!result) return
      try {
        const params = { page: 1, page_size: 1 }
        if (result.parser_profile_id) params.parser_id = result.parser_profile_id
        const res = await parseApi.getData(taskId, result.port_number, params)
        const cols = (res.data.columns || []).filter(c => !SKIP_FIELDS.has(c) && !c.endsWith('_enum'))
        fieldsMap[key] = cols
      } catch {
        fieldsMap[key] = []
      }
    }))
    setCpFieldsPerResult(fieldsMap)

    if (Object.keys(fieldsMap).length >= 2) {
      const arrays = Object.values(fieldsMap).filter(a => a.length > 0)
      if (arrays.length >= 2) {
        const intersection = arrays.reduce((acc, cur) =>
          acc.filter(f => cur.includes(f)))
        setCpCommonFields(intersection)
      } else {
        setCpCommonFields([])
      }
    } else {
      setCpCommonFields([])
    }
  }, [taskId, results])

  useEffect(() => {
    if (compareMode === 'cross_port' && cpSelectedResults.length >= 2) {
      setCpSelectedCommonFields([])
      setCpSelectedUniqueFields({})
      setCpChartData({})
      setCpSkippedSeries([])
      loadCpFieldsForResults(cpSelectedResults)
    } else {
      setCpCommonFields([])
      setCpFieldsPerResult({})
    }
  }, [cpSelectedResults, compareMode, loadCpFieldsForResults])

  const loadCpChartData = useCallback(async () => {
    if (cpSelectedResults.length < 2 || !cpHasSelection) return
    setChartLoading(true)
    const requests = []

    for (const field of cpSelectedCommonFields) {
      for (const key of cpSelectedResults) {
        const result = results.find(r => getResultKey(r) === key)
        if (!result) continue
        const fields = cpFieldsPerResult[key] || []
        if (!fields.includes(field)) continue
        requests.push({ key, field, result })
      }
    }

    for (const [key, fields] of Object.entries(cpSelectedUniqueFields)) {
      if (!cpSelectedResults.includes(key)) continue
      const result = results.find(r => getResultKey(r) === key)
      if (!result) continue
      for (const field of fields) {
        requests.push({ key, field, result })
      }
    }

    if (requests.length === 0) {
      setChartLoading(false)
      return
    }

    const newData = {}
    const skipped = []
    try {
      await Promise.all(requests.map(async ({ key, field, result }) => {
        const seriesKey = `${key}::${field}`
        try {
          const params = { max_points: 2000 }
          if (result.parser_profile_id) params.parser_id = result.parser_profile_id
          const res = await parseApi.getTimeSeries(taskId, result.port_number, field, params)
          const shortLabel = result.source_device
            ? `${result.port_number} / ${result.source_device}`
            : `${result.port_number}`
          newData[seriesKey] = {
            label: `${shortLabel} - ${field}`,
            timestamps: res.data.timestamps,
            values: res.data.values,
            enumLabels: res.data.enum_labels || null,
            fieldName: field,
            resultKey: key,
          }
        } catch {
          skipped.push(`${result.port_number} / ${field}`)
        }
      }))
      setCpChartData(newData)
      setCpSkippedSeries(skipped)
    } catch {
      message.error('加载对比数据失败')
    } finally {
      setChartLoading(false)
    }
  }, [taskId, cpSelectedCommonFields, cpSelectedUniqueFields, cpSelectedResults, results, cpFieldsPerResult, cpHasSelection])

  const getCpChartOption = () => {
    const keys = Object.keys(cpChartData)
    if (keys.length === 0) return {}

    const allSeriesData = {}
    const series = keys.map((key) => {
      const d = cpChartData[key]
      const el = d.enumLabels
      const points = d.timestamps.map((t, i) => [t * 1000, d.values[i], el ? el[i] : null])
      allSeriesData[d.label] = points
      const color = getCpSeriesColor(d.label)
      return {
        name: d.label, type: 'line', data: points,
        smooth: true, symbol: 'circle', symbolSize: 4, showSymbol: false,
        lineStyle: { width: 1.5, color }, itemStyle: { color },
        emphasis: { focus: 'series', lineStyle: { width: 3 }, itemStyle: { borderWidth: 2 } },
      }
    })

    const seriesNames = series.map(s => s.name)

    const cpDualAxis = seriesNames.length === 2
    let yAxis
    let chartSeries = series
    if (cpDualAxis) {
      const leftName = seriesNames[0]
      const rightName = seriesNames[1]
      const leftRange = computeYRange(allSeriesData, [leftName])
      const rightRange = computeYRange(allSeriesData, [rightName])
      yAxis = [
        {
          type: 'value',
          name: leftName,
          min: leftRange.min,
          max: leftRange.max,
          position: 'left',
          axisLabel: { color: '#a1a1aa', formatter: formatYAxisTick },
          axisLine: { lineStyle: { color: '#27272a' } },
          splitLine: { lineStyle: { color: '#27272a' } },
        },
        {
          type: 'value',
          name: rightName,
          min: rightRange.min,
          max: rightRange.max,
          position: 'right',
          axisLabel: { color: '#a1a1aa', formatter: formatYAxisTick },
          axisLine: { lineStyle: { color: '#27272a' } },
          splitLine: { show: false },
        },
      ]
      chartSeries = series.map((s, idx) => ({ ...s, yAxisIndex: idx }))
    } else {
      const cpUsePrimary = !!cpPrimaryYSeries && seriesNames.includes(cpPrimaryYSeries)
      const cpRange = computeYRange(allSeriesData, cpUsePrimary ? [cpPrimaryYSeries] : null)
      yAxis = {
        type: 'value',
        name: seriesNames.length > 1 ? (cpUsePrimary ? cpPrimaryYSeries : '自动(全部系列)') : '',
        min: cpRange.min,
        max: cpRange.max,
        axisLabel: { color: '#a1a1aa', formatter: formatYAxisTick },
        axisLine: { lineStyle: { color: '#27272a' } },
        splitLine: { lineStyle: { color: '#27272a' } },
      }
    }

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis', backgroundColor: '#0f0f12', borderColor: '#27272a',
        textStyle: { color: '#e4e4e7' },
        axisPointer: {
          type: 'cross', snap: true,
          crossStyle: { color: '#a1a1aa' },
          lineStyle: { color: '#8b5cf6', type: 'dashed' },
          label: { backgroundColor: '#18181b', color: '#e4e4e7' },
        },
        formatter: (params) => {
          if (!params || params.length === 0) return ''
          const time = params[0].value[0]
          let html = `<div style="font-weight:600;margin-bottom:8px">${dayjs(time).format('HH:mm:ss.SSS')}</div>`
          const matched = new Set(params.map(p => p.seriesName))
          params.forEach(p => {
            const display = formatValueWithEnum(p.value[1], p.value[2])
            html += `<div style="display:flex;justify-content:space-between;gap:20px">
              <span>${p.marker} ${p.seriesName}</span>
              <span style="font-family:JetBrains Mono">${display}</span>
            </div>`
          })
          seriesNames.forEach((name) => {
            if (matched.has(name)) return
            const entry = binarySearchNearest(allSeriesData[name], time)
            const display = entry ? formatValueWithEnum(entry[1], entry[2]) : '-'
            const color = getCpSeriesColor(name)
            html += `<div style="display:flex;justify-content:space-between;gap:20px">
              <span><span style="display:inline-block;margin-right:4px;border-radius:50%;width:10px;height:10px;background:${color}"></span> ${name}</span>
              <span style="font-family:JetBrains Mono">${display}</span>
            </div>`
          })
          return html
        }
      },
      legend: {
        data: seriesNames,
        textStyle: { color: '#a1a1aa' }, top: 10,
        type: 'scroll',
      },
      grid: { left: 60, right: 40, top: 60, bottom: 70 },
      xAxis: {
        type: 'time',
        axisPointer: { snap: true },
        axisLabel: { color: '#a1a1aa', formatter: (v) => dayjs(v).format('HH:mm:ss'), hideOverlap: true, rotate: 30 },
        axisLine: { lineStyle: { color: '#27272a' } }, splitLine: { show: false }
      },
      yAxis,
      series: chartSeries,
      dataZoom: [
        { type: 'inside', start: 0, end: 100 },
        { type: 'slider', start: 0, end: 100, height: 20, bottom: 10,
          borderColor: '#27272a', backgroundColor: '#0f0f12',
          fillerColor: 'rgba(139, 92, 246, 0.2)',
          handleStyle: { color: '#8b5cf6' }, textStyle: { color: '#a1a1aa' } }
      ],
      color: CHART_COLORS,
    }
  }

  const getCpSingleChartOption = (seriesKey) => {
    const d = cpChartData[seriesKey]
    if (!d) return {}
    const el = d.enumLabels
    const points = d.timestamps.map((t, i) => [t * 1000, d.values[i], el ? el[i] : null])
    const range = computeYRange({ [d.label]: points }, [d.label])
    const color = getCpSeriesColor(d.label)
    return {
      backgroundColor: 'transparent',
      title: { text: d.label, left: 'center', top: 6, textStyle: { color: '#e4e4e7', fontSize: 12, fontFamily: 'JetBrains Mono' } },
      tooltip: {
        trigger: 'axis', backgroundColor: '#0f0f12', borderColor: '#27272a',
        textStyle: { color: '#e4e4e7' },
        formatter: (params) => {
          if (!params || params.length === 0) return ''
          const p = params[0]
          const display = formatValueWithEnum(p.value[1], p.value[2])
          return `<div style="font-weight:600;margin-bottom:4px">${dayjs(p.value[0]).format('HH:mm:ss.SSS')}</div>
            <div style="display:flex;justify-content:space-between;gap:16px"><span>${p.marker} ${d.label}</span><span style="font-family:JetBrains Mono">${display}</span></div>`
        },
      },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: { left: 56, right: 16, top: 36, bottom: 56 },
      xAxis: {
        type: 'time',
        axisPointer: { snap: true, label: { show: false } },
        axisLabel: { color: '#a1a1aa', formatter: (v) => dayjs(v).format('HH:mm:ss'), hideOverlap: true, rotate: 30 },
        axisLine: { lineStyle: { color: '#27272a' } }, splitLine: { show: false },
      },
      yAxis: {
        type: 'value', name: '', min: range.min, max: range.max,
        axisLabel: { color: '#a1a1aa', formatter: formatYAxisTick },
        axisLine: { lineStyle: { color: '#27272a' } },
        splitLine: { lineStyle: { color: '#27272a' } },
      },
      series: [{
        name: d.label, type: 'line', data: points,
        smooth: true, symbol: 'circle', symbolSize: 4, showSymbol: false,
        lineStyle: { width: 1.5, color }, itemStyle: { color },
        emphasis: { lineStyle: { width: 3 }, itemStyle: { borderWidth: 2 } },
      }],
      dataZoom: [
        { type: 'inside', start: 0, end: 100 },
        { type: 'slider', start: 0, end: 100, height: 16, bottom: 4,
          borderColor: '#27272a', backgroundColor: '#0f0f12',
          fillerColor: 'rgba(139, 92, 246, 0.2)',
          handleStyle: { color: '#8b5cf6' }, textStyle: { color: '#a1a1aa' } }
      ],
    }
  }

  // ======== Render helpers ========

  const renderComparePanel = () => {
    const renderSegmentedOption = (text) => (
      <Tooltip title={text} placement="right">
        <div style={{ maxWidth: 80, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {text}
        </div>
      </Tooltip>
    )

    if (compareMode === 'single_port') {
      const spCanMulti = spSelectedFields.length >= 2
      const showSpYBaseline = spCanMulti && spChartLayout === 'overlay' && spSelectedFields.length >= 3
      return (
        <>
          {/* 改善 2: 模式说明 */}
          <div style={{ color: '#a1a1aa', fontSize: 12, marginBottom: 16 }}>在同一设备的数据中，对比不同字段的变化趋势</div>

          <Row gutter={16} align="bottom" style={{ marginBottom: 16 }}>
            <Col flex="240px">
              <div style={{ color: '#a1a1aa', marginBottom: 8, fontSize: 13 }}>选择端口</div>
              <Select
                value={spActiveResult ? getResultKey(spActiveResult) : undefined}
                onChange={(key) => {
                  const r = results.find(res => getResultKey(res) === key)
                  if (r) { setSpActiveResult(r); setSpSelectedFields([]); setSpChartData({}) }
                }}
                style={{ width: '100%' }}
                placeholder="选择一个端口"
              >
                {results.map(r => (
                  <Option key={getResultKey(r)} value={getResultKey(r)}>
                    {getResultLabel(r)}
                  </Option>
                ))}
              </Select>
            </Col>
            <Col flex="auto">
              <div style={{ color: '#a1a1aa', marginBottom: 8, fontSize: 13 }}>预加载要分析的字段（可多选）</div>
              <Select
                mode="multiple"
                value={spSelectedFields}
                onChange={setSpSelectedFields}
                style={{ width: '100%' }}
                placeholder="选择要分析的字段"
                maxTagCount={6}
                disabled={spAvailableFields.length === 0}
              >
                {spAvailableFields.map(f => <Option key={f} value={f}>{renderFieldWithTooltip(f)}</Option>)}
              </Select>
            </Col>
            <Col flex="100px">
              <Button
                type="default"
                icon={<ReloadOutlined />}
                onClick={loadSpChartData}
                loading={chartLoading}
                disabled={spSelectedFields.length === 0}
                style={{ width: '100%' }}
              >
                刷新
              </Button>
            </Col>
          </Row>

          {/* 改善 3: 快速选择字段面板上移 + 可折叠 */}
          {spAvailableFields.length > 0 && (
            <Collapse
              size="small"
              style={{ marginBottom: 16, backgroundColor: '#0f0f12', border: '1px solid #27272a', borderRadius: 8 }}
              items={[{
                key: 'quick-fields',
                label: <span style={{ color: '#a1a1aa', fontSize: 13 }}>快速选择字段（点击展开）</span>,
                children: (
                  <Checkbox.Group value={spSelectedFields} onChange={setSpSelectedFields} style={{ width: '100%' }}>
                    <Row gutter={[16, 12]}>
                      {spAvailableFields.map(f => (
                        <Col span={6} key={f}>
                          <Checkbox value={f}>{renderFieldWithTooltip(f)}</Checkbox>
                        </Col>
                      ))}
                    </Row>
                  </Checkbox.Group>
                ),
              }]}
            />
          )}

          {/* 叠加图/并列图（居中） */}
          {spSelectedFields.length >= 1 && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16, margin: '0 0 8px', flexWrap: 'wrap' }}>
              <Tooltip title={!spCanMulti ? '选择 2 个以上字段可启用对比模式' : undefined}>
                <Radio.Group
                  value={spChartLayout}
                  onChange={e => {
                    const v = e.target.value
                    setSpChartLayout(v)
                    if (v === 'grid' && spGridPanels.length === 0 && spSelectedFields.length > 0) {
                      setSpGridPanels(spSelectedFields.map(f => [f]))
                    }
                  }}
                  size="small" optionType="button" buttonStyle="solid"
                  disabled={!spCanMulti}
                >
                  <Radio.Button value="overlay"><Space size={4}><LineChartOutlined />叠加图</Space></Radio.Button>
                  <Radio.Button value="grid"><Space size={4}><AppstoreOutlined />并列图</Space></Radio.Button>
                </Radio.Group>
              </Tooltip>
              {spCanMulti && spChartLayout === 'grid' && (
                <>
                  <Segmented value={spGridCols} onChange={setSpGridCols} options={[
                    { label: '1列', value: 1 }, { label: '2列', value: 2 }, { label: '3列', value: 3 },
                  ]} size="small" />
                  <Button
                    size="small" icon={<PlusOutlined />}
                    onClick={() => setSpGridPanels(prev => [...prev, []])}
                  >
                    新建子图
                  </Button>
                </>
              )}
              {!spCanMulti ? (
                <span style={{ color: '#a1a1aa', fontSize: 12 }}>提示：选择多个字段可使用叠加对比或并列对比模式</span>
              ) : spChartLayout === 'grid' ? (
                <span style={{ color: '#a1a1aa', fontSize: 12 }}>提示：可在各个子图的下拉框中选择多个字段进行叠加对比</span>
              ) : null}
            </div>
          )}

          {spSelectedFields.length === 0 ? (
            <Empty description="请选择端口和字段" style={{ padding: '60px 0' }} />
          ) : chartLoading ? (
            <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
          ) : Object.keys(spChartData).length > 0 ? (
            spChartLayout === 'grid' && spCanMulti ? (
              <Row gutter={[16, 16]}>
                {spGridPanels.map((panelFields, panelIdx) => {
                  const opt = panelFields.length > 0 ? getSpPanelChartOption(panelFields) : {}
                  const hasSeries = opt && opt.series && opt.series.length > 0
                  return (
                    <Col span={24 / spGridCols} key={panelIdx}>
                      <div style={{ border: '1px solid #27272a', borderRadius: 8, backgroundColor: '#0f0f12', overflow: 'hidden' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', borderBottom: '1px solid #27272a', backgroundColor: '#0f0f12' }}>
                          <Select
                            mode="multiple"
                            size="small"
                            value={panelFields}
                            onChange={(vals) => {
                              setSpGridPanels(prev => {
                                const next = [...prev]
                                next[panelIdx] = vals
                                return next
                              })
                            }}
                            style={{ flex: 1, minWidth: 0 }}
                            placeholder="选择要叠加显示的字段"
                            maxTagCount={2}
                          >
                            {spAvailableFields.map(f => <Option key={f} value={f}>{renderFieldWithTooltip(f)}</Option>)}
                          </Select>
                          <Button
                            type="text" size="small" danger
                            icon={<DeleteOutlined />}
                            onClick={() => setSpGridPanels(prev => prev.filter((_, i) => i !== panelIdx))}
                          />
                        </div>
                        <div style={{ padding: 4 }}>
                          {hasSeries ? (
                            <ReactECharts
                              option={opt}
                              style={{ height: 280 }}
                              notMerge
                              onChartReady={(instance) => { instance.group = 'sp-grid'; echarts.connect('sp-grid') }}
                            />
                          ) : (
                            <Empty description="请在上方下拉框选择字段（可多选）" style={{ padding: '40px 0' }} image={Empty.PRESENTED_IMAGE_SIMPLE} />
                          )}
                        </div>
                      </div>
                    </Col>
                  )
                })}
              </Row>
            ) : showSpYBaseline ? (
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6, marginTop: 0 }}>
                <div style={{ flex: '0 0 auto', paddingTop: 48 }}>
                  <div style={{ color: '#a1a1aa', fontSize: 11, marginBottom: 6, lineHeight: 1.2 }}>Y轴基准</div>
                  <Segmented
                    vertical
                    value={spPrimaryYField || '__auto__'}
                    onChange={(v) => setSpPrimaryYField(v === '__auto__' ? null : v)}
                    options={[{ label: renderSegmentedOption('自动(全部)'), value: '__auto__' }, ...spSelectedFields.map(f => ({ label: renderSegmentedOption(f), value: f }))]}
                    size="small"
                    style={{ fontSize: 11 }}
                  />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <ReactECharts option={getSpChartOption()} style={{ height: 500 }} notMerge />
                </div>
              </div>
            ) : (
              <ReactECharts option={getSpChartOption()} style={{ height: 500 }} notMerge />
            )
          ) : null}
        </>
      )
    }

    // cross_port mode
    return (
      <>
        {/* 改善 2: 模式说明 */}
        <div style={{ color: '#a1a1aa', fontSize: 12, marginBottom: 16 }}>选择多个设备/端口，对比相同或不同字段</div>

        <Row gutter={16} align="bottom" style={{ marginBottom: 24 }}>
          <Col flex="auto">
            <div style={{ color: '#a1a1aa', marginBottom: 8, fontSize: 13 }}>选择端口/设备（至少两个）</div>
            <Select
              mode="multiple"
              value={cpSelectedResults}
              onChange={(vals) => {
                setCpSelectedResults(vals)
                setCpSelectedCommonFields([])
                setCpSelectedUniqueFields({})
                setCpChartData({})
              }}
              style={{ width: '100%' }}
              placeholder="选择要对比的端口（至少两个）"
              maxTagCount={6}
              optionLabelProp="label"
            >
              {results.map(r => (
                <Option key={getResultKey(r)} value={getResultKey(r)} label={getResultLabel(r)}>
                  <Space>
                    <span className="mono">{r.port_number}</span>
                    {r.source_device && <Tag color="orange" style={{ margin: 0, background: 'rgba(212, 168, 67, 0.15)', borderColor: '#d4a843', color: '#d4a843' }}>{r.source_device}</Tag>}
                    {r.parser_profile_name && <Tag color="green" style={{ margin: 0, background: 'rgba(95, 208, 104, 0.15)', borderColor: '#5fd068', color: '#5fd068' }}>{r.parser_profile_name}</Tag>}
                  </Space>
                </Option>
              ))}
            </Select>
          </Col>
          <Col flex="100px">
            <Button
              type="default"
              icon={<ReloadOutlined />}
              onClick={loadCpChartData}
              loading={chartLoading}
              disabled={!cpHasSelection || cpSelectedResults.length < 2}
              style={{ width: '100%' }}
            >
              刷新
            </Button>
          </Col>
        </Row>

        {cpSelectedResults.length < 2 && (
          <Empty description="请选择至少两个端口进行对比" style={{ padding: '60px 0' }} />
        )}

        {cpSelectedResults.length >= 2 && cpCommonFields.length > 0 && (
          <div style={{ marginBottom: 16, padding: 16, backgroundColor: '#0f0f12', border: '1px solid #27272a', borderRadius: 8 }}>
            <div style={{ color: '#8b5cf6', marginBottom: 12, fontSize: 13, fontWeight: 500 }}>
              共同字段 <span style={{ color: '#a1a1aa', fontWeight: 400 }}>（对所有已选设备生效）</span>
            </div>
            <Checkbox.Group value={cpSelectedCommonFields} onChange={setCpSelectedCommonFields} style={{ width: '100%' }}>
              <Row gutter={[16, 12]}>
                {cpCommonFields.map(f => (
                  <Col span={6} key={f}>
                    <Checkbox value={f}>{renderFieldWithTooltip(f)}</Checkbox>
                  </Col>
                ))}
              </Row>
            </Checkbox.Group>
          </div>
        )}

        {cpSelectedResults.length >= 2 && cpSelectedResults.some(key => (cpUniqueFieldsPerResult[key] || []).length > 0) && (
          <div style={{ marginBottom: 16, padding: 16, backgroundColor: '#0f0f12', border: '1px solid #27272a', borderRadius: 8 }}>
            <div style={{ color: '#d4a843', marginBottom: 16, fontSize: 13, fontWeight: 500 }}>
              设备独有字段 <span style={{ color: '#a1a1aa', fontWeight: 400 }}>（仅对对应设备生效）</span>
            </div>
            {cpSelectedResults.map(key => {
              const result = results.find(r => getResultKey(r) === key)
              const uniqueFields = cpUniqueFieldsPerResult[key] || []
              if (uniqueFields.length === 0) return null
              return (
                <div key={key} style={{ marginBottom: 16, paddingBottom: 12, borderBottom: '1px solid #18181b' }}>
                  <div style={{ color: '#e4e4e7', marginBottom: 8, fontSize: 13 }}>
                    {result && (
                      <Space size={4}>
                        <span className="mono" style={{ fontWeight: 600 }}>{result.port_number}</span>
                        {result.source_device && <Tag color="orange" style={{ margin: 0, background: 'rgba(212, 168, 67, 0.15)', borderColor: '#d4a843', color: '#d4a843' }}>{result.source_device}</Tag>}
                        {result.parser_profile_name && <Tag color="green" style={{ margin: 0, background: 'rgba(95, 208, 104, 0.15)', borderColor: '#5fd068', color: '#5fd068' }}>{result.parser_profile_name}</Tag>}
                      </Space>
                    )}
                  </div>
                  <Checkbox.Group
                    value={cpSelectedUniqueFields[key] || []}
                    onChange={(vals) => setCpSelectedUniqueFields(prev => ({ ...prev, [key]: vals }))}
                    style={{ width: '100%' }}
                  >
                    <Row gutter={[16, 8]}>
                      {uniqueFields.map(f => (
                        <Col span={6} key={f}>
                          <Checkbox value={f}>{renderFieldWithTooltip(f)}</Checkbox>
                        </Col>
                      ))}
                    </Row>
                  </Checkbox.Group>
                </div>
              )
            })}
          </div>
        )}

        {cpSelectedResults.length >= 2 && cpCommonFields.length === 0 &&
          Object.values(cpUniqueFieldsPerResult).every(arr => arr.length === 0) &&
          Object.keys(cpFieldsPerResult).length > 0 && (
          <Alert
            type="warning" showIcon
            message="所选端口没有可用的数值字段"
            style={{ marginBottom: 24 }}
          />
        )}

        {cpSelectedResults.length >= 2 && Object.keys(cpFieldsPerResult).length > 0 && (
          <div style={{ marginBottom: 24, display: 'flex', alignItems: 'center', gap: 16 }}>
            <Button
              type="primary"
              icon={<LineChartOutlined />}
              onClick={loadCpChartData}
              loading={chartLoading}
              disabled={!cpHasSelection}
              size="large"
            >
              开始分析
            </Button>
            {cpHasSelection && (
              <span style={{ color: '#a1a1aa', fontSize: 13 }}>
                已选择 {(() => {
                  let count = 0
                  count += cpSelectedCommonFields.length * cpSelectedResults.length
                  Object.values(cpSelectedUniqueFields).forEach(arr => { count += arr.length })
                  return count
                })()} 条数据系列
              </span>
            )}
      </div>
        )}

        {cpSkippedSeries.length > 0 && (
          <Alert
            type="info" showIcon closable
            message={`以下系列加载失败，已跳过：${cpSkippedSeries.join('、')}`}
            style={{ marginBottom: 24 }}
          />
        )}

        {(() => {
          const cpKeys = Object.keys(cpChartData)
          const cpSeriesLabels = Object.values(cpChartData).map(d => d.label)
          const hasCpData = cpKeys.length > 0
          const cpCanMulti = cpKeys.length >= 2
          const showCpYBaseline = cpCanMulti && cpChartLayout === 'overlay' && cpSeriesLabels.length >= 3
          return (
            <>
              {/* 叠加图/并列图（居中） */}
              {cpHasSelection && cpSelectedResults.length >= 2 && (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16, margin: '6px 0 8px', flexWrap: 'wrap' }}>
                  <Tooltip title={!cpCanMulti ? '加载数据后可启用对比模式' : undefined}>
                    <Radio.Group
                      value={cpChartLayout}
                      onChange={e => setCpChartLayout(e.target.value)}
                      size="small" optionType="button" buttonStyle="solid"
                      disabled={!cpCanMulti}
                    >
                      <Radio.Button value="overlay"><Space size={4}><LineChartOutlined />叠加图</Space></Radio.Button>
                      <Radio.Button value="grid"><Space size={4}><AppstoreOutlined />并列图</Space></Radio.Button>
                    </Radio.Group>
                  </Tooltip>
                  {cpCanMulti && cpChartLayout === 'grid' && (
                    <Segmented value={cpGridCols} onChange={setCpGridCols} options={[
                      { label: '1列', value: 1 }, { label: '2列', value: 2 }, { label: '3列', value: 3 },
                    ]} size="small" />
                  )}
                  {!cpCanMulti && (
                    <span style={{ color: '#a1a1aa', fontSize: 12 }}>提示：点击"开始分析"加载数据后可使用叠加或并列模式</span>
                  )}
                </div>
              )}

              {cpHasSelection && cpSelectedResults.length >= 2 ? (
                chartLoading ? (
                  <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
                ) : hasCpData ? (
                  cpChartLayout === 'grid' && cpCanMulti ? (
                    <Row gutter={[16, 16]}>
                      {cpKeys.map((key) => {
                        const opt = getCpSingleChartOption(key)
                        if (!opt || !opt.series) return null
                        return (
                          <Col span={24 / cpGridCols} key={key}>
                            <div style={{ border: '1px solid #27272a', borderRadius: 8, padding: 4, backgroundColor: '#0f0f12' }}>
                              <ReactECharts
                                option={opt}
                                style={{ height: 280 }}
                                notMerge
                                onChartReady={(instance) => { instance.group = 'cp-grid'; echarts.connect('cp-grid') }}
                              />
                            </div>
                          </Col>
                        )
                      })}
                    </Row>
                  ) : showCpYBaseline ? (
                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6, marginTop: 0 }}>
                      <div style={{ flex: '0 0 auto', paddingTop: 48 }}>
                        <div style={{ color: '#a1a1aa', fontSize: 11, marginBottom: 6, lineHeight: 1.2 }}>Y轴基准</div>
                        <Segmented
                          vertical
                          value={cpPrimaryYSeries || '__auto__'}
                          onChange={(v) => setCpPrimaryYSeries(v === '__auto__' ? null : v)}
                          options={[{ label: renderSegmentedOption('自动(全部)'), value: '__auto__' }, ...cpSeriesLabels.map(s => ({ label: renderSegmentedOption(s), value: s }))]}
                          size="small"
                          style={{ fontSize: 11 }}
                        />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <ReactECharts option={getCpChartOption()} style={{ height: 500 }} notMerge />
                      </div>
                    </div>
                  ) : (
                    <ReactECharts option={getCpChartOption()} style={{ height: 500 }} notMerge />
                  )
                ) : null
              ) : null}
            </>
          )
        })()}
      </>
    )
  }

  const formatAnomalyTs = (ts) =>
    ts == null || ts === undefined ? '—' : dayjs(ts * 1000).format('YYYY-MM-DD HH:mm:ss.SSS')

  const renderAnomalyPanel = () => {
    if (task.status !== 'completed') {
      return (
        <Alert type="warning" showIcon message="仅解析已完成的任务支持端口异常分析" />
      )
    }
    if (filteredResults.length === 0) {
      const isNoMatchedPorts = results.length === 0
        && task.status === 'completed'
        && (
          Number(task.parsed_packets || 0) === 0
          || String(task.error_message || '').includes('未找到匹配端口')
        )
      return <Empty description={isNoMatchedPorts ? '未找到匹配端口数据' : '暂无解析结果'} />
    }
    return (
      <div>
        {renderResultScopeFilters(
          <Button
            icon={<ReloadOutlined />}
            onClick={() => loadAnomalyDefaults()}
            disabled={anomalyDefaultsLoading || !activeResult}
          >
            刷新字段与默认阈值
          </Button>
        )}

        <div style={{ marginBottom: 16 }}>
          <div style={{ color: '#a1a1aa', fontSize: 12, marginBottom: 6 }}>分析端口</div>
          <Select
            showSearch
            placeholder="选择端口 / 设备 / 解析器"
            optionFilterProp="label"
            style={{ width: '100%' }}
            value={activeResult ? getResultKey(activeResult) : undefined}
            onChange={(key) => {
              const result = filteredResults.find(r => getResultKey(r) === key)
              if (result) {
                setActiveResult(result)
                setPagination(prev => ({ ...prev, current: 1 }))
              }
            }}
            options={filteredResults.map((r) => ({
              value: getResultKey(r),
              label: getResultLabel(r),
            }))}
          />
        </div>

        <Spin spinning={anomalyDefaultsLoading}>
          {!anomalyDefaultsLoading && anomalyNumericFields.length === 0 && (
            <Alert
              type="info" showIcon
              message="当前端口暂无可分析的数值字段（或解析结果不可用）"
              style={{ marginBottom: 16 }}
            />
          )}

          {anomalyNumericFields.length > 0 && (
            <>
              <Alert
                type="info" showIcon
                style={{ marginBottom: 16 }}
                message={
                  <span>
                    卡死：连续 <strong>{anomalyStuckFrames}</strong> 帧数值完全相同计为异常区间；
                    跳变：相对<strong>卡尔曼滤波预测值</strong>的偏差超过阈值（%）时告警。阈值可按字段调整。
                  </span>
                }
              />

              <div style={{ marginBottom: 12 }}>
                <Space wrap>
                  <span style={{ color: '#a1a1aa' }}>分析字段:</span>
                  <Button size="small" type="link" onClick={() => onAnomalyFieldsChange([...anomalyNumericFields])}>
                    全选
                  </Button>
                  <Button size="small" type="link" onClick={() => onAnomalyFieldsChange([])}>
                    清空
                  </Button>
                </Space>
              </div>
              <Checkbox.Group
                value={anomalySelectedFields}
                onChange={onAnomalyFieldsChange}
                style={{ width: '100%', marginBottom: 16 }}
              >
                <Row gutter={[8, 8]}>
                  {anomalyNumericFields.map((f) => (
                    <Col xs={24} sm={12} md={8} lg={6} key={f}>
                      <Checkbox value={f}>{renderFieldWithTooltip(f)}</Checkbox>
                    </Col>
                  ))}
                </Row>
              </Checkbox.Group>

              <Divider orientation="left" plain style={{ color: '#a1a1aa' }}>
                跳变阈值（%，相对卡尔曼预测值）
              </Divider>
              <Row gutter={[12, 12]} style={{ marginBottom: 20 }}>
                {anomalySelectedFields.map((f) => (
                  <Col xs={24} sm={12} md={8} key={f}>
                    <Space>
                      <Tooltip title={getFieldTooltipText(f)}>
                        <span className="mono" style={{ color: '#e4e4e7', minWidth: 120 }}>{f}</span>
                      </Tooltip>
                      <InputNumber
                        min={0.01}
                        max={500}
                        step={0.5}
                        value={anomalyThresholdEdits[f]}
                        onChange={(v) => setAnomalyThresholdEdits((prev) => ({ ...prev, [f]: v }))}
                        size="small"
                      />
                      <span style={{ color: '#a1a1aa', fontSize: 12 }}>
                        默认 {anomalyDefaultThresholds[f] ?? '—'}
                      </span>
                    </Space>
                  </Col>
                ))}
              </Row>

              <Button
                type="primary"
                icon={<WarningOutlined />}
                onClick={runAnomalyAnalyze}
                loading={anomalyAnalyzing}
                disabled={anomalySelectedFields.length === 0}
                size="large"
              >
                开始异常分析
              </Button>
            </>
          )}
        </Spin>

        {anomalyResult && (
          <div style={{ marginTop: 28 }}>
            {anomalyResult.message && (
              <Alert type="warning" showIcon message={anomalyResult.message} style={{ marginBottom: 16 }} />
            )}
            <Row gutter={16} style={{ marginBottom: 20 }}>
              <Col span={6}>
                <Statistic title="分析字段数" value={anomalyResult.summary?.fields_analyzed ?? 0} />
              </Col>
              <Col span={6}>
                <Statistic title="跳变告警数" value={anomalyResult.summary?.jump_count ?? 0} valueStyle={{ color: '#f05050' }} />
              </Col>
              <Col span={6}>
                <Statistic title="卡死区间数" value={anomalyResult.summary?.stuck_count ?? 0} valueStyle={{ color: '#d4a843' }} />
              </Col>
              <Col span={6}>
                <Statistic
                  title="最早异常时间"
                  value={formatAnomalyTs(anomalyResult.summary?.first_anomaly_ts)}
                  valueStyle={{ fontSize: 13 }}
                />
              </Col>
            </Row>
            <Row gutter={16} style={{ marginBottom: 20 }}>
              <Col span={24}>
                <Statistic
                  title="最晚异常时间"
                  value={formatAnomalyTs(anomalyResult.summary?.last_anomaly_ts)}
                  valueStyle={{ fontSize: 13 }}
                />
              </Col>
            </Row>

            {anomalyTimelineHints.length > 0 && (
              <div style={{ marginBottom: 24 }}>
                <div style={{ color: '#a1a1aa', marginBottom: 8 }}>异常时间点速览（点击复制时间戳）</div>
                <Space wrap size={[4, 8]}>
                  {anomalyTimelineHints.map((ts) => (
                    <Tag
                      key={ts}
                      style={{ cursor: 'pointer' }}
                      onClick={() => {
                        const t = formatAnomalyTs(ts)
                        navigator.clipboard?.writeText(t).then(() => message.success('已复制: ' + t)).catch(() => message.info(t))
                      }}
                    >
                      {formatAnomalyTs(ts)}
                    </Tag>
                  ))}
                </Space>
              </div>
            )}

            <Divider orientation="left">跳变分析</Divider>
            <div style={{ marginBottom: 12 }}>
              <Space>
                <span style={{ color: '#a1a1aa' }}>按字段筛选:</span>
                <Select
                  allowClear
                  placeholder="全部字段"
                  style={{ width: 200 }}
                  value={anomalyJumpFieldFilter}
                  onChange={setAnomalyJumpFieldFilter}
                  options={jumpFieldFilterOptions.map((f) => ({ label: f, value: f }))}
                />
              </Space>
            </div>
            <Table
              size="small"
              rowKey={(r, i) => `j-${r.field_name}-${r.timestamp}-${i}`}
              dataSource={filteredJumpEvents}
              scroll={{ x: 'max-content' }}
              pagination={{ pageSize: 50, showTotal: (t) => `共 ${t} 条` }}
              columns={[
                { title: '字段', dataIndex: 'field_name', key: 'field_name', width: 140, render: (v) => <span className="mono">{v}</span> },
                { title: '时间', dataIndex: 'timestamp', key: 'timestamp', width: 200, render: (v) => formatAnomalyTs(v) },
                { title: '当前值', dataIndex: 'current_value', key: 'current_value', render: (v) => <span className="mono">{v != null ? Number(v).toFixed(6) : '—'}</span> },
                { title: '预测值', dataIndex: 'predicted_value', key: 'predicted_value', render: (v) => <span className="mono">{v != null ? Number(v).toFixed(6) : '—'}</span> },
                { title: '偏差%', dataIndex: 'deviation_pct', key: 'deviation_pct', render: (v) => <span className="mono">{v != null ? Number(v).toFixed(4) : '—'}</span> },
                { title: '阈值%', dataIndex: 'threshold_pct', key: 'threshold_pct', render: (v) => <span className="mono">{v != null ? Number(v).toFixed(2) : '—'}</span> },
              ]}
            />

            <Divider orientation="left">卡死分析</Divider>
            <div style={{ marginBottom: 12 }}>
              <Space>
                <span style={{ color: '#a1a1aa' }}>按字段筛选:</span>
                <Select
                  allowClear
                  placeholder="全部字段"
                  style={{ width: 200 }}
                  value={anomalyStuckFieldFilter}
                  onChange={setAnomalyStuckFieldFilter}
                  options={stuckFieldFilterOptions.map((f) => ({ label: f, value: f }))}
                />
              </Space>
            </div>
            <Table
              size="small"
              rowKey={(r, i) => `s-${r.field_name}-${r.start_ts}-${i}`}
              dataSource={filteredStuckEvents}
              scroll={{ x: 'max-content' }}
              pagination={{ pageSize: 50, showTotal: (t) => `共 ${t} 条` }}
              columns={[
                { title: '字段', dataIndex: 'field_name', key: 'field_name', width: 140, render: (v) => <span className="mono">{v}</span> },
                { title: '开始时间', dataIndex: 'start_ts', key: 'start_ts', width: 200, render: (v) => formatAnomalyTs(v) },
                { title: '结束时间', dataIndex: 'end_ts', key: 'end_ts', width: 200, render: (v) => formatAnomalyTs(v) },
                { title: '连续帧数', dataIndex: 'frame_count', key: 'frame_count', width: 100 },
                { title: '卡死值', dataIndex: 'stuck_value', key: 'stuck_value', render: (v) => <span className="mono">{v != null && typeof v === 'number' ? Number(v).toFixed(6) : String(v)}</span> },
              ]}
            />
          </div>
        )}
      </div>
    )
  }

  // ======== Main render ========

  if (loading) {
    return <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
  }

  if (!task) {
    return <Empty description="任务不存在" />
  }

  if (task.status === 'pending' || task.status === 'processing') {
    const pct = typeof task.progress === 'number'
      ? Math.min(100, Math.max(0, task.progress))
      : 0
    return (
      <div className="fade-in" style={{ maxWidth: 520, margin: '64px auto', padding: '0 24px' }}>
        <Card>
          <div style={{ textAlign: 'center', padding: '32px 16px' }}>
            <Spin size="large" />
            <h2 style={{ marginTop: 28, marginBottom: 8, color: '#e4e4e7', fontWeight: 600 }}>
              {task.status === 'pending' ? '等待开始解析…' : '正在解析数据…'}
            </h2>
            <p className="mono" style={{ color: '#a1a1aa', marginBottom: 24, wordBreak: 'break-all' }}>
              {task.filename}
            </p>
            <Progress
              percent={task.status === 'pending' ? 0 : pct}
              status={task.status === 'pending' ? 'normal' : 'active'}
              strokeColor={{ from: '#8b5cf6', to: '#5fd068' }}
              style={{ marginBottom: 12 }}
            />
            <p style={{ color: '#a1a1aa', fontSize: 13 }}>
              {task.status === 'pending'
                ? '任务已排队，解析即将开始'
                : `已读取约 ${pct}%（按文件字节估算，保存结果阶段可能停留在 99%）`}
            </p>
          </div>
        </Card>
      </div>
    )
  }

  const noMatchedPortData = task.status === 'completed'
    && results.length === 0
    && (
      Number(task.parsed_packets || 0) === 0
      || String(task.error_message || '').includes('未找到匹配端口')
    )

  const tabItems = filteredResults.map(result => ({
    key: getResultKey(result),
    label: (
      <Space>
        <span className="mono">{result.port_number}</span>
        {result.source_device && <Tag color="orange" style={{ background: 'rgba(212, 168, 67, 0.15)', borderColor: '#d4a843', color: '#d4a843' }}>{result.source_device}</Tag>}
        {result.parser_profile_name && parserList.length > 1 && (
          <Tag color="green" style={{ background: 'rgba(95, 208, 104, 0.15)', borderColor: '#5fd068', color: '#5fd068' }}>{result.parser_profile_name}</Tag>
        )}
        <Tag style={{ background: '#18181b', borderColor: '#27272a', color: '#a1a1aa' }}>{result.record_count.toLocaleString()} 条</Tag>
      </Space>
    ),
  }))

  const renderResultScopeFilters = (extraRight = null) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 10 }}>
      <Space wrap>
        {(deviceList.length > 0 || parserList.length > 1) && (
          <>
            <span style={{ color: '#a1a1aa' }}><FilterOutlined /> 筛选:</span>
            {deviceList.length > 0 && (
              <Select
                placeholder="按设备筛选"
                allowClear
                style={{ width: 160 }}
                value={selectedDevice}
                onChange={handleDeviceFilter}
              >
                {deviceList.map(d => <Option key={d} value={d}>{d}</Option>)}
              </Select>
            )}
            {parserList.length > 1 && (
              <Select
                placeholder="按解析器筛选"
                allowClear
                style={{ width: 160 }}
                value={selectedParser}
                onChange={handleParserFilter}
              >
                {parserList.map(p => <Option key={p.id} value={p.id}>{p.name}</Option>)}
              </Select>
            )}
          </>
        )}
        {results.length > 0 && (
          filteredResults.length > 0 ? (
            <Tag style={{ background: '#18181b', borderColor: '#27272a', color: '#a1a1aa' }}>
              匹配端口 {filteredResults.length} / {results.length}
            </Tag>
          ) : (
            <Tag style={{ background: 'rgba(212, 168, 67, 0.12)', borderColor: '#d4a843', color: '#d4a843' }}>
              筛选后无可用端口
            </Tag>
          )
        )}
      </Space>
      {extraRight ? <Space>{extraRight}</Space> : null}
    </div>
  )

  return (
    <div className="fade-in">
      {/* Task overview */}
      <Card style={{ marginBottom: 24 }}>
        <Row gutter={[24, 16]} align="middle">
          <Col xs={24} sm={12} md={8} lg={6}>
            <Statistic
              title="文件名" value={task.filename}
              valueStyle={{ fontSize: 14, fontFamily: 'JetBrains Mono', wordBreak: 'break-all', color: '#e4e4e7' }}
            />
          </Col>
          <Col xs={12} sm={6} md={4} lg={4}>
            <Statistic
              title={<Space size={4}><ApiOutlined style={{ color: '#8b5cf6' }} /><span>网络配置</span></Space>}
              value={task.network_config_name ? `${task.network_config_name} ${task.network_config_version}` : '扫描模式'}
              valueStyle={{ fontSize: 13, color: task.network_config_name ? '#8b5cf6' : '#a1a1aa' }}
            />
          </Col>
          <Col xs={12} sm={6} md={4} lg={4}>
            <Statistic
              title={<Space size={4}><RocketOutlined style={{ color: '#5fd068' }} /><span>解析器</span></Space>}
              value={
                task.device_parsers?.length > 0
                  ? `${task.device_parsers.length} 设备`
                  : task.parser_profiles?.length > 0
                    ? `${task.parser_profiles.length} 个解析器`
                    : (task.parser_profile_name || '-')
              }
              valueStyle={{ fontSize: 13, color: '#5fd068' }}
            />
          </Col>
          <Col xs={12} sm={6} md={4} lg={3}>
            <Statistic title="解析端口数" value={results.length}
              prefix={<DatabaseOutlined />} valueStyle={{ color: '#5fd068' }} />
          </Col>
          <Col xs={12} sm={6} md={4} lg={3}>
            <Statistic title="总数据量" value={task.parsed_packets}
              valueStyle={{ color: '#d4a843' }} />
          </Col>
        </Row>

        {task.device_parsers && task.device_parsers.length > 0 ? (
          <div style={{ marginTop: 16 }}>
            <Space wrap>
              <DesktopOutlined style={{ color: '#d4a843' }} />
              <span style={{ color: '#a1a1aa' }}>设备解析配置:</span>
              {task.device_parsers.map(dp => (
                <Space key={dp.device_name} size={2}>
                  <Tag color="orange" style={{ background: 'rgba(212, 168, 67, 0.15)', borderColor: '#d4a843', color: '#d4a843' }}>{dp.device_name}</Tag>
                  <span style={{ color: '#a1a1aa' }}>→</span>
                  <Tag color="green" style={{ background: 'rgba(95, 208, 104, 0.15)', borderColor: '#5fd068', color: '#5fd068' }}>{[dp.parser_profile_name, dp.parser_profile_version].filter(Boolean).join(' ')}</Tag>
                </Space>
              ))}
            </Space>
          </div>
        ) : (
          <>
            {task.selected_devices && task.selected_devices.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <Space>
                  <DesktopOutlined style={{ color: '#d4a843' }} />
                  <span style={{ color: '#a1a1aa' }}>选中设备:</span>
                  {task.selected_devices.map(d => <Tag key={d} color="orange" style={{ background: 'rgba(212, 168, 67, 0.15)', borderColor: '#d4a843', color: '#d4a843' }}>{d}</Tag>)}
                </Space>
              </div>
            )}
            {task.parser_profiles && task.parser_profiles.length > 1 && (
              <div style={{ marginTop: 8 }}>
                <Space>
                  <RocketOutlined style={{ color: '#5fd068' }} />
                  <span style={{ color: '#a1a1aa' }}>解析器:</span>
                  {task.parser_profiles.map(p => <Tag key={p.id} color="green" style={{ background: 'rgba(95, 208, 104, 0.15)', borderColor: '#5fd068', color: '#5fd068' }}>{p.name}</Tag>)}
                </Space>
              </div>
            )}
          </>
        )}
      </Card>

      {noMatchedPortData && (
        <Alert
          type="info"
          showIcon
          message="未找到匹配端口数据"
          description={task.error_message || '当前文件未命中所选端口，请检查端口选择或数据内容。'}
          style={{ marginBottom: 16 }}
        />
      )}

      <Tabs
        activeKey={mainTab}
        onChange={setMainTab}
        type="card"
        items={[
          {
            key: 'table',
            label: <Space><DatabaseOutlined />数据表格</Space>,
            children: (
              <Card>
                {renderResultScopeFilters(
                  <>
                    {activeResult && (
                      <>
                        <Checkbox
                          checked={singleExportIncludeText}
                          onChange={(e) => setSingleExportIncludeText(e.target.checked)}
                        >
                          导出中文说明列
                        </Checkbox>
                        <Button icon={<DownloadOutlined />} onClick={() => handleExport('csv')}>导出 CSV</Button>
                        <Button icon={<DownloadOutlined />} onClick={() => handleExport('parquet')}>导出 Parquet</Button>
                      </>
                    )}
                    {results.length > 0 && (
                      <Button type="primary" icon={<DownloadOutlined />} onClick={() => {
                        setBatchExportSelected(results.map(r => getResultKey(r)))
                        setBatchExportOpen(true)
                      }}>
                        批量导出
                      </Button>
                    )}
                    {allColumnNames.length > 0 && (
                      <Button icon={<SettingOutlined />} onClick={() => setColManagerOpen(true)}>
                        列管理
                      </Button>
                    )}
                  </>
                )}

                {filteredResults.length > 0 ? (
          <>
            <div style={{ marginBottom: 12 }}>
              <div style={{ color: '#a1a1aa', fontSize: 12, marginBottom: 6 }}>当前端口</div>
              <Select
                showSearch
                optionFilterProp="label"
                placeholder="选择端口 / 设备 / 解析器"
                style={{ width: '100%' }}
                value={activeResult ? getResultKey(activeResult) : undefined}
                onChange={(key) => {
                  const result = filteredResults.find(r => getResultKey(r) === key)
                  if (result) {
                    setActiveResult(result)
                    setPagination(prev => ({ ...prev, current: 1 }))
                  }
                }}
                options={filteredResults.map((result) => ({
                  value: getResultKey(result),
                  label: getResultLabel(result),
                }))}
              />
            </div>
            {labelFilterOptions.length > 0 && (
              <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center' }}>
                <span style={{ color: '#a1a1aa', marginRight: 8 }}><FilterOutlined /> 当前视图内筛选:</span>
                <Select
                  placeholder="按 Label / CAN ID 筛选列/行"
                  allowClear showSearch
                  style={{ width: 240 }}
                  value={labelFilterValue}
                  onChange={handleLabelFilter}
                  options={labelFilterOptions}
                />
              </div>
            )}
            <Table
                      columns={portColumns} dataSource={filteredPortData}
                      rowKey={(_, index) => index} loading={dataLoading}
                      scroll={{ x: 'max-content', y: 585 }} size="small"
              pagination={{
                        ...pagination, showSizeChanger: true, showQuickJumper: true,
                showTotal: (total) => `共 ${total} 条`,
                pageSizeOptions: [50, 100, 200, 500],
                        onChange: (page, pageSize) => setPagination(prev => ({ ...prev, current: page, pageSize })),
              }}
            />
          </>
        ) : (
          <Empty description={noMatchedPortData ? '未找到匹配端口数据' : '暂无解析结果'} />
        )}
      </Card>
            )
          },
          {
            key: 'analysis',
            label: <Space><LineChartOutlined />数据分析</Space>,
            children: (
              <Card
                title={
                  <Space>
                    <BarChartOutlined />
                    <span>图表分析</span>
                    <Radio.Group
                      value={compareMode}
                      onChange={(e) => {
                        setCompareMode(e.target.value)
                        setChartLoading(false)
                      }}
                      size="small"
                      optionType="button"
                      buttonStyle="solid"
                      style={{ marginLeft: 8 }}
                    >
                      <Radio.Button value="single_port">
                        <Space size={4}><LineChartOutlined />同端口多字段</Space>
                      </Radio.Button>
                      <Radio.Button value="cross_port">
                        <Space size={4}><SwapOutlined />跨设备对比</Space>
                      </Radio.Button>
                    </Radio.Group>
                  </Space>
                }
              >
                {renderComparePanel()}
              </Card>
            )
          },
          {
            key: 'anomaly',
            label: <Space><WarningOutlined />异常分析</Space>,
            children: (
              <Card title={<Space><WarningOutlined /><span>端口异常分析（跳变 / 卡死）</span></Space>}>
                {renderAnomalyPanel()}
              </Card>
            ),
          },
        ]}
      />

      {/* Column Manager Modal */}
      <Modal
        title="列管理"
        open={colManagerOpen}
        onCancel={() => setColManagerOpen(false)}
        footer={null}
        width={520}
        styles={{ body: { maxHeight: 480, overflowY: 'auto' } }}
      >
        <div style={{ marginBottom: 12 }}>
          <Space>
            <Button size="small" type="link" onClick={() => setHiddenColumns(new Set())}>显示全部</Button>
            <Button size="small" type="link" onClick={() => {
              const toHide = allColumnNames.filter(c => !pinnedColumns.has(c))
              setHiddenColumns(new Set(toHide))
            }}>仅显示固定列</Button>
          </Space>
        </div>
        <div style={{ marginBottom: 8, color: '#a1a1aa', fontSize: 12 }}>
          <PushpinOutlined /> 固定列会锁定在表格左侧。点击图钉切换固定状态，取消勾选可隐藏列。
        </div>
        {allColumnNames.map(col => {
          const isHidden = hiddenColumns.has(col)
          const isPinned = pinnedColumns.has(col)
          return (
            <div key={col} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '6px 8px', borderBottom: '1px solid #18181b',
              opacity: isHidden ? 0.5 : 1,
            }}>
              <Checkbox
                checked={!isHidden}
                onChange={(e) => {
                  setHiddenColumns(prev => {
                    const next = new Set(prev)
                    if (e.target.checked) next.delete(col)
                    else next.add(col)
                    return next
                  })
                }}
              >
                <span className="mono" style={{ fontSize: 13 }}>{col}</span>
              </Checkbox>
              <Button
                type="text" size="small"
                icon={<PushpinOutlined style={{ color: isPinned ? '#8b5cf6' : '#a1a1aa' }} />}
                onClick={() => {
                  setPinnedColumns(prev => {
                    const next = new Set(prev)
                    if (next.has(col)) next.delete(col)
                    else next.add(col)
                    return next
                  })
                }}
              />
            </div>
          )
        })}
      </Modal>

      {/* Batch Export Modal */}
      <Modal
        title="批量导出"
        open={batchExportOpen}
        onCancel={() => setBatchExportOpen(false)}
        onOk={handleBatchExportSubmit}
        confirmLoading={batchExporting}
        okText="开始导出"
        cancelText="取消"
        width={560}
      >
        <div style={{ marginBottom: 16 }}>
          <div style={{ color: '#a1a1aa', marginBottom: 8, fontSize: 13 }}>导出格式</div>
          <Radio.Group value={batchExportFormat} onChange={e => setBatchExportFormat(e.target.value)}>
            <Radio.Button value="csv">CSV（逐个下载）</Radio.Button>
            <Radio.Button value="zip">ZIP（打包下载）</Radio.Button>
          </Radio.Group>
        </div>
        <div style={{ marginBottom: 16 }}>
          <div style={{ color: '#a1a1aa', marginBottom: 8, fontSize: 13 }}>文字列导出</div>
          <Radio.Group value={batchExportIncludeText} onChange={e => setBatchExportIncludeText(e.target.value)}>
            <Radio.Button value={true}>导出文字列</Radio.Button>
            <Radio.Button value={false}>去掉中文说明列</Radio.Button>
          </Radio.Group>
        </div>
        <div style={{ marginBottom: 12 }}>
          <div style={{ color: '#a1a1aa', marginBottom: 8, fontSize: 13 }}>选择要导出的端口</div>
          <Space style={{ marginBottom: 8 }}>
            <Button size="small" type="link" onClick={() => setBatchExportSelected(results.map(r => getResultKey(r)))}>全选</Button>
            <Button size="small" type="link" onClick={() => setBatchExportSelected([])}>清空</Button>
          </Space>
          <Checkbox.Group
            value={batchExportSelected}
            onChange={setBatchExportSelected}
            style={{ width: '100%' }}
          >
            <Row gutter={[8, 8]}>
              {results.map(r => (
                <Col span={24} key={getResultKey(r)}>
                  <Checkbox value={getResultKey(r)}>
                    <Space>
                      <span className="mono">{r.port_number}</span>
                      {r.source_device && <Tag color="orange" style={{ margin: 0, background: 'rgba(212, 168, 67, 0.15)', borderColor: '#d4a843', color: '#d4a843' }}>{r.source_device}</Tag>}
                      {r.parser_profile_name && <Tag color="green" style={{ margin: 0, background: 'rgba(95, 208, 104, 0.15)', borderColor: '#5fd068', color: '#5fd068' }}>{r.parser_profile_name}</Tag>}
                      <span style={{ color: '#a1a1aa', fontSize: 12 }}>{r.record_count.toLocaleString()} 条</span>
                    </Space>
                  </Checkbox>
                </Col>
              ))}
            </Row>
          </Checkbox.Group>
        </div>
      </Modal>
    </div>
  )
}

export default ResultPage
