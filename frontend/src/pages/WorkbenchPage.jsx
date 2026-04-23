import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Card, Row, Col, Select, Button, Space, Typography, Spin, Alert, InputNumber,
  Form, Radio, Table, Tag, Empty, message, Tabs, Slider, Switch, Tooltip,
  Statistic, Collapse, Badge, Divider,
} from 'antd'
import {
  AimOutlined, LeftOutlined, FullscreenOutlined, FullscreenExitOutlined,
  ReloadOutlined, DatabaseOutlined, RightOutlined, SwapOutlined,
  CheckCircleOutlined, WarningOutlined, CloseCircleOutlined, PlayCircleOutlined,
  LineChartOutlined, AppstoreOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { parseApi, workbenchApi, sharedTsnApi, TOKEN_KEY } from '../services/api'
import MapTrajectoryLeaflet from '../components/workbench/MapTrajectoryLeaflet'

const { Title, Text } = Typography

function videoTabsStorageKey(sortieId) {
  return `workbench_video_tabs_v1_${sortieId}`
}

function loadVideoTabsState(sortieId) {
  try {
    const raw = sessionStorage.getItem(videoTabsStorageKey(sortieId))
    if (!raw) return null
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function saveVideoTabsState(sortieId, state) {
  sessionStorage.setItem(videoTabsStorageKey(sortieId), JSON.stringify(state))
}

const VIDEO_MULTI_SLOTS = 9

function migratePaneMultiIds(p) {
  if (Array.isArray(p.multiIds) && p.multiIds.length === VIDEO_MULTI_SLOTS) {
    return [...p.multiIds]
  }
  const m = Array(VIDEO_MULTI_SLOTS).fill(null)
  const q = p.quadIds
  if (Array.isArray(q)) {
    for (let i = 0; i < Math.min(4, q.length); i += 1) {
      m[i] = q[i] ?? null
    }
  }
  return m
}

function normalizeVideoPane(p) {
  const multiIds = migratePaneMultiIds(p)
  const cc = Number(p.columnCount)
  const columnCount = Number.isFinite(cc) && cc >= 1 && cc <= 9 ? Math.floor(cc) : 3
  return { ...p, multiIds, columnCount }
}

function visibleVideoSlotCount(p) {
  if (!p) return 0
  if (p.layout === 'quad') return 4
  if (p.layout === 'nine') return 9
  if (p.layout === 'column') {
    return Math.min(VIDEO_MULTI_SLOTS, Math.max(1, Number(p.columnCount) || 3))
  }
  return 0
}

function alignmentStorageKey(sortieId) {
  return `workbench_align_v1_${sortieId}`
}

function loadAlignment(sortieId) {
  try {
    const raw = localStorage.getItem(alignmentStorageKey(sortieId))
    if (!raw) return { parseOffsetMs: 0, masterClock: 'parse', videoOffsets: {} }
    const j = JSON.parse(raw)
    return {
      parseOffsetMs: Number(j.parseOffsetMs) || 0,
      masterClock: j.masterClock === 'video' ? 'video' : 'parse',
      videoOffsets: typeof j.videoOffsets === 'object' && j.videoOffsets ? j.videoOffsets : {},
    }
  } catch {
    return { parseOffsetMs: 0, masterClock: 'parse', videoOffsets: {} }
  }
}

function saveAlignment(sortieId, data) {
  localStorage.setItem(alignmentStorageKey(sortieId), JSON.stringify(data))
}

function pickIrsResults(results) {
  if (!results?.length) return []
  return results.filter((r) => {
    const t = `${r.parser_profile_name || ''}${r.message_name || ''}${r.source_device || ''}`
    return /惯导|IRS|惯性/i.test(t)
  })
}

function formatIrsLabel(r) {
  const dev = r.source_device || r.message_name || '未知设备'
  return `${dev} · 端口 ${r.port_number}${r.parser_profile_name ? ` · ${r.parser_profile_name}` : ''}`
}

function haversineMeters(lon1, lat1, lon2, lat2) {
  const R = 6371000
  const toRad = (d) => (d * Math.PI) / 180
  const dLat = toRad(lat2 - lat1)
  const dLon = toRad(lon2 - lon1)
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)))
}

/**
 * 沿轨迹由相邻点距离 / 解析时间差估算地速 (m/s)，用于缺速度列或列值近似常数时的着色尺度。
 */
function kinematicGroundSpeedFromPath(path, tSec) {
  const n = path?.length || 0
  const out = Array.from({ length: n }, () => null)
  if (n < 2 || !tSec?.length) return out
  const segV = []
  for (let i = 1; i < n; i += 1) {
    const dt = Number(tSec[i]) - Number(tSec[i - 1])
    const [lo0, la0] = path[i - 1]
    const [lo1, la1] = path[i]
    const dm = haversineMeters(lo0, la0, lo1, la1)
    segV.push(dt > 1e-12 ? dm / dt : null)
  }
  out[0] = segV[0]
  for (let i = 1; i < n - 1; i += 1) {
    const a = segV[i - 1]
    const b = segV[i]
    if (a != null && Number.isFinite(a) && b != null && Number.isFinite(b)) out[i] = (a + b) / 2
    else out[i] = Number.isFinite(a) ? a : (Number.isFinite(b) ? b : null)
  }
  out[n - 1] = segV[segV.length - 1]
  return out
}

/** 解析得到的地速序列 + 轨迹运动学推算，保证地图颜色映射有足够动态范围 */
function finalizeGroundSpeedValsForMap(path, tSec, parserGs) {
  const kin = kinematicGroundSpeedFromPath(path, tSec)
  const n = path?.length || 0
  if (!n) return []

  let merged = parserGs.map((g, i) => ((g != null && Number.isFinite(g)) ? g : kin[i]))

  function spectrumFlat(arr) {
    const fin = arr.filter((x) => x != null && Number.isFinite(x))
    if (fin.length < 2) return true
    const mn = Math.min(...fin)
    const mx = Math.max(...fin)
    const spread = mx - mn
    const mid = Math.abs((mx + mn) / 2)
    const rel = spread / (mid + 0.05)
    return spread < 2e-2 || rel < 5e-5
  }

  if (spectrumFlat(merged)) merged = kin.slice()

  return merged
}

function parseSeriesNumber(v) {
  if (v == null || v === '') return null
  const x = Number(v)
  return Number.isFinite(x) ? x : null
}

/**
 * 给定"毫秒时间戳"（Date 可构造）返回 Asia/Shanghai 的 HH:MM:SS。
 * 用于图表坐标轴时间刻度显示；越界/非数值返回空串。
 */
function beijingHmsFromMs(ms) {
  if (!Number.isFinite(ms)) return ''
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/** 与解析结果页图表一致的 dataZoom（内置缩放 + 底部滑块） */
const WORKBENCH_CHART_DATA_ZOOM = [
  { type: 'inside', start: 0, end: 100 },
  {
    type: 'slider',
    start: 0,
    end: 100,
    height: 20,
    bottom: 8,
    borderColor: '#27272a',
    backgroundColor: '#0f0f12',
    fillerColor: 'rgba(139, 92, 246, 0.2)',
    handleStyle: { color: '#8b5cf6' },
    textStyle: { color: '#a1a1aa' },
  },
]

function computeWorkbenchAttitudeYRange(seriesArrays) {
  const vals = []
  seriesArrays.forEach((arr) => {
    (arr || []).forEach((v) => {
      if (v != null && Number.isFinite(Number(v))) vals.push(Number(v))
    })
  })
  if (!vals.length) return { min: undefined, max: undefined }
  const lo = Math.min(...vals)
  const hi = Math.max(...vals)
  const span = hi - lo
  const pad = span > 0 ? span * 0.05 : Math.max(Math.abs(lo) * 0.05, 1)
  return { min: lo - pad, max: hi + pad }
}

/** 按时间轴像素值（ms）找最近轨迹采样索引 */
function nearestTrajIndexFromAxisMs(tSec, tMs) {
  let bestI = 0
  let bestD = Infinity
  for (let i = 0; i < tSec.length; i += 1) {
    const tv = tSec[i]
    if (!Number.isFinite(tv)) continue
    const d = Math.abs(tv * 1000 - tMs)
    if (d < bestD) {
      bestD = d
      bestI = i
    }
  }
  return { idx: bestI, distMs: bestD }
}

/** 在姿态降采样序列上找与 tMs 最近的点下标 */
function nearestAttitudeIndexFromAxisMs(tMs, toX, len) {
  let bestK = 0
  let bestD = Infinity
  for (let k = 0; k < len; k += 1) {
    const x = toX(k)
    if (x == null || !Number.isFinite(x)) continue
    const d = Math.abs(x - tMs)
    if (d < bestD) {
      bestD = d
      bestK = k
    }
  }
  return bestK
}

/** 总览姿态序列 + 与轨迹对齐的 toX（ms）；无 epoch 时返回 null */
function getAttitudeTooltipContext(overview, align) {
  const series = overview?.attitude_series
  if (!series?.time?.length) return null
  const fields = [
    { key: 'pitch', shortName: 'pitch', label: 'Pitch (°)', unit: '°' },
    { key: 'roll', shortName: 'roll', label: 'Roll (°)', unit: '°' },
    { key: 'yaw', shortName: 'yaw', label: 'Yaw (°)', unit: '°' },
  ].filter((f) => Array.isArray(series[f.key]) && series[f.key].some((v) => v != null && Number.isFinite(v)))
  if (!fields.length) return null
  const epoch = series.time_epoch
  const useEpoch = Array.isArray(epoch) && epoch.length === series.time.length && epoch.some((v) => Number.isFinite(Number(v)))
  if (!useEpoch) return null
  const offSec = (align?.parseOffsetMs || 0) / 1000
  const toX = (idx) => {
    const v = epoch[idx]
    return Number.isFinite(v) ? (v + offSec) * 1000 : null
  }
  return { series, fields, toX }
}

/**
 * 剖面 / 姿态 共用悬停读数：北京时间、累计航程、经纬度、高度、各姿态角（轨迹点按时间最近，姿态点按降采样最近）
 */
function formatWorkbenchProfileAttitudeTooltipHtml(tMs, trajData, altColumn, attitudeSeries, attitudeFields, toX) {
  const { distM, altVals, tSec, path } = trajData
  const { idx: i } = nearestTrajIndexFromAxisMs(tSec, tMs)
  const bjFull = Number.isFinite(tSec[i])
    ? (numericToBeijingWallClock(tSec[i] * 1000) || '—')
    : '—'
  const km = distM?.[i] != null ? (distM[i] / 1000).toFixed(3) : '—'
  const lo = path[i]?.[0]
  const la = path[i]?.[1]
  const alt = altVals?.[i]
  const altStr = alt != null && Number.isFinite(alt) ? Number(alt).toFixed(2) : '—'
  const loStr = lo != null ? Number(lo).toFixed(6) : '—'
  const laStr = la != null ? Number(la).toFixed(6) : '—'

  const parts = [
    `<div style="font-weight:600;margin-bottom:6px;color:#fef08a">时间（北京） ${bjFull}</div>`,
    `<div>累计航程 <strong>${km}</strong> km</div>`,
    `<div>经度 <strong>${loStr}</strong>°　纬度 <strong>${laStr}</strong>°</div>`,
  ]
  if (altColumn) {
    parts.push(`<div>${altColumn} <strong>${altStr}</strong></div>`)
  }

  if (attitudeSeries && attitudeFields?.length && toX) {
    const len = attitudeSeries.time?.length || 0
    const k = nearestAttitudeIndexFromAxisMs(tMs, toX, len)
    attitudeFields.forEach((f) => {
      const arr = attitudeSeries[f.key]
      const v = arr?.[k]
      const unit = f.unit || '°'
      parts.push(`<div>${f.shortName} <strong>${v != null && Number.isFinite(v) ? Number(v).toFixed(3) : '—'}</strong> ${unit}</div>`)
    })
  }

  return parts.join('')
}

/** 将 Unix 秒或毫秒转为 Asia/Shanghai 本地化时间字符串 */
function numericToBeijingWallClock(v) {
  if (!Number.isFinite(v)) return null
  const ms = Math.abs(v) > 1e11 ? v : v * 1000
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/**
 * 采样点北京时间：优先解析结果中的时间列（字符串或 Unix），否则用解析时间戳 tv（秒）换算。
 */
function formatSampleBeijingTime(raw, fallbackUnixSec) {
  if (raw != null && raw !== '') {
    if (typeof raw === 'number' && Number.isFinite(raw)) {
      const s = numericToBeijingWallClock(raw)
      if (s) return s
    }
    const str = String(raw).trim()
    if (str) {
      const dj = dayjs(str)
      if (dj.isValid()) return dj.format('YYYY-MM-DD HH:mm:ss')
      const n = Number(str)
      if (Number.isFinite(n)) {
        const s = numericToBeijingWallClock(n)
        if (s) return s
      }
      return str
    }
  }
  if (fallbackUnixSec != null && Number.isFinite(fallbackUnixSec)) {
    const s = numericToBeijingWallClock(fallbackUnixSec)
    if (s) return s
  }
  return '—'
}

/** 解析结果中与「北京时间 / 本地时刻」相关的列名 */
function resolveBeijingWallClockColumn(columns) {
  if (!columns?.length) return null
  const geo = /^latitude|^longitude|^lat$|^lon$/i
  const pool = columns.filter((c) => !geo.test(String(c)))
  const pref = [
    'BeijingDateTime', 'beijing_datetime', 'beijing_time', 'GPSBeijingTime', 'gps_beijing_time',
    'utc_time', 'gps_time', 'packet_time', 'sensor_time',
  ]
  for (const p of pref) {
    const hit = pool.find((c) => String(c).toLowerCase() === p.toLowerCase())
    if (hit) return hit
  }
  const hit = pool.find((c) => {
    const s = String(c)
    return /beijing|北京时间|本地时刻/.test(s) && !/latitude|longitude|lat|lon/i.test(s)
  })
  return hit || null
}

/** 惯导故障时常见占位 (0°,0°)；用微小容差避免浮点抖动 */
function isNearZeroOrigin(lon, lat) {
  const e = 1e-6
  return Math.abs(Number(lon)) < e && Math.abs(Number(lat)) < e
}

/** 从 path 重算累积距离（米），与 loadTrajectory 中逻辑一致 */
function recomputeTrajectoryDistM(path) {
  const distM = []
  let prevLL = null
  for (let i = 0; i < path.length; i += 1) {
    const [lo, la] = path[i]
    let cum = 0
    if (i === 0) cum = 0
    else if (prevLL) cum = distM[i - 1] + haversineMeters(prevLL[0], prevLL[1], lo, la)
    prevLL = [lo, la]
    distM.push(cum)
  }
  return distM
}

/**
 * 去掉开头连续接近 (0,0) 的采样；仅影响从记录起点起的故障段。
 * 若全部为 (0,0) 则返回 null。
 */
function stripLeadingZeroOriginTraj(traj) {
  const { path } = traj
  if (!path?.length) return null
  let k = 0
  while (k < path.length && isNearZeroOrigin(path[k][0], path[k][1])) k += 1
  if (k === 0) return traj
  if (k >= path.length) return null
  const rest = (arr) => arr.slice(k)
  const path2 = rest(path)
  return {
    ...traj,
    path: path2,
    tSec: rest(traj.tSec),
    latVals: rest(traj.latVals),
    speedVals: rest(traj.speedVals),
    altVals: rest(traj.altVals),
    eastVals: traj.eastVals ? rest(traj.eastVals) : undefined,
    northVals: traj.northVals ? rest(traj.northVals) : undefined,
    pitchVals: traj.pitchVals ? rest(traj.pitchVals) : undefined,
    rollVals: traj.rollVals ? rest(traj.rollVals) : undefined,
    yawVals: traj.yawVals ? rest(traj.yawVals) : undefined,
    groundSpeedVals: traj.groundSpeedVals ? rest(traj.groundSpeedVals) : undefined,
    beijingTimeStrs: traj.beijingTimeStrs ? rest(traj.beijingTimeStrs) : undefined,
    distM: recomputeTrajectoryDistM(path2),
  }
}

/** 东/北单向速度列名，不作为「综合速度」列（地速由 hypot(东,北) 或专用标量列提供） */
function isEnuAxisVelocityColumn(name) {
  const s = String(name).toLowerCase()
  if (/east_velocity|velocity_east|north_velocity|velocity_north|east_vel|north_vel/.test(s)) return true
  if (/^vel_[en]$|^v_[en]$|^speed_[en]$/.test(s)) return true
  if (/vned_[en]/.test(s)) return true
  if (/(东向|北向).*(速|vel|rate)/i.test(String(name))) return true
  return false
}

/** 仅从解析结果 columns 中选取标量速度/地速字段名（不含 ENU 单轴列，避免误把东向分量当地速） */
function resolveSpeedColumn(columns) {
  if (!columns?.length) return null
  const pref = [
    'ground_speed', 'groundspeed', 'gps_speed', 'speed_x', 'speed_y',
    'speed', 'gps_speed_ms', 'velocity', 'nav_speed', 'true_airspeed', 'airspeed',
  ]
  const geo = /^latitude|^longitude|^lat$|^lon$/i
  const pool = columns.filter((c) => !geo.test(String(c)) && !isEnuAxisVelocityColumn(c))
  for (const p of pref) {
    const hit = pool.find((c) => String(c).toLowerCase() === p.toLowerCase())
    if (hit) return hit
  }
  const kw = /speed|velocity|vel|地速|速率/i
  const hit = pool.find((c) => kw.test(String(c)) && !isEnuAxisVelocityColumn(c))
  return hit || null
}

/** 仅从解析结果 columns 中选取高度字段名（不存在则返回 null） */
function resolveAltColumn(columns) {
  if (!columns?.length) return null
  const pref = [
    'altitude', 'gps_altitude', 'height', 'gps_height', 'msl_altitude',
    'relative_altitude', 'pressure_altitude', 'geo_altitude', 'alt_m', 'altitude_m',
  ]
  const geo = /^latitude|^longitude|^lat$|^lon$/i
  const pool = columns.filter((c) => !geo.test(String(c)))
  for (const p of pref) {
    const hit = pool.find((c) => String(c).toLowerCase() === p.toLowerCase())
    if (hit) return hit
  }
  const kw = /altitude|height|alt|海拔|高度|msl|气压高/i
  const hit = pool.find((c) => kw.test(String(c)) && !/(speed|velocity)/i.test(String(c)))
  return hit || null
}

/** 东向速度列（ENU） */
function resolveEastVelocityColumn(columns) {
  if (!columns?.length) return null
  const geo = /^latitude|^longitude|^lat$|^lon$/i
  const pool = columns.filter((c) => !geo.test(String(c)))
  const pref = [
    'east_velocity', 'velocity_east', 'east_vel', 'vel_e', 'v_e', 'speed_e', 'vned_e', 've',
    'navigation_velocity_east', 'nav_velocity_east', 'nav_ve', 'velocity_e', 'speed_east', 'v_east',
  ]
  for (const p of pref) {
    const hit = pool.find((c) => String(c).toLowerCase() === p.toLowerCase())
    if (hit) return hit
  }
  const hit = pool.find((c) => {
    const s = String(c).toLowerCase()
    return /east|东向/.test(s) && /vel|speed|速率/.test(s) && !/north|北/.test(s)
  })
  return hit || null
}

/** 北向速度列（ENU） */
function resolveNorthVelocityColumn(columns) {
  if (!columns?.length) return null
  const geo = /^latitude|^longitude|^lat$|^lon$/i
  const pool = columns.filter((c) => !geo.test(String(c)))
  const pref = [
    'north_velocity', 'velocity_north', 'north_vel', 'vel_n', 'v_n', 'speed_n', 'vned_n', 'vn',
    'navigation_velocity_north', 'nav_velocity_north', 'nav_vn', 'velocity_n', 'speed_north', 'v_north',
  ]
  for (const p of pref) {
    const hit = pool.find((c) => String(c).toLowerCase() === p.toLowerCase())
    if (hit) return hit
  }
  const hit = pool.find((c) => {
    const s = String(c).toLowerCase()
    return (/north|北向/.test(s) || /^vn$/i.test(String(c))) && /vel|speed|速率/.test(s) && !/east|东/.test(s)
  })
  return hit || null
}

/** 前端兜底：列名匹配 pitch */
function resolvePitchColumn(columns) {
  if (!columns?.length) return null
  const low = columns.map((c) => String(c).toLowerCase())
  const i = low.findIndex((c) => c === 'pitch')
  if (i >= 0) return columns[i]
  const kw = /pitch|俯仰|ptch/i
  return columns.find((c) => kw.test(String(c))) || null
}

/** 前端兜底：列名匹配 roll */
function resolveRollColumn(columns) {
  if (!columns?.length) return null
  const low = columns.map((c) => String(c).toLowerCase())
  const i = low.findIndex((c) => c === 'roll')
  if (i >= 0) return columns[i]
  const kw = /roll|滚转|bank/i
  return (
    columns.find((c) => {
      const s = String(c).toLowerCase()
      return kw.test(String(c)) && !s.includes('rate')
    }) || null
  )
}

/** 前端兜底：列名匹配 yaw/heading */
function resolveYawColumn(columns) {
  if (!columns?.length) return null
  const low = columns.map((c) => String(c).toLowerCase())
  const i = low.findIndex((c) => c === 'heading' || c === 'yaw' || c === 'psi' || c === 'hdg')
  if (i >= 0) return columns[i]
  const kw = /yaw|heading|航向|偏航|psi|hdg/i
  return columns.find((c) => kw.test(String(c))) || null
}

const QUALITY_COLOR = {
  Good: 'success',
  'Minor Issues': 'processing',
  Warning: 'warning',
  Critical: 'error',
}

function QualityBadge({ quality }) {
  const status = QUALITY_COLOR[quality] || 'default'
  return <Badge status={status} text={<Text strong>质量：{quality || '未知'}</Text>} />
}

function WorkbenchPicker() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [tree, setTree] = useState([])
  const [selectedKeys, setSelectedKeys] = useState([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await sharedTsnApi.listSorties()
      setTree(res.data || [])
    } catch {
      setTree([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const rows = useMemo(() => {
    const out = []
    for (const s of tree) {
      if (!s.id || s.id <= 0) continue
      out.push({
        key: s.id,
        id: s.id,
        label: s.sortie_label,
        date: s.experiment_date,
        fileCount: (s.files || []).length,
      })
    }
    return out
  }, [tree])

  const columns = [
    { title: '架次', dataIndex: 'label', ellipsis: true },
    { title: '试验日期', dataIndex: 'date', width: 140, render: (t) => t || '—' },
    { title: '文件数', dataIndex: 'fileCount', width: 90 },
    {
      title: '操作',
      key: 'op',
      width: 140,
      render: (_, r) => (
        <Button type="primary" size="small" onClick={() => navigate(`/workbench/${r.id}`)}>
          进入工作台
        </Button>
      ),
    },
  ]

  const goCompare = () => {
    if (!selectedKeys.length) return
    navigate(`/workbench/compare?sortieIds=${selectedKeys.join(',')}`)
  }

  return (
    <div className="fade-in">
      <Card
        title={<><AimOutlined style={{ marginRight: 8 }} />试验工作台</>}
        extra={(
          <Space>
            <Button
              icon={<SwapOutlined />}
              disabled={selectedKeys.length < 2}
              onClick={goCompare}
            >
              对比所选架次（{selectedKeys.length}）
            </Button>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新架次</Button>
          </Space>
        )}
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          选择一个<strong>试验架次</strong>进入工作台查看总览/轨迹/视频/事件分析；
          在表格左侧勾选多行后点击<strong>对比所选架次</strong>可进入跨架次对比页。
          经纬度轨迹需先在「任务列表」中完成与本试验相关的<strong>解析任务</strong>（包含惯导端口）。
        </Text>
        <Table
          rowKey="key"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={rows}
          rowSelection={{
            selectedRowKeys: selectedKeys,
            onChange: (keys) => setSelectedKeys(keys),
          }}
          pagination={{ pageSize: 12 }}
          locale={{ emptyText: '暂无试验架次，请管理员在「平台共享数据」中新建架次并上传数据' }}
        />
      </Card>
    </div>
  )
}

function WorkbenchDetail({ sortieId }) {
  const navigate = useNavigate()
  const [detailLoading, setDetailLoading] = useState(true)
  const [detail, setDetail] = useState(null)
  const [tasks, setTasks] = useState([])
  const [taskId, setTaskId] = useState(null)
  const [taskDetail, setTaskDetail] = useState(null)
  const [irsKey, setIrsKey] = useState(null)
  const [trajLoading, setTrajLoading] = useState(false)
  const [trajDataRaw, setTrajDataRaw] = useState(null)
  const [omitZeroOrigin, setOmitZeroOrigin] = useState(false)
  const [selectedTrajIdx, setSelectedTrajIdx] = useState(null)
  const [matched, setMatched] = useState(null)
  const [overview, setOverview] = useState(null)
  const [overviewLoading, setOverviewLoading] = useState(false)
  const [eventsSummary, setEventsSummary] = useState(null)
  const [eventsLoading, setEventsLoading] = useState(false)

  const leadingZeroOriginCount = useMemo(() => {
    if (!trajDataRaw?.path?.length) return 0
    const { path } = trajDataRaw
    let k = 0
    while (k < path.length && isNearZeroOrigin(path[k][0], path[k][1])) k += 1
    return k
  }, [trajDataRaw])

  const trajData = useMemo(() => {
    if (!trajDataRaw?.path?.length) return null
    if (!omitZeroOrigin) return trajDataRaw
    return stripLeadingZeroOriginTraj(trajDataRaw)
  }, [trajDataRaw, omitZeroOrigin])

  const [align, setAlign] = useState(() => loadAlignment(sortieId))
  const [videoPanes, setVideoPanes] = useState(() => {
    const saved = loadVideoTabsState(sortieId)
    if (saved?.panes?.length) return saved.panes.map(normalizeVideoPane)
    return [{
      key: '1',
      label: '视图 1',
      layout: 'single',
      singleId: null,
      multiIds: Array(VIDEO_MULTI_SLOTS).fill(null),
      columnCount: 3,
    }]
  })
  const [videoTabActiveKey, setVideoTabActiveKey] = useState(() => {
    const saved = loadVideoTabsState(sortieId)
    if (saved?.activeKey && saved?.panes?.some((p) => p.key === saved.activeKey)) {
      return saved.activeKey
    }
    return '1'
  })
  const [fs, setFs] = useState(false)
  /** 姿态时序：与解析结果页一致的「叠加 / 并列」布局 */
  const [attitudeChartLayout, setAttitudeChartLayout] = useState('overlay')
  const wrapRef = useRef(null)
  const videoElsRef = useRef({})
  /** 每个 fileId 对应 stable ref，避免每次 render 新建函数导致 <video> 反复挂载并死循环 */
  const videoRefCallbacks = useRef(new Map())
  const trajAltChartRef = useRef(null)
  const attitudeChartRef = useRef(null)
  /** 垂直剖面 + 姿态叠加合并为一张图时使用 */
  const mergedProfileAttitudeRef = useRef(null)
  /** 架次总览「物理异常」行点击后滚动定位到页面底部「事件分析总结」 */
  const eventsSummarySectionRef = useRef(null)

  useEffect(() => {
    setAttitudeChartLayout('overlay')
  }, [taskId])

  useEffect(() => {
    setSelectedTrajIdx(null)
  }, [omitZeroOrigin])

  const token = typeof window !== 'undefined' ? localStorage.getItem(TOKEN_KEY) : ''

  const loadDetail = useCallback(async () => {
    setDetailLoading(true)
    try {
      const res = await workbenchApi.getSortie(sortieId)
      setDetail(res.data)
    } catch {
      setDetail(null)
      message.error('加载架次失败')
    } finally {
      setDetailLoading(false)
    }
  }, [sortieId])

  const loadTasks = useCallback(async () => {
    try {
      const res = await parseApi.listTasks(1, 200)
      const items = (res.data.items || []).filter((t) => t.status === 'completed')
      setTasks(items)
    } catch {
      setTasks([])
    }
  }, [])

  const loadMatched = useCallback(async () => {
    if (!sortieId) return
    try {
      const res = await workbenchApi.listMatchedTasks(sortieId)
      setMatched(res.data || null)
    } catch {
      setMatched(null)
    }
  }, [sortieId])

  useEffect(() => { loadDetail() }, [loadDetail])
  useEffect(() => { loadTasks() }, [loadTasks])
  useEffect(() => { loadMatched() }, [loadMatched])

  useEffect(() => {
    if (!taskId && matched?.parse_tasks?.length) {
      const first = matched.parse_tasks[0]?.parse_task_id
      if (first) setTaskId(first)
    }
  }, [matched, taskId])

  const loadOverview = useCallback(async (tid) => {
    if (!tid) { setOverview(null); return }
    setOverviewLoading(true)
    try {
      const res = await workbenchApi.getOverview(sortieId, tid)
      setOverview(res.data || null)
    } catch {
      setOverview(null)
      message.error('加载架次总览失败')
    } finally {
      setOverviewLoading(false)
    }
  }, [sortieId])

  const loadEventsSummary = useCallback(async (tid) => {
    if (!tid) { setEventsSummary(null); return }
    setEventsLoading(true)
    try {
      const res = await workbenchApi.getEventsSummary(sortieId, tid)
      setEventsSummary(res.data || null)
    } catch {
      setEventsSummary(null)
    } finally {
      setEventsLoading(false)
    }
  }, [sortieId])

  useEffect(() => {
    loadOverview(taskId)
    loadEventsSummary(taskId)
  }, [taskId, loadOverview, loadEventsSummary])

  useEffect(() => {
    setAlign(loadAlignment(sortieId))
  }, [sortieId])

  useEffect(() => {
    videoRefCallbacks.current = new Map()
    videoElsRef.current = {}
  }, [sortieId])

  const patchAlign = useCallback((patchOrFn) => {
    setAlign((prev) => {
      const next = typeof patchOrFn === 'function' ? patchOrFn(prev) : { ...prev, ...patchOrFn }
      saveAlignment(sortieId, next)
      return next
    })
  }, [sortieId])

  useEffect(() => {
    if (!taskId) {
      setTaskDetail(null)
      return undefined
    }
    let cancelled = false
    ;(async () => {
      try {
        const res = await parseApi.getTask(taskId)
        if (!cancelled) setTaskDetail(res.data)
      } catch {
        if (!cancelled) setTaskDetail(null)
      }
    })()
    return () => { cancelled = true }
  }, [taskId])

  const irsOptions = useMemo(() => {
    const results = taskDetail?.results || []
    const picked = pickIrsResults(results)
    return picked.map((r) => {
      const key = `${r.port_number}|${r.parser_profile_id ?? ''}`
      return { value: key, label: formatIrsLabel(r), raw: r }
    })
  }, [taskDetail])

  useEffect(() => {
    if (!irsOptions.length) {
      setIrsKey(null)
      setTrajDataRaw(null)
      setOmitZeroOrigin(false)
      setSelectedTrajIdx(null)
      return
    }
    if (!irsKey || !irsOptions.some((o) => o.value === irsKey)) {
      const primary = overview?.primary_irs
      const preferred = primary
        ? irsOptions.find((o) => (
            o.raw?.port_number === primary.port
              && (primary.parser_id == null || o.raw?.parser_profile_id === primary.parser_id)
          ))
        : null
      setIrsKey((preferred || irsOptions[0]).value)
    }
  }, [irsOptions, irsKey, overview])

  const loadTrajectory = useCallback(async () => {
    if (!taskId || !irsKey) return
    const opt = irsOptions.find((o) => o.value === irsKey)
    const port = opt?.raw?.port_number
    const parserId = opt?.raw?.parser_profile_id
    if (port == null) return
    setTrajLoading(true)
    try {
      const listParams = { page: 1, page_size: 8 }
      if (parserId != null) listParams.parser_id = parserId
      let columns = []
      try {
        const metaRes = await parseApi.getData(taskId, port, { params: listParams })
        columns = metaRes.data?.columns || []
      } catch {
        columns = []
      }
      const speedCol = resolveSpeedColumn(columns)
      const altCol = resolveAltColumn(columns)
      const eastVelCol = resolveEastVelocityColumn(columns)
      const northVelCol = resolveNorthVelocityColumn(columns)
      const beijingWallCol = resolveBeijingWallClockColumn(columns)
      const pitchCol = resolvePitchColumn(columns)
      const rollCol = resolveRollColumn(columns)
      const yawCol = resolveYawColumn(columns)

      const params = { max_points: 8000 }
      if (parserId != null) params.parser_id = parserId

      const uniqueVarCols = [...new Set([
        speedCol, altCol, eastVelCol, northVelCol, beijingWallCol,
        pitchCol, rollCol, yawCol,
      ].filter(Boolean))]
      const seriesReq = [
        parseApi.getTimeSeries(taskId, port, 'latitude', { params: { ...params } }),
        parseApi.getTimeSeries(taskId, port, 'longitude', { params: { ...params } }),
        ...uniqueVarCols.map((col) => parseApi.getTimeSeries(taskId, port, col, { params: { ...params } })),
      ]

      const seriesRes = await Promise.all(seriesReq)
      const latR = seriesRes[0]
      const lonR = seriesRes[1]
      const varByCol = {}
      uniqueVarCols.forEach((col, i) => {
        varByCol[col] = seriesRes[2 + i]
      })

      const spdR = speedCol ? varByCol[speedCol] : null
      const altR = altCol ? varByCol[altCol] : null
      const eastR = eastVelCol ? varByCol[eastVelCol] : null
      const northR = northVelCol ? varByCol[northVelCol] : null
      const bjR = beijingWallCol ? varByCol[beijingWallCol] : null
      const pitchR = pitchCol ? varByCol[pitchCol] : null
      const rollR = rollCol ? varByCol[rollCol] : null
      const yawR = yawCol ? varByCol[yawCol] : null

      const ts = latR.data.timestamps || []
      const lat = latR.data.values || []
      const lon = lonR.data.values || []
      const spd = spdR ? (spdR.data.values || []) : []
      const alt = altR ? (altR.data.values || []) : []
      const eastRaw = eastR ? (eastR.data.values || []) : []
      const northRaw = northR ? (northR.data.values || []) : []
      const bjRaw = bjR ? (bjR.data.values || []) : []
      const pitchRaw = pitchR ? (pitchR.data.values || []) : []
      const rollRaw = rollR ? (rollR.data.values || []) : []
      const yawRaw = yawR ? (yawR.data.values || []) : []

      const lens = [ts.length, lat.length, lon.length]
      uniqueVarCols.forEach((col) => {
        const vals = varByCol[col]?.data?.values || []
        lens.push(vals.length)
      })
      const n = Math.min(...lens)

      const off = (align.parseOffsetMs || 0) / 1000
      const path = []
      const tSec = []
      const latVals = []
      const speedVals = []
      const altVals = []
      const eastVals = []
      const northVals = []
      const pitchVals = []
      const rollVals = []
      const yawVals = []
      const parserGroundSpeedVals = []
      const beijingTimeStrs = []
      const distM = []
      let prevLL = null
      for (let i = 0; i < n; i += 1) {
        const la = lat[i]
        const lo = lon[i]
        const tv = ts[i]
        if (la == null || lo == null || Number.isNaN(la) || Number.isNaN(lo) || tv == null) continue
        let cum = 0
        if (path.length === 0) {
          cum = 0
        } else if (prevLL) {
          cum = distM[distM.length - 1] + haversineMeters(prevLL[0], prevLL[1], lo, la)
        }
        prevLL = [lo, la]
        path.push([lo, la])
        tSec.push(tv + off)
        latVals.push(la)
        speedVals.push(speedCol ? parseSeriesNumber(spd[i]) : null)
        altVals.push(altCol ? parseSeriesNumber(alt[i]) : null)
        const ve = eastVelCol ? parseSeriesNumber(eastRaw[i]) : null
        const vn = northVelCol ? parseSeriesNumber(northRaw[i]) : null
        const sv = speedVals[speedVals.length - 1]
        let gs = null
        if (ve != null && vn != null && Number.isFinite(ve) && Number.isFinite(vn)) {
          gs = Math.hypot(ve, vn)
        } else if (sv != null && Number.isFinite(sv)) {
          gs = sv
        }
        eastVals.push(ve)
        northVals.push(vn)
        pitchVals.push(pitchCol ? parseSeriesNumber(pitchRaw[i]) : null)
        rollVals.push(rollCol ? parseSeriesNumber(rollRaw[i]) : null)
        yawVals.push(yawCol ? parseSeriesNumber(yawRaw[i]) : null)
        parserGroundSpeedVals.push(gs)
        const rawBj = beijingWallCol ? bjRaw[i] : null
        beijingTimeStrs.push(formatSampleBeijingTime(rawBj, tv))
        distM.push(cum)
      }
      const groundSpeedVals = finalizeGroundSpeedValsForMap(path, tSec, parserGroundSpeedVals)
      setSelectedTrajIdx(null)
      setOmitZeroOrigin(false)
      setTrajDataRaw(path.length ? {
        path,
        tSec,
        latVals,
        speedVals,
        altVals,
        eastVals,
        northVals,
        pitchVals,
        rollVals,
        yawVals,
        groundSpeedVals,
        beijingTimeStrs,
        distM,
        speedColumn: speedCol,
        altColumn: altCol,
        eastVelocityColumn: eastVelCol,
        northVelocityColumn: northVelCol,
        beijingWallClockColumn: beijingWallCol,
        pitchColumn: pitchCol,
        rollColumn: rollCol,
        yawColumn: yawCol,
      } : null)
    } catch {
      message.error('加载惯导轨迹失败')
      setTrajDataRaw(null)
      setOmitZeroOrigin(false)
      setSelectedTrajIdx(null)
    } finally {
      setTrajLoading(false)
    }
  }, [taskId, irsKey, irsOptions, align.parseOffsetMs])

  useEffect(() => {
    loadTrajectory()
  }, [loadTrajectory])

  const trajAltOption = useMemo(() => {
    if (!trajData?.path?.length || !trajData.altColumn) return null
    const { distM, altVals, altColumn, tSec, path } = trajData
    if (!tSec?.length || !altVals?.some((a) => a != null && Number.isFinite(a))) return null
    // x = 北京时间（基于 UTC epoch 秒转 ms），y = 高度
    const pts = []
    for (let i = 0; i < path.length; i += 1) {
      const a = altVals[i]
      const tv = tSec[i]
      if (a == null || !Number.isFinite(a) || !Number.isFinite(tv)) continue
      pts.push([tv * 1000, a, i])
    }
    if (!pts.length) return null
    const finAlts = altVals.filter((x) => x != null && Number.isFinite(x))
    const aMin = Math.min(...finAlts)
    const aMax = Math.max(...finAlts)
    const xSel = selectedTrajIdx != null && Number.isFinite(tSec[selectedTrajIdx])
      ? tSec[selectedTrajIdx] * 1000
      : null
    const markLine = xSel != null
      ? {
        symbol: 'none',
        label: { formatter: '选中', color: '#facc15', fontSize: 10 },
        lineStyle: { color: '#facc15', type: 'dashed' },
        data: [{ xAxis: xSel }],
      }
      : undefined
    return {
      backgroundColor: 'transparent',
      title: {
        text: `垂直剖面：${altColumn} — 时间（北京）`,
        left: 'center',
        top: 4,
        textStyle: { fontSize: 12, color: '#9ca3af', fontWeight: 'normal' },
      },
      tooltip: {
        trigger: 'axis',
        formatter: (items) => {
          const it = items?.[0]
          if (!it) return ''
          const row = it.data
          const idx = Array.isArray(row) ? row[2] : it.dataIndex
          const i = typeof idx === 'number' ? idx : 0
          const t = tSec[i]
          const tMs = Number.isFinite(t) ? t * 1000 : null
          const attCtx = getAttitudeTooltipContext(overview, align)
          if (tMs != null && attCtx) {
            return formatWorkbenchProfileAttitudeTooltipHtml(
              tMs,
              trajData,
              altColumn,
              attCtx.series,
              attCtx.fields,
              attCtx.toX,
            )
          }
          const lo = path[i]?.[0]
          const la = path[i]?.[1]
          const alt = altVals[i]
          const km = distM?.[i] != null ? (distM[i] / 1000).toFixed(3) : '—'
          const bjFull = numericToBeijingWallClock(t * 1000) || '—'
          return `时间 ${bjFull}<br/>${altColumn}: ${alt != null ? Number(alt).toFixed(2) : '—'}<br/>累计航程 ${km} km<br/>经度 ${lo != null ? Number(lo).toFixed(6) : '—'}° 纬度 ${la != null ? Number(la).toFixed(6) : '—'}°`
        },
      },
      grid: { left: 56, right: 18, top: 40, bottom: 64 },
      xAxis: {
        type: 'time',
        name: '时间（北京）',
        axisPointer: { snap: true },
        axisLabel: {
          color: '#a1a1aa',
          hideOverlap: true,
          rotate: 30,
          formatter: (v) => beijingHmsFromMs(v),
        },
        axisLine: { lineStyle: { color: '#27272a' } },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        name: altColumn,
        min: aMin,
        max: aMax,
        axisLabel: { color: '#a1a1aa' },
        axisLine: { lineStyle: { color: '#27272a' } },
        splitLine: { lineStyle: { color: '#27272a' } },
      },
      dataZoom: WORKBENCH_CHART_DATA_ZOOM,
      series: [{
        type: 'line',
        name: altColumn,
        large: true,
        showSymbol: false,
        lineStyle: { color: '#34d399', width: 1.5 },
        data: pts,
        markLine,
      }],
    }
  }, [trajData, selectedTrajIdx, overview, align])

  const attitudeChart = useMemo(() => {
    const series = overview?.attitude_series
    if (!series?.time?.length) return null
    const baseFields = [
      { key: 'pitch', label: 'Pitch (°)', shortName: 'pitch', color: '#60a5fa', unit: '°', source: 'attitude' },
      { key: 'roll', label: 'Roll (°)', shortName: 'roll', color: '#34d399', unit: '°', source: 'attitude' },
      { key: 'yaw', label: 'Yaw (°)', shortName: 'yaw', color: '#fbbf24', unit: '°', source: 'attitude' },
    ].filter((f) => Array.isArray(series[f.key]) && series[f.key].some((v) => v != null && Number.isFinite(v)))
    const hasTrajAltitude = !!(
      trajData?.altColumn
      && trajData?.tSec?.length
      && trajData?.altVals?.some((v) => v != null && Number.isFinite(v))
    )
    const altitudeField = hasTrajAltitude
      ? { key: '_traj_altitude', label: `${trajData.altColumn} (m)`, shortName: 'altitude', color: '#f97316', unit: 'm', source: 'trajectory' }
      : null
    const fields = altitudeField ? [...baseFields, altitudeField] : baseFields
    if (!fields.length) return null

    const epoch = series.time_epoch
    const useEpoch = Array.isArray(epoch) && epoch.length === series.time.length && epoch.some((v) => Number.isFinite(v))
    // 与垂直剖面 / 地图轨迹一致：X 轴使用「解析 UTC + 本页时间对齐偏移」，与 trajData.tSec 同口径
    const offSec = (align.parseOffsetMs || 0) / 1000
    const toX = (i) => {
      if (useEpoch) {
        const v = epoch[i]
        return Number.isFinite(v) ? (v + offSec) * 1000 : null
      }
      const v = series.time[i]
      return Number.isFinite(v) ? v : null
    }
    const fieldPoints = (f) => {
      if (f.source === 'trajectory') {
        if (!trajData?.tSec?.length || !trajData?.altVals?.length) return []
        const pts = []
        for (let i = 0; i < trajData.tSec.length; i += 1) {
          const tv = trajData.tSec[i]
          const av = trajData.altVals[i]
          if (!Number.isFinite(tv) || av == null || !Number.isFinite(av)) continue
          pts.push([tv * 1000, av])
        }
        return pts
      }
      return series[f.key]
        .map((v, k) => [toX(k), v])
        .filter((p) => p[0] != null && p[1] != null && Number.isFinite(p[1]))
    }

    const markLine = (() => {
      if (selectedTrajIdx == null || !Number.isFinite(trajData?.tSec?.[selectedTrajIdx])) return undefined
      if (!useEpoch) return undefined
      const xVal = trajData.tSec[selectedTrajIdx] * 1000
      return {
        symbol: 'none',
        label: { formatter: '选中', color: '#facc15', fontSize: 10, distance: 8 },
        lineStyle: { color: '#facc15', type: 'dashed' },
        data: [{ xAxis: xVal }],
      }
    })()

    const fmtYTick = (value) => {
      const n = Number(value)
      if (!Number.isFinite(n)) return String(value ?? '')
      const v3 = n.toFixed(3)
      return v3.endsWith('0') ? n.toFixed(2) : v3
    }

    const xAxisBase = {
      type: useEpoch ? 'time' : 'value',
      axisPointer: useEpoch ? { snap: true } : {},
      axisLabel: {
        color: '#a1a1aa',
        hideOverlap: true,
        rotate: 30,
        formatter: (v) => (useEpoch ? beijingHmsFromMs(v) : Number(v).toFixed(0)),
      },
      axisLine: { lineStyle: { color: '#27272a' } },
      splitLine: { show: false },
    }

    const canToggleLayout = fields.length >= 2

    if (attitudeChartLayout === 'overlay') {
      const pointsByField = {}
      fields.forEach((f) => {
        pointsByField[f.key] = fieldPoints(f)
      })

      const attitudeOnlyFields = fields.filter((f) => f.source !== 'trajectory')
      const altitudeOnlyField = fields.find((f) => f.source === 'trajectory')
      const hasAltitudeSeries = !!altitudeOnlyField
      let yAxis
      let chartSeries
      if (hasAltitudeSeries && !attitudeOnlyFields.length) {
        const altNums = trajData.altVals.filter((v) => v != null && Number.isFinite(v))
        const altMin = Math.min(...altNums)
        const altMax = Math.max(...altNums)
        yAxis = {
          type: 'value',
          name: altitudeOnlyField.shortName,
          min: altMin,
          max: altMax,
          nameTextStyle: { color: '#a1a1aa', fontSize: 11 },
          axisLabel: { color: '#a1a1aa', formatter: fmtYTick },
          axisLine: { lineStyle: { color: '#27272a' } },
          splitLine: { lineStyle: { color: '#27272a' } },
        }
        chartSeries = fields.map((f, i) => ({
          name: f.shortName,
          type: 'line',
          xAxisIndex: 0,
          yAxisIndex: 0,
          smooth: true,
          showSymbol: false,
          sampling: 'lttb',
          lineStyle: { width: 1.5, color: f.color },
          itemStyle: { color: f.color },
          emphasis: { focus: 'series', lineStyle: { width: 2.5 } },
          data: pointsByField[f.key],
          markLine: i === 0 ? markLine : undefined,
        }))
      } else if (hasAltitudeSeries && attitudeOnlyFields.length) {
        const rAtt = computeWorkbenchAttitudeYRange(attitudeOnlyFields.map((f) => series[f.key]))
        const altNums = trajData.altVals.filter((v) => v != null && Number.isFinite(v))
        const altMin = Math.min(...altNums)
        const altMax = Math.max(...altNums)
        yAxis = [
          {
            type: 'value',
            name: 'attitude (°)',
            min: rAtt.min,
            max: rAtt.max,
            position: 'left',
            nameTextStyle: { color: '#a1a1aa', fontSize: 11 },
            axisLabel: { color: '#a1a1aa', formatter: fmtYTick },
            axisLine: { lineStyle: { color: '#27272a' } },
            splitLine: { lineStyle: { color: '#27272a' } },
          },
          {
            type: 'value',
            name: altitudeOnlyField.shortName,
            min: altMin,
            max: altMax,
            position: 'right',
            nameTextStyle: { color: '#a1a1aa', fontSize: 11 },
            axisLabel: { color: '#a1a1aa', formatter: fmtYTick },
            axisLine: { lineStyle: { color: '#27272a' } },
            splitLine: { show: false },
          },
        ]
        chartSeries = fields.map((f, i) => ({
          name: f.shortName,
          type: 'line',
          xAxisIndex: 0,
          yAxisIndex: f.source === 'trajectory' ? 1 : 0,
          smooth: true,
          showSymbol: false,
          sampling: 'lttb',
          lineStyle: { width: 1.5, color: f.color },
          itemStyle: { color: f.color },
          emphasis: { focus: 'series', lineStyle: { width: 2.5 } },
          data: pointsByField[f.key],
          markLine: i === 0 ? markLine : undefined,
        }))
      } else if (fields.length === 2) {
        const f0 = fields[0]
        const f1 = fields[1]
        const r0 = computeWorkbenchAttitudeYRange([series[f0.key]])
        const r1 = computeWorkbenchAttitudeYRange([series[f1.key]])
        yAxis = [
          {
            type: 'value',
            name: f0.shortName,
            min: r0.min,
            max: r0.max,
            position: 'left',
            nameTextStyle: { color: '#a1a1aa', fontSize: 11 },
            axisLabel: { color: '#a1a1aa', formatter: fmtYTick },
            axisLine: { lineStyle: { color: '#27272a' } },
            splitLine: { lineStyle: { color: '#27272a' } },
          },
          {
            type: 'value',
            name: f1.shortName,
            min: r1.min,
            max: r1.max,
            position: 'right',
            nameTextStyle: { color: '#a1a1aa', fontSize: 11 },
            axisLabel: { color: '#a1a1aa', formatter: fmtYTick },
            axisLine: { lineStyle: { color: '#27272a' } },
            splitLine: { show: false },
          },
        ]
        chartSeries = fields.map((f, i) => ({
          name: f.shortName,
          type: 'line',
          xAxisIndex: 0,
          yAxisIndex: i,
          smooth: true,
          showSymbol: false,
          sampling: 'lttb',
          lineStyle: { width: 1.5, color: f.color },
          itemStyle: { color: f.color },
          emphasis: { focus: 'series', lineStyle: { width: 2.5 } },
          data: pointsByField[f.key],
          markLine: i === 0 ? markLine : undefined,
        }))
      } else {
        const rAll = computeWorkbenchAttitudeYRange(fields.map((f) => series[f.key]))
        yAxis = {
          type: 'value',
          name: fields.length > 1 ? '°' : fields[0].shortName,
          min: rAll.min,
          max: rAll.max,
          nameTextStyle: { color: '#a1a1aa', fontSize: 11 },
          axisLabel: { color: '#a1a1aa', formatter: fmtYTick },
          axisLine: { lineStyle: { color: '#27272a' } },
          splitLine: { lineStyle: { color: '#27272a' } },
        }
        chartSeries = fields.map((f, i) => ({
          name: f.shortName,
          type: 'line',
          xAxisIndex: 0,
          yAxisIndex: 0,
          smooth: true,
          showSymbol: false,
          sampling: 'lttb',
          lineStyle: { width: 1.5, color: f.color },
          itemStyle: { color: f.color },
          emphasis: { focus: 'series', lineStyle: { width: 2.5 } },
          data: pointsByField[f.key],
          markLine: i === 0 ? markLine : undefined,
        }))
      }

      const rightPad = Array.isArray(yAxis) ? 52 : 22
      const option = {
        backgroundColor: 'transparent',
        legend: {
          data: fields.map((f) => f.shortName),
          textStyle: { color: '#a1a1aa' },
          top: 6,
        },
        tooltip: {
          trigger: 'axis',
          backgroundColor: '#0f0f12',
          borderColor: '#27272a',
          textStyle: { color: '#e4e4e7' },
          confine: true,
          appendToBody: true,
          axisPointer: {
            type: 'cross',
            snap: !!useEpoch,
            crossStyle: { color: '#a1a1aa' },
            lineStyle: { color: '#8b5cf6', type: 'dashed' },
            label: { backgroundColor: '#18181b', color: '#e4e4e7' },
          },
          formatter: (items) => {
            if (!items?.length) return ''
            const ax = items[0].axisValue
            if (useEpoch && trajData?.tSec?.length && trajData.altColumn) {
              return formatWorkbenchProfileAttitudeTooltipHtml(
                Number(ax),
                trajData,
                trajData.altColumn,
                series,
                fields,
                toX,
              )
            }
            const head = useEpoch
              ? (numericToBeijingWallClock(Number(ax)) || beijingHmsFromMs(ax))
              : `时间 ${Number(ax).toFixed(3)} s`
            const body = items.map((it) => {
              const v = Array.isArray(it.data) ? it.data[1] : it.value
              return `${it.marker}${it.seriesName}: ${v != null && Number.isFinite(v) ? Number(v).toFixed(3) : '—'}`
            }).join('<br/>')
            return `${head}<br/>${body}`
          },
        },
        grid: { left: 58, right: rightPad, top: 40, bottom: 64 },
        xAxis: { ...xAxisBase },
        yAxis,
        series: chartSeries,
        dataZoom: WORKBENCH_CHART_DATA_ZOOM,
      }
      return { option, chartHeight: 320, canToggleLayout }
    }

    // 并列：多子图 + 底部滑块联动所有 X 轴
    const n = fields.length
    const padTop = 12
    const padBottom = 56
    const rowGap = 44
    const rowInner = 148
    const leftPx = 88
    const rightPx = 28
    const chartHeight = padTop + n * rowInner + Math.max(0, n - 1) * rowGap + padBottom

    const grids = fields.map((_, i) => ({
      left: leftPx,
      right: rightPx,
      top: padTop + i * (rowInner + rowGap),
      height: rowInner,
      containLabel: false,
    }))

    const axisLabelStyle = { color: '#a1a1aa', fontSize: 11 }
    const splitStyle = { lineStyle: { color: '#27272a' } }
    const xAxisIndices = fields.map((_, i) => i)

    const option = {
      backgroundColor: 'transparent',
      legend: {
        data: fields.map((f) => f.shortName),
        textStyle: { color: '#a1a1aa' },
        top: 6,
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#0f0f12',
        borderColor: '#27272a',
        textStyle: { color: '#e4e4e7' },
        axisPointer: {
          type: 'cross',
          snap: !!useEpoch,
          crossStyle: { color: '#a1a1aa' },
          lineStyle: { color: '#8b5cf6', type: 'dashed' },
          label: { backgroundColor: '#18181b', color: '#e4e4e7' },
        },
        confine: true,
        appendToBody: true,
        formatter: (items) => {
          if (!items?.length) return ''
          const ax = items[0].axisValue
          if (useEpoch && trajData?.tSec?.length && trajData.altColumn) {
            return formatWorkbenchProfileAttitudeTooltipHtml(
              Number(ax),
              trajData,
              trajData.altColumn,
              series,
              fields,
              toX,
            )
          }
          const head = useEpoch
            ? (numericToBeijingWallClock(Number(ax)) || beijingHmsFromMs(ax))
            : `时间 ${Number(ax).toFixed(3)} s`
          const body = items.map((it) => {
            const v = Array.isArray(it.data) ? it.data[1] : it.value
            return `${it.marker}${it.seriesName}: ${v != null && Number.isFinite(v) ? Number(v).toFixed(3) : '—'}`
          }).join('<br/>')
          return `${head}<br/>${body}`
        },
      },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: grids,
      dataZoom: [
        { type: 'inside', xAxisIndex: xAxisIndices, start: 0, end: 100 },
        {
          type: 'slider',
          xAxisIndex: xAxisIndices,
          start: 0,
          end: 100,
          height: 20,
          bottom: 6,
          borderColor: '#27272a',
          backgroundColor: '#0f0f12',
          fillerColor: 'rgba(139, 92, 246, 0.2)',
          handleStyle: { color: '#8b5cf6' },
          textStyle: { color: '#a1a1aa' },
        },
      ],
      xAxis: fields.map((_, i) => {
        const isBottom = i === fields.length - 1
        return {
          ...xAxisBase,
          gridIndex: i,
          name: isBottom ? (useEpoch ? '时间（北京）' : '时间 (s)') : '',
          nameLocation: 'middle',
          nameGap: 30,
          nameTextStyle: { color: '#9ca3af', fontSize: 11, padding: [10, 0, 0, 0] },
          scale: true,
          axisTick: { show: isBottom },
          axisLabel: {
            show: isBottom,
            ...axisLabelStyle,
            margin: 10,
            hideOverlap: true,
            formatter: (v) => (useEpoch ? beijingHmsFromMs(v) : Number(v).toFixed(0)),
          },
          splitLine: { show: true, ...splitStyle },
        }
      }),
      yAxis: fields.map((f, i) => ({
        type: 'value',
        gridIndex: i,
        name: f.shortName,
        nameLocation: 'middle',
        nameRotate: 90,
        nameGap: 52,
        nameTextStyle: { color: '#9ca3af', fontSize: 11, align: 'center' },
        scale: true,
        axisLine: { show: true, lineStyle: { color: '#27272a' } },
        axisTick: { show: true },
        axisLabel: { ...axisLabelStyle, margin: 10, formatter: fmtYTick },
        splitLine: { show: true, ...splitStyle },
        splitNumber: 5,
      })),
      series: fields.map((f, i) => ({
        name: f.shortName,
        type: 'line',
        xAxisIndex: i,
        yAxisIndex: i,
        showSymbol: false,
        sampling: 'lttb',
        smooth: true,
        lineStyle: { color: f.color, width: 1.5 },
        data: fieldPoints(f),
        markLine,
      })),
    }

    return { option, chartHeight, canToggleLayout }
  }, [overview, selectedTrajIdx, trajData, align.parseOffsetMs, attitudeChartLayout])

  /** 叠加模式：剖面 + 姿态合并为一张图，共用时间轴与悬停读数 */
  const mergedProfileAttitudeOption = useMemo(() => {
    if (attitudeChartLayout !== 'overlay') return null
    const attCtx = getAttitudeTooltipContext(overview, align)
    if (!attCtx || !trajData?.path?.length || !trajData.altColumn) return null
    const { altVals, altColumn, tSec, path } = trajData
    if (!tSec?.length || !altVals?.some((a) => a != null && Number.isFinite(a))) return null

    const pts = []
    for (let i = 0; i < path.length; i += 1) {
      const a = altVals[i]
      const tv = tSec[i]
      if (a == null || !Number.isFinite(a) || !Number.isFinite(tv)) continue
      pts.push([tv * 1000, a, i])
    }
    if (!pts.length) return null
    const finAlts = altVals.filter((x) => x != null && Number.isFinite(x))
    const aMin = Math.min(...finAlts)
    const aMax = Math.max(...finAlts)

    const { series, fields, toX } = attCtx
    const pointsByField = {}
    fields.forEach((f) => {
      pointsByField[f.key] = series[f.key]
        .map((v, k) => [toX(k), v])
        .filter((p) => p[0] != null && p[1] != null && Number.isFinite(p[1]))
    })

    const fmtYTick = (value) => {
      const n = Number(value)
      if (!Number.isFinite(n)) return String(value ?? '')
      const v3 = n.toFixed(3)
      return v3.endsWith('0') ? n.toFixed(2) : v3
    }

    const xSel = selectedTrajIdx != null && Number.isFinite(tSec[selectedTrajIdx])
      ? tSec[selectedTrajIdx] * 1000
      : null
    const markLine = xSel != null
      ? {
        symbol: 'none',
        label: { formatter: '选中', color: '#facc15', fontSize: 10 },
        lineStyle: { color: '#facc15', type: 'dashed' },
        data: [{ xAxis: xSel }],
      }
      : undefined

    const nFields = fields.length
    const attitudeColors = { pitch: '#60a5fa', roll: '#34d399', yaw: '#fbbf24' }
    let attitudeYAxis
    let attitudeSeriesArr
    const attitudeRightPad = nFields === 2 ? 52 : 22

    if (nFields === 2) {
      const f0 = fields[0]
      const f1 = fields[1]
      const r0 = computeWorkbenchAttitudeYRange([series[f0.key]])
      const r1 = computeWorkbenchAttitudeYRange([series[f1.key]])
      attitudeYAxis = [
        {
          type: 'value',
          gridIndex: 1,
          name: f0.shortName,
          min: r0.min,
          max: r0.max,
          position: 'left',
          nameTextStyle: { color: '#a1a1aa', fontSize: 11 },
          axisLabel: { color: '#a1a1aa', formatter: fmtYTick },
          axisLine: { lineStyle: { color: '#27272a' } },
          splitLine: { lineStyle: { color: '#27272a' } },
        },
        {
          type: 'value',
          gridIndex: 1,
          name: f1.shortName,
          min: r1.min,
          max: r1.max,
          position: 'right',
          nameTextStyle: { color: '#a1a1aa', fontSize: 11 },
          axisLabel: { color: '#a1a1aa', formatter: fmtYTick },
          axisLine: { lineStyle: { color: '#27272a' } },
          splitLine: { show: false },
        },
      ]
      attitudeSeriesArr = fields.map((f, i) => ({
        name: f.shortName,
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1 + i,
        smooth: true,
        showSymbol: false,
        sampling: 'lttb',
        lineStyle: { width: 1.5, color: attitudeColors[f.key] || '#94a3b8' },
        itemStyle: { color: attitudeColors[f.key] || '#94a3b8' },
        emphasis: { focus: 'series', lineStyle: { width: 2.5 } },
        data: pointsByField[f.key],
        markLine: i === 0 ? markLine : undefined,
      }))
    } else {
      const rAll = computeWorkbenchAttitudeYRange(fields.map((f) => series[f.key]))
      attitudeYAxis = {
        type: 'value',
        gridIndex: 1,
        name: nFields > 1 ? '°' : fields[0].shortName,
        min: rAll.min,
        max: rAll.max,
        nameTextStyle: { color: '#a1a1aa', fontSize: 11 },
        axisLabel: { color: '#a1a1aa', formatter: fmtYTick },
        axisLine: { lineStyle: { color: '#27272a' } },
        splitLine: { lineStyle: { color: '#27272a' } },
      }
      attitudeSeriesArr = fields.map((f, i) => ({
        name: f.shortName,
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        smooth: true,
        showSymbol: false,
        sampling: 'lttb',
        lineStyle: { width: 1.5, color: attitudeColors[f.key] || '#94a3b8' },
        itemStyle: { color: attitudeColors[f.key] || '#94a3b8' },
        emphasis: { focus: 'series', lineStyle: { width: 2.5 } },
        data: pointsByField[f.key],
        markLine: i === 0 ? markLine : undefined,
      }))
    }

    const xAxisBase = {
      type: 'time',
      axisPointer: { snap: true },
      axisLabel: {
        color: '#a1a1aa',
        hideOverlap: true,
        rotate: 30,
        formatter: (v) => beijingHmsFromMs(v),
      },
      axisLine: { lineStyle: { color: '#27272a' } },
      splitLine: { show: false },
    }

    const option = {
      backgroundColor: 'transparent',
      title: {
        text: '惯导剖面与姿态时序（共用时间轴 · 悬停显示时间 / 航程 / 经纬度 / 高度 / 姿态）',
        left: 'center',
        top: 2,
        textStyle: { fontSize: 12, color: '#9ca3af', fontWeight: 'normal' },
      },
      legend: {
        data: [altColumn, ...fields.map((f) => f.shortName)],
        textStyle: { color: '#a1a1aa' },
        top: 26,
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#0f0f12',
        borderColor: '#27272a',
        textStyle: { color: '#e4e4e7' },
        confine: true,
        appendToBody: true,
        axisPointer: {
          type: 'cross',
          snap: true,
          crossStyle: { color: '#a1a1aa' },
          lineStyle: { color: '#8b5cf6', type: 'dashed' },
          label: { backgroundColor: '#18181b', color: '#e4e4e7' },
        },
        formatter: (items) => {
          if (!items?.length) return ''
          const tMs = items[0].axisValue
          return formatWorkbenchProfileAttitudeTooltipHtml(
            tMs,
            trajData,
            altColumn,
            series,
            fields,
            toX,
          )
        },
      },
      axisPointer: { link: [{ xAxisIndex: [0, 1] }] },
      grid: [
        { left: 56, right: 22, top: 52, height: '30%' },
        { left: 56, right: attitudeRightPad, top: '52%', height: '34%' },
      ],
      xAxis: [
        { ...xAxisBase, gridIndex: 0, axisLabel: { ...xAxisBase.axisLabel, show: false } },
        { ...xAxisBase, gridIndex: 1, name: '时间（北京）', nameLocation: 'middle', nameGap: 28, nameTextStyle: { color: '#9ca3af', fontSize: 11 } },
      ],
      yAxis: [
        {
          type: 'value',
          gridIndex: 0,
          name: altColumn,
          min: aMin,
          max: aMax,
          axisLabel: { color: '#a1a1aa' },
          axisLine: { lineStyle: { color: '#27272a' } },
          splitLine: { lineStyle: { color: '#27272a' } },
        },
        ...(Array.isArray(attitudeYAxis) ? attitudeYAxis : [attitudeYAxis]),
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
        {
          type: 'slider',
          xAxisIndex: [0, 1],
          start: 0,
          end: 100,
          height: 20,
          bottom: 6,
          borderColor: '#27272a',
          backgroundColor: '#0f0f12',
          fillerColor: 'rgba(139, 92, 246, 0.2)',
          handleStyle: { color: '#8b5cf6' },
          textStyle: { color: '#a1a1aa' },
        },
      ],
      series: [
        {
          type: 'line',
          name: altColumn,
          xAxisIndex: 0,
          yAxisIndex: 0,
          large: true,
          showSymbol: false,
          lineStyle: { color: '#34d399', width: 1.5 },
          data: pts,
          markLine,
        },
        ...attitudeSeriesArr,
      ],
    }

    return { option, chartHeight: 520 }
  }, [
    trajData,
    selectedTrajIdx,
    overview,
    align,
    attitudeChartLayout,
  ])

  /** 垂直剖面 / 合并图内点击 → 地图选点 */
  useEffect(() => {
    if (!trajData?.tSec?.length || !trajData.altColumn) return undefined
    if (!trajData.altVals?.some((a) => a != null && Number.isFinite(a))) return undefined
    const bind = { zr: null, handler: null }
    const tid = window.setTimeout(() => {
      const useMerged = !!mergedProfileAttitudeOption
      const chart = useMerged
        ? mergedProfileAttitudeRef.current?.getEchartsInstance?.()
        : trajAltChartRef.current?.getEchartsInstance?.()
      if (!chart) return
      const { tSec } = trajData
      const validTs = tSec.filter((v) => Number.isFinite(v))
      if (!validTs.length) return
      const tMinMs = Math.min(...validTs) * 1000
      const tMaxMs = Math.max(...validTs) * 1000
      const maxPickMs = Math.max((tMaxMs - tMinMs) * 0.02, 500)

      const resolveClickMs = (ox, oy) => {
        if (!useMerged) {
          const coord = chart.convertFromPixel({ gridIndex: 0 }, [ox, oy])
          return coord && Number.isFinite(coord[0]) ? coord[0] : null
        }
        const opt = chart.getOption()
        const gridOpt = opt.grid
        const nGrids = Array.isArray(gridOpt) ? gridOpt.length : (gridOpt != null ? 1 : 0)
        for (let gi = 0; gi < nGrids; gi += 1) {
          try {
            if (chart.containPixel({ gridIndex: gi }, [ox, oy])) {
              const coord = chart.convertFromPixel({ gridIndex: gi }, [ox, oy])
              if (coord && Number.isFinite(coord[0])) return coord[0]
            }
          } catch {
            /* next */
          }
        }
        try {
          const coord = chart.convertFromPixel({ gridIndex: 0 }, [ox, oy])
          if (coord && Number.isFinite(coord[0])) return coord[0]
        } catch {
          return null
        }
        return null
      }

      bind.zr = chart.getZr()
      bind.handler = (ev) => {
        const clickMs = resolveClickMs(ev.offsetX, ev.offsetY)
        if (clickMs == null || !Number.isFinite(clickMs)) return
        let best = 0
        let bestD = Infinity
        for (let i = 0; i < tSec.length; i += 1) {
          const tv = tSec[i]
          if (!Number.isFinite(tv)) continue
          const d = Math.abs(tv * 1000 - clickMs)
          if (d < bestD) {
            bestD = d
            best = i
          }
        }
        if (bestD > maxPickMs) return
        setSelectedTrajIdx(best)
      }
      bind.zr.on('click', bind.handler)
    }, 0)
    return () => {
      window.clearTimeout(tid)
      if (bind.zr && bind.handler) bind.zr.off('click', bind.handler)
    }
  }, [trajData, mergedProfileAttitudeOption])

  /** 地图/剖面选点后，将姿态图时间轴缩放到包含该时刻（便于看到黄线） */
  useEffect(() => {
    if (selectedTrajIdx == null || !trajData?.tSec?.length) return undefined
    const s = overview?.attitude_series
    const ep = s?.time_epoch
    if (!Array.isArray(ep) || !ep.some((v) => Number.isFinite(Number(v)))) return undefined
    const offMs = align.parseOffsetMs || 0
    const msList = ep
      .map((v) => (Number.isFinite(Number(v)) ? Number(v) * 1000 + offMs : null))
      .filter((x) => x != null)
    if (!msList.length) return undefined
    const tMin = Math.min(...msList)
    const tMax = Math.max(...msList)
    const tMs = trajData.tSec[selectedTrajIdx] * 1000
    const nAxes = ['pitch', 'roll', 'yaw'].filter(
      (k) => Array.isArray(s[k]) && s[k].some((v) => v != null && Number.isFinite(v)),
    ).length
    if (!nAxes) return undefined
    const useMerged = !!mergedProfileAttitudeOption
    const xAxisIndex = useMerged ? [0, 1] : (attitudeChartLayout === 'overlay' ? 0 : Array.from({ length: nAxes }, (_, i) => i))
    const tid = window.setTimeout(() => {
      const inst = useMerged
        ? mergedProfileAttitudeRef.current?.getEchartsInstance?.()
        : attitudeChartRef.current?.getEchartsInstance?.()
      if (!inst) return
      const full = Math.max(tMax - tMin, 1)
      const span = Math.min(full * 0.15, 15 * 60 * 1000)
      let startV = tMs - span / 2
      let endV = tMs + span / 2
      if (startV < tMin) {
        endV += tMin - startV
        startV = tMin
      }
      if (endV > tMax) {
        startV -= endV - tMax
        endV = tMax
      }
      startV = Math.max(tMin, startV)
      endV = Math.min(tMax, endV)
      if (!(endV > startV)) return
      try {
        inst.dispatchAction({ type: 'dataZoom', xAxisIndex, startValue: startV, endValue: endV })
      } catch {
        /* ignore */
      }
    }, 80)
    return () => window.clearTimeout(tid)
  }, [
    selectedTrajIdx,
    trajData,
    align.parseOffsetMs,
    attitudeChartLayout,
    mergedProfileAttitudeOption,
    overview?.attitude_series?.time_epoch?.length,
    overview?.attitude_series?.time?.length,
  ])

  /** 姿态图点击 → 与地图/剖面共用 selectedTrajIdx（须与 tSec 同为 epoch+偏移 的 time 轴）；合并图时由剖面点击逻辑统一处理 */
  useEffect(() => {
    if (mergedProfileAttitudeOption) return undefined
    const s = overview?.attitude_series
    const ep = s?.time_epoch
    const useEpoch = Array.isArray(ep) && ep.length === s?.time?.length && ep.some((v) => Number.isFinite(Number(v)))
    if (!useEpoch || !trajData?.tSec?.length) return undefined

    const bind = { zr: null, handler: null }
    const tid = window.setTimeout(() => {
      const chart = attitudeChartRef.current?.getEchartsInstance?.()
      if (!chart) return
      const { tSec } = trajData
      const validTs = tSec.filter((v) => Number.isFinite(v))
      if (!validTs.length) return
      const tMinMs = Math.min(...validTs) * 1000
      const tMaxMs = Math.max(...validTs) * 1000
      const maxPickMs = Math.max((tMaxMs - tMinMs) * 0.02, 500)

      const resolveClickMs = (ox, oy) => {
        const opt = chart.getOption()
        const gridOpt = opt.grid
        const nGrids = Array.isArray(gridOpt) ? gridOpt.length : (gridOpt != null ? 1 : 0)
        if (!nGrids) return null
        for (let gi = 0; gi < nGrids; gi += 1) {
          try {
            if (chart.containPixel({ gridIndex: gi }, [ox, oy])) {
              const coord = chart.convertFromPixel({ gridIndex: gi }, [ox, oy])
              if (coord && Number.isFinite(coord[0])) return coord[0]
            }
          } catch {
            /* try next grid */
          }
        }
        try {
          const coord = chart.convertFromPixel({ gridIndex: 0 }, [ox, oy])
          if (coord && Number.isFinite(coord[0])) return coord[0]
        } catch {
          return null
        }
        return null
      }

      bind.zr = chart.getZr()
      bind.handler = (ev) => {
        const clickMs = resolveClickMs(ev.offsetX, ev.offsetY)
        if (clickMs == null || !Number.isFinite(clickMs)) return
        let best = 0
        let bestD = Infinity
        for (let i = 0; i < tSec.length; i += 1) {
          const tv = tSec[i]
          if (!Number.isFinite(tv)) continue
          const d = Math.abs(tv * 1000 - clickMs)
          if (d < bestD) {
            bestD = d
            best = i
          }
        }
        if (bestD > maxPickMs) return
        setSelectedTrajIdx(best)
      }
      bind.zr.on('click', bind.handler)
    }, 0)
    return () => {
      window.clearTimeout(tid)
      if (bind.zr && bind.handler) bind.zr.off('click', bind.handler)
    }
  }, [trajData, attitudeChartLayout, overview?.attitude_series, mergedProfileAttitudeOption])

  const videos = useMemo(() => {
    const files = detail?.files || []
    return files.filter((f) => (f.asset_type || '').startsWith('video_'))
  }, [detail])

  useEffect(() => {
    const saved = loadVideoTabsState(sortieId)
    if (saved?.panes?.length) {
      setVideoPanes(saved.panes.map(normalizeVideoPane))
      const k = saved.activeKey && saved.panes.some((p) => p.key === saved.activeKey)
        ? saved.activeKey
        : saved.panes[0].key
      setVideoTabActiveKey(k)
    } else {
      setVideoPanes([{
        key: '1',
        label: '视图 1',
        layout: 'single',
        singleId: null,
        multiIds: Array(VIDEO_MULTI_SLOTS).fill(null),
        columnCount: 3,
      }])
      setVideoTabActiveKey('1')
    }
  }, [sortieId])

  useEffect(() => {
    saveVideoTabsState(sortieId, { panes: videoPanes, activeKey: videoTabActiveKey })
  }, [sortieId, videoPanes, videoTabActiveKey])

  useEffect(() => {
    if (!videos.length) return
    setVideoPanes((prev) => prev.map((p) => ({
      ...p,
      singleId: (p.singleId != null && videos.some((v) => v.id === p.singleId))
        ? p.singleId
        : videos[0]?.id ?? null,
      multiIds: migratePaneMultiIds(p).map((id, slot) => (
        (id != null && videos.some((v) => v.id === id))
          ? id
          : (videos[slot]?.id ?? videos[0]?.id ?? null)
      )),
    })))
  }, [videos])

  const streamUrlForFileId = useCallback((fileId) => {
    if (fileId == null || !token) return ''
    return `/api/shared-tsn/files/${fileId}/stream?token=${encodeURIComponent(token)}`
  }, [token])

  const openStreamInNewTab = (fileId) => {
    const u = streamUrlForFileId(fileId)
    if (!u) return
    window.open(u, '_blank', 'noopener,noreferrer')
  }

  const updateVideoPane = (paneKey, patch) => {
    setVideoPanes((prev) => prev.map((p) => (p.key === paneKey ? { ...p, ...patch } : p)))
  }

  const activeVideoPane = useMemo(
    () => videoPanes.find((p) => p.key === videoTabActiveKey) || videoPanes[0],
    [videoPanes, videoTabActiveKey],
  )

  const hasRenderableVideo = activeVideoPane && (
    activeVideoPane.layout === 'single'
      ? activeVideoPane.singleId
      : migratePaneMultiIds(activeVideoPane).slice(0, visibleVideoSlotCount(activeVideoPane)).some(Boolean)
  )

  const videoLabel = useCallback((fid) => {
    const v = videos.find((x) => x.id === fid)
    return v?.asset_label || v?.original_filename || `视频 #${fid}`
  }, [videos])

  const refForVideo = useCallback((fileId) => {
    if (!fileId) return undefined
    const map = videoRefCallbacks.current
    if (!map.has(fileId)) {
      map.set(fileId, (el) => {
        if (el) videoElsRef.current[fileId] = el
        else delete videoElsRef.current[fileId]
      })
    }
    return map.get(fileId)
  }, [])

  const onWorkbenchVideoLoaded = useCallback((e) => {
    const el = e.currentTarget
    const fid = Number(el.getAttribute('data-file-id'))
    const pend = el.dataset.workbenchSeek
    if (pend == null || !Number.isFinite(el.duration) || el.duration <= 0) return
    const tv = Number(pend)
    delete el.dataset.workbenchSeek
    if (!Number.isFinite(tv)) return
    const name = videoLabel(fid)
    if (tv < 0 || tv > el.duration) {
      message.warning(`${name}：同步时刻 ${tv.toFixed(2)}s 超出片长 [0, ${el.duration.toFixed(2)}]s`)
      return
    }
    el.currentTime = tv
  }, [videoLabel])

  useEffect(() => {
    if (selectedTrajIdx == null || !trajData?.tSec?.length) return
    const tAligned = trajData.tSec[selectedTrajIdx]
    const pane = activeVideoPane
    if (!pane) return
    const ids = pane.layout === 'single'
      ? (pane.singleId ? [pane.singleId] : [])
      : migratePaneMultiIds(pane).slice(0, visibleVideoSlotCount(pane)).filter((x) => x != null)
    if (!ids.length) return
    const oob = []
    const seen = new Set()
    ids.forEach((fid) => {
      if (seen.has(fid)) return
      seen.add(fid)
      const voff = (align.videoOffsets[fid] || 0) / 1000
      const tv = tAligned + voff
      const el = videoElsRef.current[fid]
      const name = videoLabel(fid)
      if (!el) return
      if (!Number.isFinite(el.duration) || el.duration <= 0) {
        el.dataset.workbenchSeek = String(tv)
        return
      }
      if (tv < 0) {
        oob.push(`${name}：目标 ${tv.toFixed(2)}s 小于 0`)
        return
      }
      if (tv > el.duration) {
        oob.push(`${name}：目标 ${tv.toFixed(2)}s 超过片长 ${el.duration.toFixed(2)}s`)
        return
      }
      el.currentTime = tv
    })
    if (oob.length) {
      message.warning({ content: oob.join('；'), key: 'workbench_video_sync_oob', duration: 6 })
    }
  }, [selectedTrajIdx, trajData, activeVideoPane, align.videoOffsets, videoLabel, videoTabActiveKey])

  const syncHintText = useMemo(() => {
    if (selectedTrajIdx == null || !trajData?.tSec || !activeVideoPane) return null
    const tAligned = trajData.tSec[selectedTrajIdx]
    const ids = activeVideoPane.layout === 'single'
      ? (activeVideoPane.singleId ? [activeVideoPane.singleId] : [])
      : migratePaneMultiIds(activeVideoPane).slice(0, visibleVideoSlotCount(activeVideoPane)).filter((x) => x != null)
    const parts = ids.map((fid) => {
      const off = (align.videoOffsets[fid] || 0) / 1000
      const tv = tAligned + off
      return `${videoLabel(fid)}：视频 ${tv.toFixed(3)} s（解析对齐 ${tAligned.toFixed(3)} s + 偏移 ${(off * 1000).toFixed(0)} ms）`
    })
    return parts.join(' · ')
  }, [selectedTrajIdx, trajData, activeVideoPane, align.videoOffsets, videoLabel])

  const navParseMeta = useMemo(() => {
    const opt = irsOptions.find((o) => o.value === irsKey)
    if (!taskId || !opt?.raw) return null
    return {
      port: opt.raw.port_number,
      parserId: opt.raw.parser_profile_id ?? null,
    }
  }, [taskId, irsOptions, irsKey])

  const openParseTableAtTrajPoint = useCallback(() => {
    if (selectedTrajIdx == null || !taskId || !navParseMeta || !trajData?.tSec?.length) return
    const rawTs = trajData.tSec[selectedTrajIdx] - (align.parseOffsetMs || 0) / 1000
    const qs = new URLSearchParams()
    qs.set('parse_ts', String(rawTs))
    qs.set('port', String(navParseMeta.port))
    if (navParseMeta.parserId != null) qs.set('parser_id', String(navParseMeta.parserId))
    window.open(`/tasks/${taskId}?${qs}`, '_blank', 'noopener,noreferrer')
  }, [selectedTrajIdx, taskId, navParseMeta, trajData, align.parseOffsetMs])

  const openParseTableAtEvent = useCallback((ev) => {
    if (!taskId || !ev) return
    const qs = new URLSearchParams()
    if (ev.parse_ts != null && Number.isFinite(ev.parse_ts)) qs.set('parse_ts', String(ev.parse_ts))
    if (ev.port != null) qs.set('port', String(ev.port))
    if (ev.parser_id != null) qs.set('parser_id', String(ev.parser_id))
    window.open(`/tasks/${taskId}?${qs.toString()}`, '_blank', 'noopener,noreferrer')
  }, [taskId])

  const scrollToEventsSummarySection = useCallback(() => {
    eventsSummarySectionRef.current?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    })
  }, [])

  const onVideoTabsEdit = (targetKey, action) => {
    if (action === 'add') {
      const newKey = `v_${Date.now()}`
      const v0 = videos[0]?.id ?? null
      setVideoPanes((prev) => {
        const n = prev.length + 1
        return [
          ...prev,
          {
            key: newKey,
            label: `视图 ${n}`,
            layout: 'single',
            singleId: v0,
            multiIds: Array.from({ length: VIDEO_MULTI_SLOTS }, (_, i) => videos[i]?.id ?? v0),
            columnCount: 3,
          },
        ]
      })
      setVideoTabActiveKey(newKey)
      return
    }
    if (action === 'remove') {
      setVideoPanes((prev) => {
        if (prev.length <= 1) return prev
        return prev.filter((p) => p.key !== targetKey)
      })
    }
  }

  useEffect(() => {
    if (videoPanes.length && !videoPanes.some((p) => p.key === videoTabActiveKey)) {
      setVideoTabActiveKey(videoPanes[0].key)
    }
  }, [videoPanes, videoTabActiveKey])

  const toggleFs = () => {
    const el = wrapRef.current
    if (!el) return
    if (!document.fullscreenElement) {
      el.requestFullscreen?.().then(() => setFs(true)).catch(() => {})
    } else {
      document.exitFullscreen?.().then(() => setFs(false)).catch(() => {})
    }
  }

  useEffect(() => {
    const onFs = () => setFs(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', onFs)
    return () => document.removeEventListener('fullscreenchange', onFs)
  }, [])

  if (detailLoading) {
    return (
      <div style={{ padding: 48, textAlign: 'center' }}>
        <Spin /> 加载架次…
      </div>
    )
  }

  if (!detail) {
    return <Alert type="error" message="架次不存在或无权访问" showIcon />
  }

  return (
    <div className="fade-in">
      <Space style={{ marginBottom: 16 }} align="center">
        <Button type="link" icon={<LeftOutlined />} onClick={() => navigate('/workbench')}>返回架次列表</Button>
        <Title level={4} style={{ margin: 0 }}>{detail?.sortie_label}</Title>
        {detail?.experiment_date && <Tag>{detail.experiment_date}</Tag>}
      </Space>
      {detail?.remarks && (
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>{detail.remarks}</Text>
      )}

      <Card
        size="small"
        title={<><DatabaseOutlined style={{ marginRight: 6 }} />解析任务</>}
        style={{ marginBottom: 16 }}
      >
        <Space wrap size="middle">
          <Text type="secondary">选择该架次的解析任务，总览/事件分析以此为数据来源：</Text>
          <Select
            style={{ minWidth: 320 }}
            placeholder="选择已完成的解析任务"
            value={taskId}
            onChange={setTaskId}
            allowClear
            showSearch
            optionFilterProp="label"
            options={(() => {
              const inSortie = new Set((matched?.parse_tasks || []).map((t) => t.parse_task_id))
              const all = tasks.map((t) => ({
                value: t.id,
                label: `${inSortie.has(t.id) ? '★ ' : ''}#${t.id} ${t.filename || ''} (${t.status})`,
              }))
              all.sort((a, b) => (b.label.startsWith('★') ? 1 : 0) - (a.label.startsWith('★') ? 1 : 0))
              return all
            })()}
          />
          {matched?.parse_tasks?.length ? (
            <Text type="secondary" style={{ fontSize: 12 }}>
              ★ 为本架次文件直接匹配到的解析任务（共 {matched.parse_tasks.length} 个）
            </Text>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>
              未匹配到直接关联的解析任务，可从全部已完成任务中手动选择
            </Text>
          )}
        </Space>
      </Card>

      <WorkbenchOverviewCard
        overview={overview}
        loading={overviewLoading}
        taskId={taskId}
        onScrollToEventsSummary={scrollToEventsSummarySection}
      />

      <Card title="时间对齐（本地保存）" style={{ marginBottom: 16 }} size="small">
        <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          解析任务时间戳统一加偏移（毫秒），用于与视频等外源对齐；设置保存在本机浏览器。
        </Text>
        <Form layout="inline">
          <Form.Item label="解析时间偏移 (ms)">
            <InputNumber
              value={align.parseOffsetMs}
              onChange={(v) => patchAlign({ parseOffsetMs: v ?? 0 })}
              step={10}
              style={{ width: 140 }}
            />
          </Form.Item>
          <Form.Item label="主时钟参考">
            <Radio.Group
              value={align.masterClock}
              onChange={(e) => patchAlign({ masterClock: e.target.value })}
            >
              <Radio.Button value="parse">解析数据</Radio.Button>
              <Radio.Button value="video">视频时间轴</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Button
            type="link"
            onClick={() => {
              const fresh = { parseOffsetMs: 0, masterClock: 'parse', videoOffsets: {} }
              setAlign(fresh)
              saveAlignment(sortieId, fresh)
            }}
          >重置偏移</Button>
        </Form>
        {videos.map((v) => (
          <div key={v.id} style={{ marginTop: 10 }}>
            <Space>
              <Text style={{ minWidth: 220 }} ellipsis>{v.asset_label || v.original_filename}</Text>
              <Text type="secondary">视频相对解析额外偏移 (ms)</Text>
              <InputNumber
                value={align.videoOffsets[v.id] ?? 0}
                onChange={(n) => patchAlign((a) => ({
                  ...a,
                  videoOffsets: { ...a.videoOffsets, [v.id]: n ?? 0 },
                }))}
                step={10}
              />
            </Space>
          </div>
        ))}
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card
            title="惯导轨迹（地图）"
            extra={(
              <Space size="middle" wrap>
                {trajDataRaw?.path?.length > 0 && leadingZeroOriginCount > 0 && (
                  <Tooltip title={`开头连续 ${leadingZeroOriginCount} 个采样接近经度 0°、纬度 0°，多为惯导未就绪时的占位；剔除后地图与剖面等图表一并使用该轨迹。`}>
                    <Space size={6} align="center">
                      <Text type="secondary" style={{ fontSize: 12 }}>去掉开头 (0°,0°)</Text>
                      <Switch
                        size="small"
                        checked={omitZeroOrigin}
                        onChange={setOmitZeroOrigin}
                      />
                    </Space>
                  </Tooltip>
                )}
                <Button icon={<ReloadOutlined />} size="small" onClick={loadTrajectory} loading={trajLoading}>重载</Button>
              </Space>
            )}
          >
            <Space wrap style={{ marginBottom: 12 }}>
              <Text type="secondary">惯导源（仅驱动地图/姿态/视频同步）</Text>
              <Select
                style={{ minWidth: 320 }}
                placeholder="选择惯导端口"
                value={irsKey}
                onChange={setIrsKey}
                disabled={!irsOptions.length}
                options={irsOptions}
              />
            </Space>
            {!taskId && <Alert type="info" showIcon message="请选择解析任务" style={{ marginBottom: 12 }} />}
            {taskId && !irsOptions.length && (
              <Alert type="warning" showIcon message="该任务结果中未识别到惯导相关端口（名称需含「惯导」「IRS」等）" style={{ marginBottom: 12 }} />
            )}
            {taskId && !!irsOptions.length && trajData && (
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                message="速度与高度字段（从当前惯导端口解析结果的列名中自动匹配）"
                description={(
                  <span>
                    速度：<strong>{trajData.speedColumn || '未匹配到列'}</strong>
                    （用于轨迹颜色渐变）
                    {' · '}
                    高度：<strong>{trajData.altColumn || '未匹配到列'}</strong>
                    （用于垂直剖面）
                  </span>
                )}
              />
            )}
            <Spin spinning={trajLoading}>
              {trajData?.path?.length > 0 ? (
                <MapTrajectoryLeaflet
                  path={trajData.path}
                  groundSpeedVals={trajData.groundSpeedVals}
                  eastVals={trajData.eastVals}
                  northVals={trajData.northVals}
                  pitchVals={trajData.pitchVals}
                  rollVals={trajData.rollVals}
                  yawVals={trajData.yawVals}
                  beijingTimeStrs={trajData.beijingTimeStrs}
                  selectedTrajIdx={selectedTrajIdx}
                  onSelectIdx={setSelectedTrajIdx}
                  height={460}
                />
              ) : !trajLoading ? (
                <Empty
                  description={
                    omitZeroOrigin && trajDataRaw?.path?.length && !trajData?.path?.length
                      ? '全部为 (0°,0°)，剔除后无可用点；请关闭「去掉开头」开关'
                      : '无轨迹数据'
                  }
                />
              ) : null}
            </Spin>
            {trajData?.path?.length > 0 && (
              <div style={{ marginTop: 14 }}>
                <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
                  共 <strong>{trajData.path.length}</strong> 个采样点。地图可滚轮缩放、拖拽；沿途小圆点为采样点，点击圆点或轨迹附近可选点。
                  选中后可打开解析任务表格并定位到对应 timestamp 行。
                </Text>
                <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
                  北京时间（与滑块当前序号一致）：
                  <Text strong style={{ color: '#e4e4e7' }}>
                    {trajData.beijingTimeStrs?.[selectedTrajIdx ?? 0] ?? '—'}
                  </Text>
                  {trajData.beijingWallClockColumn && (
                    <span> · 来自解析列「{trajData.beijingWallClockColumn}」</span>
                  )}
                  {!trajData.beijingWallClockColumn && (
                    <span> · 无时间列时由解析时间戳换算为东八区</span>
                  )}
                </Text>
                <Slider
                  min={0}
                  max={trajData.path.length - 1}
                  step={1}
                  value={selectedTrajIdx ?? 0}
                  onChange={(v) => setSelectedTrajIdx(v)}
                  tooltip={{ formatter: (v) => `第 ${Number(v) + 1} / ${trajData.path.length} 点` }}
                  marks={trajData.path.length <= 1 ? {} : { 0: '1', [trajData.path.length - 1]: String(trajData.path.length) }}
                />
                <Space wrap style={{ marginTop: 10 }} align="center">
                  <Text type="secondary">跳到序号</Text>
                  <InputNumber
                    min={1}
                    max={trajData.path.length}
                    size="small"
                    style={{ width: 100 }}
                    placeholder="1…N"
                    value={selectedTrajIdx != null ? selectedTrajIdx + 1 : undefined}
                    onChange={(v) => {
                      if (v == null) return
                      const i = Math.round(Number(v)) - 1
                      if (i >= 0 && i < trajData.path.length) setSelectedTrajIdx(i)
                    }}
                  />
                  <Button type="link" size="small" onClick={() => setSelectedTrajIdx(null)}>清除选点</Button>
                </Space>
              </div>
            )}
            {selectedTrajIdx != null && trajData?.path?.[selectedTrajIdx] && (
              <Space wrap style={{ marginTop: 12 }} align="center">
                <Tag color="gold">选中 {selectedTrajIdx + 1}/{trajData.path.length}</Tag>
                <Text>
                  北京时间{' '}
                  <strong>{trajData.beijingTimeStrs?.[selectedTrajIdx] ?? '—'}</strong>
                </Text>
                <Text>经度 {Number(trajData.path[selectedTrajIdx][0]).toFixed(6)}°</Text>
                <Text>纬度 {Number(trajData.path[selectedTrajIdx][1]).toFixed(6)}°</Text>
                <Text type="secondary">解析对齐 {Number(trajData.tSec[selectedTrajIdx]).toFixed(3)} s</Text>
                {trajData.speedColumn && (
                  <Text type="secondary">
                    {trajData.speedColumn}
                    ：{trajData.speedVals?.[selectedTrajIdx] != null && Number.isFinite(trajData.speedVals[selectedTrajIdx])
                      ? String(trajData.speedVals[selectedTrajIdx])
                      : '—'}
                  </Text>
                )}
                {trajData.altColumn && (
                  <Text type="secondary">
                    {trajData.altColumn}
                    ：{trajData.altVals?.[selectedTrajIdx] != null && Number.isFinite(trajData.altVals[selectedTrajIdx])
                      ? String(trajData.altVals[selectedTrajIdx])
                      : '—'}
                  </Text>
                )}
                <Button
                  type="link"
                  size="small"
                  href={`https://www.openstreetmap.org/?mlat=${Number(trajData.path[selectedTrajIdx][1])}&mlon=${Number(trajData.path[selectedTrajIdx][0])}&zoom=16`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  地图中查看实际位置
                </Button>
                <Button
                  type="primary"
                  size="small"
                  icon={<DatabaseOutlined />}
                  disabled={!navParseMeta}
                  onClick={openParseTableAtTrajPoint}
                >
                  解析表格中打开
                </Button>
              </Space>
            )}
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
              轨迹叠加在 OpenStreetMap 底图上；线段颜色表示地速（由东/北分量计算或解析标量速度列）。下方
              {mergedProfileAttitudeOption ? '垂直剖面与姿态时序合并为一图' : '垂直剖面与姿态时序'}
              与地图、滑块选点共用同一时间基准（含「解析时间偏移」）；右侧视频仍按该时间关联。
            </Text>
            {(mergedProfileAttitudeOption || trajAltOption || attitudeChart) && (
              <Row gutter={[0, 20]} style={{ marginTop: 12 }}>
                {mergedProfileAttitudeOption ? (
                  <Col span={24}>
                    <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
                      垂直剖面与姿态时序（共用时间轴；悬停显示时间、累计航程、经纬度、高度与各姿态分量；黄线表示当前选点时刻；在图内点击联动地图；点底部缩放条区域无效）
                    </Text>
                    {attitudeChart?.canToggleLayout && (
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 8 }}>
                        <Radio.Group
                          value={attitudeChartLayout}
                          onChange={(e) => setAttitudeChartLayout(e.target.value)}
                          size="small"
                          optionType="button"
                          buttonStyle="solid"
                        >
                          <Radio.Button value="overlay">
                            <Space size={4}><LineChartOutlined />叠加图</Space>
                          </Radio.Button>
                          <Radio.Button value="grid">
                            <Space size={4}><AppstoreOutlined />并列图</Space>
                          </Radio.Button>
                        </Radio.Group>
                      </div>
                    )}
                    <ReactECharts
                      ref={mergedProfileAttitudeRef}
                      option={mergedProfileAttitudeOption.option}
                      style={{ height: mergedProfileAttitudeOption.chartHeight, minHeight: 400 }}
                      notMerge
                      lazyUpdate
                      theme="dark"
                    />
                  </Col>
                ) : (
                  <>
                    {trajAltOption && (
                      <Col span={24}>
                        <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
                          垂直剖面（高度 vs 时间，与地图同源）
                        </Text>
                        <ReactECharts
                          ref={trajAltChartRef}
                          option={trajAltOption}
                          style={{ height: 300 }}
                          notMerge
                          lazyUpdate
                          theme="dark"
                        />
                      </Col>
                    )}
                    {attitudeChart && (
                      <Col span={24}>
                        <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
                          姿态时序（pitch / roll / yaw，总览 IRS 降采样；黄线表示当前选点时刻）。在图内点击与垂直剖面相同，会联动地图与剖面；点底部缩放条区域无效。
                        </Text>
                        {attitudeChart.canToggleLayout && (
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 8 }}>
                            <Radio.Group
                              value={attitudeChartLayout}
                              onChange={(e) => setAttitudeChartLayout(e.target.value)}
                              size="small"
                              optionType="button"
                              buttonStyle="solid"
                            >
                              <Radio.Button value="overlay">
                                <Space size={4}><LineChartOutlined />叠加图</Space>
                              </Radio.Button>
                              <Radio.Button value="grid">
                                <Space size={4}><AppstoreOutlined />并列图</Space>
                              </Radio.Button>
                            </Radio.Group>
                          </div>
                        )}
                        <ReactECharts
                          ref={attitudeChartRef}
                          option={attitudeChart.option}
                          style={{ height: attitudeChart.chartHeight, minHeight: 280 }}
                          notMerge
                          lazyUpdate
                          theme="dark"
                        />
                      </Col>
                    )}
                  </>
                )}
              </Row>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card
            title="试验视频"
            extra={(
              <Button
                icon={fs ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
                onClick={toggleFs}
                disabled={!videos.length || !hasRenderableVideo}
              >
                {fs ? '退出全屏' : '全屏'}
              </Button>
            )}
          >
            {!videos.length && <Empty description="本架次暂无视频类文件（上传时请选择视频机位类型）" />}
            {!!videos.length && (
              <>
                <Alert
                  type="info"
                  showIcon
                  message="编码与解码"
                  description="素材可能为 H.265(HEVC)。Chrome/Edge 在内核版本与系统解码器不同，内嵌播放器可能无法硬解；可尝试 Safari、新标签页系统播放，或改用 H.264。"
                  style={{ marginBottom: 12 }}
                />
                {syncHintText && (
                  <Alert
                    type="success"
                    showIcon
                    style={{ marginBottom: 12 }}
                    message="轨迹时刻对应的视频跳转（解析对齐时间 + 各路视频偏移）"
                    description={syncHintText}
                  />
                )}
                <Tabs
                  type="editable-card"
                  size="small"
                  activeKey={videoTabActiveKey}
                  onChange={setVideoTabActiveKey}
                  onEdit={onVideoTabsEdit}
                  items={videoPanes.map((p) => ({
                    key: p.key,
                    label: p.label,
                    closable: videoPanes.length > 1,
                    children: (
                      <div>
                        <Space wrap style={{ marginBottom: 12 }} align="center">
                          <Text type="secondary">布局</Text>
                          <Radio.Group
                            value={p.layout}
                            onChange={(e) => updateVideoPane(p.key, { layout: e.target.value })}
                          >
                            <Radio.Button value="single">单画面</Radio.Button>
                            <Radio.Button value="column">单列</Radio.Button>
                            <Radio.Button value="quad">四分屏</Radio.Button>
                            <Radio.Button value="nine">九分屏</Radio.Button>
                          </Radio.Group>
                          {p.layout === 'column' && (
                            <>
                              <Text type="secondary">路数</Text>
                              <Select
                                style={{ width: 88 }}
                                value={Math.min(9, Math.max(1, Number(p.columnCount) || 3))}
                                onChange={(n) => updateVideoPane(p.key, { columnCount: n })}
                                options={Array.from({ length: 9 }, (_, i) => ({
                                  value: i + 1,
                                  label: `${i + 1}`,
                                }))}
                              />
                            </>
                          )}
                        </Space>
                        {p.layout === 'single' && (
                          <>
                            <Space wrap style={{ marginBottom: 8 }}>
                              <Select
                                style={{ minWidth: 220 }}
                                value={p.singleId}
                                onChange={(id) => updateVideoPane(p.key, { singleId: id })}
                                options={videos.map((v, i) => ({
                                  value: v.id,
                                  label: v.asset_label || v.original_filename || `视频 ${i + 1}`,
                                }))}
                              />
                              <Button size="small" onClick={() => openStreamInNewTab(p.singleId)}>
                                新标签页打开
                              </Button>
                            </Space>
                            <div
                              ref={videoTabActiveKey === p.key ? wrapRef : undefined}
                              style={{ background: '#000', borderRadius: 8, overflow: 'hidden' }}
                            >
                              {p.singleId && streamUrlForFileId(p.singleId) && (
                                <video
                                  ref={refForVideo(p.singleId)}
                                  data-file-id={p.singleId}
                                  key={p.singleId}
                                  src={streamUrlForFileId(p.singleId)}
                                  controls
                                  playsInline
                                  onLoadedMetadata={onWorkbenchVideoLoaded}
                                  style={{ width: '100%', maxHeight: 420, display: 'block' }}
                                  crossOrigin="anonymous"
                                />
                              )}
                            </div>
                          </>
                        )}
                        {(p.layout === 'quad' || p.layout === 'column' || p.layout === 'nine') && (
                          <div
                            ref={videoTabActiveKey === p.key ? wrapRef : undefined}
                            style={{
                              display: 'grid',
                              gridTemplateColumns:
                                p.layout === 'column'
                                  ? '1fr'
                                  : p.layout === 'nine'
                                    ? '1fr 1fr 1fr'
                                    : '1fr 1fr',
                              gap: 8,
                              background: '#111',
                              borderRadius: 8,
                              padding: 8,
                            }}
                          >
                            {Array.from(
                              { length: visibleVideoSlotCount(p) },
                              (_, slot) => slot,
                            ).map((slot) => {
                              const mids = migratePaneMultiIds(p)
                              const fid = mids[slot]
                              const rowMaxH = p.layout === 'nine' ? 120 : p.layout === 'column' ? 140 : 180
                              return (
                                <div
                                  key={slot}
                                  style={{ background: '#000', borderRadius: 6, overflow: 'hidden' }}
                                >
                                  <Space size="small" wrap style={{ padding: 8 }}>
                                    <Select
                                      size="small"
                                      style={{ minWidth: 140 }}
                                      value={fid}
                                      onChange={(id) => updateVideoPane(p.key, {
                                        multiIds: mids.map((x, i) => (i === slot ? id : x)),
                                      })}
                                      options={videos.map((v, i) => ({
                                        value: v.id,
                                        label: v.asset_label || v.original_filename || `视频 ${i + 1}`,
                                      }))}
                                    />
                                    <Button
                                      size="small"
                                      onClick={() => openStreamInNewTab(fid)}
                                    >
                                      新标签页
                                    </Button>
                                  </Space>
                                  {fid && streamUrlForFileId(fid) && (
                                    <video
                                      ref={refForVideo(fid)}
                                      data-file-id={fid}
                                      key={`${p.layout}-${slot}-${fid}`}
                                      src={streamUrlForFileId(fid)}
                                      controls
                                      playsInline
                                      onLoadedMetadata={onWorkbenchVideoLoaded}
                                      style={{ width: '100%', maxHeight: rowMaxH, display: 'block' }}
                                      crossOrigin="anonymous"
                                    />
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    ),
                  }))}
                />
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
                  使用「新建视图」可添加多组机位组合；单列、四分屏、九分屏每路可独立选择，单列路数为 1–9。新标签页会以当前登录 token 直连流地址。
                </Text>
              </>
            )}
          </Card>
        </Col>
      </Row>

      <div
        ref={eventsSummarySectionRef}
        id="workbench-events-summary"
        style={{ scrollMarginTop: 72 }}
      >
        <WorkbenchEventsCard
          summary={eventsSummary}
          loading={eventsLoading}
          taskId={taskId}
          onOpenEvent={openParseTableAtEvent}
        />
      </div>
    </div>
  )
}

function WorkbenchOverviewCard({ overview, loading, taskId, onScrollToEventsSummary }) {
  if (!taskId) {
    return (
      <Card size="small" style={{ marginBottom: 16 }}>
        <Empty description="请在上方选择一个解析任务以加载架次总览" />
      </Card>
    )
  }
  if (loading) {
    return (
      <Card size="small" style={{ marginBottom: 16 }}>
        <div style={{ textAlign: 'center', padding: 24 }}><Spin /> 加载总览…</div>
      </Card>
    )
  }
  if (!overview || overview.error) {
    return (
      <Card size="small" style={{ marginBottom: 16 }}>
        <Alert type="warning" showIcon message={overview?.error || '未能加载架次总览'} />
      </Card>
    )
  }
  const { flight_info: info = {}, flight_profile: profile = {}, attitude = {}, phases = [], anomalies = [], quality, narrative, primary_irs, primary_adc } = overview
  return (
    <Card
      size="small"
      title={(
        <Space size="middle" wrap>
          <span>架次总览</span>
          <QualityBadge quality={quality} />
          {info?.has_flight === false && <Tag color="default">地面/滑行</Tag>}
          {primary_irs && <Tag color="blue">IRS 端口 {primary_irs.port}</Tag>}
          {primary_adc && <Tag color="cyan">ADC 端口 {primary_adc.port}</Tag>}
        </Space>
      )}
      style={{ marginBottom: 16 }}
    >
      <Row gutter={[16, 16]}>
        <Col xs={12} sm={8} md={6} lg={4}>
          <Statistic title="时长" value={info.duration || 'N/A'} />
        </Col>
        <Col xs={12} sm={8} md={6} lg={5}>
          <Statistic title="时间范围" value={`${info.start_time || 'N/A'} → ${info.end_time || 'N/A'}`} valueStyle={{ fontSize: 14 }} />
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <Statistic title="最大高度 (m)" value={profile.max_altitude_m ?? '—'} />
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <Statistic title="最大地速 (m/s)" value={profile.max_ground_speed ?? '—'} />
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <Statistic title="最大空速 (m/s)" value={profile.max_airspeed ?? '—'} />
        </Col>
        <Col xs={12} sm={8} md={6} lg={3}>
          <Statistic title="最大马赫" value={profile.max_mach ?? '—'} />
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <Statistic title="解析端口数" value={info.dataset_count ?? 0} />
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <Statistic title="飞行阶段数" value={phases.length} />
        </Col>
        <Col xs={12} sm={8} md={6} lg={4}>
          <Statistic title="异常条数" value={anomalies.length} valueStyle={{ color: anomalies.length > 0 ? '#faad14' : undefined }} />
        </Col>
      </Row>

      {narrative && (
        <>
          <Divider style={{ margin: '16px 0 8px' }} orientation="left" plain>自然语言叙述</Divider>
          <div style={{ whiteSpace: 'pre-line', lineHeight: 1.8, color: '#d4d4d8' }}>{narrative}</div>
        </>
      )}

      <Divider style={{ margin: '16px 0 8px' }} orientation="left" plain>详情</Divider>
      <Collapse
        size="small"
        items={[
          {
            key: 'phases',
            label: `飞行阶段（${phases.length}）`,
            children: phases.length === 0 ? (
              <Empty description="未识别出飞行阶段" />
            ) : (
              <Table
                size="small"
                pagination={false}
                rowKey={(_, i) => i}
                dataSource={phases}
                columns={[
                  { title: '阶段', dataIndex: 'phase', width: 110 },
                  { title: '开始', dataIndex: 'start', width: 120 },
                  { title: '结束', dataIndex: 'end', width: 120 },
                  { title: '时长', dataIndex: 'duration', width: 100 },
                ]}
              />
            ),
          },
          {
            key: 'attitude',
            label: `姿态摘要（${Object.keys(attitude).length} 项）`,
            children: !Object.keys(attitude).length ? (
              <Empty description="无姿态数据" />
            ) : (
              <Table
                size="small"
                pagination={false}
                rowKey="name"
                dataSource={['pitch', 'roll', 'heading']
                  .filter((k) => attitude[k])
                  .map((k) => ({ name: k, ...attitude[k] }))}
                columns={[
                  { title: '名称', dataIndex: 'name', width: 100 },
                  { title: '最小 (°)', dataIndex: 'min', width: 100 },
                  { title: '最大 (°)', dataIndex: 'max', width: 100 },
                  { title: '均值 (°)', dataIndex: 'mean', width: 100 },
                  { title: '样本数', dataIndex: 'count', width: 100 },
                ]}
              />
            ),
          },
          {
            key: 'anomalies',
            label: `异常（${anomalies.length}）`,
            children: anomalies.length === 0 ? (
              <Empty description="未检测到物理异常" />
            ) : (
              <>
                <Text type="secondary" style={{ display: 'block', marginBottom: 8, fontSize: 12 }}>
                  时间为解析库 UTC 时间戳对应的北京时间；点击任意一行将滚动到本页底部的「事件分析总结」，可在其中用「定位数据」打开解析结果表。
                </Text>
                <Table
                size="small"
                pagination={{ pageSize: 10 }}
                rowKey={(_, i) => i}
                dataSource={anomalies}
                onRow={() => ({
                  onClick: () => onScrollToEventsSummary?.(),
                  style: { cursor: onScrollToEventsSummary ? 'pointer' : 'default' },
                })}
                columns={[
                  {
                    title: '时间（北京）',
                    dataIndex: 'time',
                    width: 200,
                    ellipsis: true,
                    render: (t, row) => (
                      <Tooltip title={row.time_utc || 'UTC 时刻见解析结果表'}>
                        <span>{t}</span>
                      </Tooltip>
                    ),
                  },
                  {
                    title: '严重度',
                    dataIndex: 'severity',
                    width: 90,
                    render: (s) => (
                      <Tag color={s === 'critical' ? 'red' : s === 'warning' ? 'orange' : 'blue'}>{s || 'info'}</Tag>
                    ),
                  },
                  { title: '类型', dataIndex: 'type', width: 180 },
                  { title: '描述', dataIndex: 'detail', ellipsis: true },
                  { title: '来源', dataIndex: 'source', width: 140 },
                ]}
                />
              </>
            ),
          },
        ]}
      />
    </Card>
  )
}

const MODULE_ROUTE = {
  fms: '/fms-event-analysis/task/',
  fcc: '/fcc-event-analysis/task/',
  auto_flight: '/auto-flight-analysis/task/',
  compare: '/compare/',
}

const MODULE_RUN_ROUTE = {
  fms: '/fms-event-analysis',
  fcc: '/fcc-event-analysis',
  auto_flight: '/auto-flight-analysis',
  compare: '/compare',
}

function statusTag(status) {
  if (status === 'completed') return <Tag color="success" icon={<CheckCircleOutlined />}>已完成</Tag>
  if (status === 'processing') return <Tag color="processing" icon={<PlayCircleOutlined />}>进行中</Tag>
  if (status === 'failed') return <Tag color="error" icon={<CloseCircleOutlined />}>失败</Tag>
  if (status === 'pending') return <Tag color="warning" icon={<WarningOutlined />}>待运行</Tag>
  if (status === 'not_run') return <Tag color="default">未运行</Tag>
  return <Tag>{status || '—'}</Tag>
}

function WorkbenchEventsCard({ summary, loading, taskId, onOpenEvent }) {
  const navigate = useNavigate()

  if (!taskId) return null
  if (loading) {
    return (
      <Card size="small" style={{ marginTop: 16 }}>
        <div style={{ textAlign: 'center', padding: 24 }}><Spin /> 加载事件分析总结…</div>
      </Card>
    )
  }
  const modules = summary?.modules || []

  return (
    <Card
      size="small"
      title="事件分析总结（按解析任务聚合）"
      style={{ marginTop: 16 }}
    >
      <Row gutter={[16, 16]}>
        {modules.map((m) => (
          <Col xs={24} md={12} xl={12} key={m.module}>
            <Card
              size="small"
              type="inner"
              title={(
                <Space>
                  <span>{m.name}</span>
                  {statusTag(m.status)}
                </Space>
              )}
              extra={(
                m.task_id ? (
                  <Button
                    type="link"
                    size="small"
                    icon={<RightOutlined />}
                    onClick={() => navigate(`${MODULE_ROUTE[m.module]}${m.task_id}`)}
                  >进入该模块</Button>
                ) : (
                  <Button
                    type="link"
                    size="small"
                    icon={<PlayCircleOutlined />}
                    onClick={() => navigate(MODULE_RUN_ROUTE[m.module])}
                  >前往运行</Button>
                )
              )}
            >
              {m.status === 'not_run' ? (
                <Empty description="尚未运行该模块分析" />
              ) : (
                <>
                  <Space wrap size="middle" style={{ marginBottom: 8 }}>
                    {Object.entries(m.counts || {}).map(([k, v]) => (
                      <Tag key={k} color="blue">{k}: {v}</Tag>
                    ))}
                    {m.overall_result && (
                      <Tag color={m.overall_result === 'pass' ? 'success' : m.overall_result === 'warning' ? 'warning' : 'error'}>
                        综合: {m.overall_result}
                      </Tag>
                    )}
                  </Space>
                  {(m.top_events || []).length === 0 ? (
                    <Empty description="暂无 top 事件" />
                  ) : (
                    <Table
                      size="small"
                      pagination={false}
                      rowKey={(_, i) => `${m.module}-${i}`}
                      dataSource={m.top_events}
                      columns={[
                        {
                          title: '时间',
                          dataIndex: 'time_str',
                          width: 120,
                          render: (v, r) => v || (r.ts != null ? Number(r.ts).toFixed(2) : '—'),
                        },
                        { title: '端口', dataIndex: 'port', width: 80, render: (v) => v ?? '—' },
                        { title: '事件', dataIndex: 'title', ellipsis: true },
                        {
                          title: '操作',
                          width: 110,
                          render: (_, r) => (
                            <Button
                              size="small"
                              type="link"
                              icon={<DatabaseOutlined />}
                              disabled={r.parse_ts == null}
                              onClick={() => onOpenEvent(r)}
                            >
                              定位数据
                            </Button>
                          ),
                        },
                      ]}
                    />
                  )}
                </>
              )}
            </Card>
          </Col>
        ))}
      </Row>
    </Card>
  )
}

function WorkbenchPage() {
  const { sortieId } = useParams()
  if (!sortieId) {
    return <WorkbenchPicker />
  }
  return <WorkbenchDetail sortieId={sortieId} />
}

export default WorkbenchPage
