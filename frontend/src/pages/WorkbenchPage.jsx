import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Card, Row, Col, Select, Button, Space, Typography, Spin, Alert, InputNumber,
  Form, Radio, Table, Tag, Empty, message, Tabs, Slider, Switch, Tooltip,
} from 'antd'
import {
  AimOutlined, LeftOutlined, FullscreenOutlined, FullscreenExitOutlined,
  ReloadOutlined, DatabaseOutlined,
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

function WorkbenchPicker() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [tree, setTree] = useState([])

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

  return (
    <div className="fade-in">
      <Card
        title={<><AimOutlined style={{ marginRight: 8 }} />试验工作台</>}
        extra={<Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新架次</Button>}
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          选择一个<strong>试验架次</strong>进入工作台：查看惯导经纬度轨迹、架次内视频，并配置各数据源相对时间对齐偏移。
          经纬度轨迹需先在「任务列表」中完成与本试验相关的<strong>解析任务</strong>（包含惯导端口）。
        </Text>
        <Table
          rowKey="key"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={rows}
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
  const wrapRef = useRef(null)
  const videoElsRef = useRef({})
  /** 每个 fileId 对应 stable ref，避免每次 render 新建函数导致 <video> 反复挂载并死循环 */
  const videoRefCallbacks = useRef(new Map())
  const trajAltChartRef = useRef(null)

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

  useEffect(() => { loadDetail() }, [loadDetail])
  useEffect(() => { loadTasks() }, [loadTasks])

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
      setIrsKey(irsOptions[0].value)
    }
  }, [irsOptions, irsKey])

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

      const params = { max_points: 8000 }
      if (parserId != null) params.parser_id = parserId

      const uniqueVarCols = [...new Set([
        speedCol, altCol, eastVelCol, northVelCol, beijingWallCol,
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

      const ts = latR.data.timestamps || []
      const lat = latR.data.values || []
      const lon = lonR.data.values || []
      const spd = spdR ? (spdR.data.values || []) : []
      const alt = altR ? (altR.data.values || []) : []
      const eastRaw = eastR ? (eastR.data.values || []) : []
      const northRaw = northR ? (northR.data.values || []) : []
      const bjRaw = bjR ? (bjR.data.values || []) : []

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
        groundSpeedVals,
        beijingTimeStrs,
        distM,
        speedColumn: speedCol,
        altColumn: altCol,
        eastVelocityColumn: eastVelCol,
        northVelocityColumn: northVelCol,
        beijingWallClockColumn: beijingWallCol,
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
    if (!distM?.length || !altVals?.some((a) => a != null && Number.isFinite(a))) return null
    const pts = []
    for (let i = 0; i < path.length; i += 1) {
      const a = altVals[i]
      if (a == null || !Number.isFinite(a)) continue
      pts.push([distM[i] / 1000, a, i])
    }
    if (!pts.length) return null
    const dKmMax = Math.max(...distM) / 1000
    const finAlts = altVals.filter((x) => x != null && Number.isFinite(x))
    const aMin = Math.min(...finAlts)
    const aMax = Math.max(...finAlts)
    const xSel = selectedTrajIdx != null && distM[selectedTrajIdx] != null
      ? distM[selectedTrajIdx] / 1000
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
        text: `垂直剖面：${altColumn} — 累计航程（数据来自解析结果列）`,
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
          const lo = path[i]?.[0]
          const la = path[i]?.[1]
          const alt = altVals[i]
          return `累计航程 ${it.axisValueLabel != null ? `${Number(it.axisValueLabel).toFixed(3)} km` : ''}<br/>${altColumn}: ${alt != null ? Number(alt).toFixed(2) : '—'}<br/>时间 ${t != null ? Number(t).toFixed(3) : '—'} s<br/>经度 ${lo != null ? Number(lo).toFixed(6) : '—'}° 纬度 ${la != null ? Number(la).toFixed(6) : '—'}°`
        },
      },
      grid: { left: 56, right: 18, top: 40, bottom: 36 },
      xAxis: {
        type: 'value',
        name: '累计航程 (km)',
        min: 0,
        max: dKmMax,
        axisLabel: { color: '#9393a1', formatter: (v) => Number(v).toFixed(2) },
      },
      yAxis: {
        type: 'value',
        name: altColumn,
        min: aMin,
        max: aMax,
        axisLabel: { color: '#9393a1' },
      },
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
  }, [trajData, selectedTrajIdx])

  useEffect(() => {
    if (!trajData?.distM?.length || !trajData?.altColumn) return undefined
    if (!trajData.altVals?.some((a) => a != null && Number.isFinite(a))) return undefined
    const bind = { zr: null, handler: null }
    const tid = window.setTimeout(() => {
      const chart = trajAltChartRef.current?.getEchartsInstance?.()
      if (!chart) return
      const { distM } = trajData
      const dMaxM = Math.max(...distM)
      const maxPickKm = Math.max((dMaxM / 1000) * 0.02, 1e-6)
      bind.zr = chart.getZr()
      bind.handler = (ev) => {
        const coord = chart.convertFromPixel({ gridIndex: 0 }, [ev.offsetX, ev.offsetY])
        if (!coord || !Number.isFinite(coord[0])) return
        const clickKm = coord[0]
        let best = 0
        let bestD = Infinity
        for (let i = 0; i < distM.length; i += 1) {
          const km = distM[i] / 1000
          const d = Math.abs(km - clickKm)
          if (d < bestD) {
            bestD = d
            best = i
          }
        }
        if (bestD > maxPickKm) return
        setSelectedTrajIdx(best)
      }
      bind.zr.on('click', bind.handler)
    }, 0)
    return () => {
      window.clearTimeout(tid)
      if (bind.zr && bind.handler) bind.zr.off('click', bind.handler)
    }
  }, [trajData])

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
              <Text type="secondary">解析任务</Text>
              <Select
                style={{ minWidth: 260 }}
                placeholder="选择已完成的解析任务"
                value={taskId}
                onChange={setTaskId}
                allowClear
                showSearch
                optionFilterProp="label"
                options={tasks.map((t) => ({
                  value: t.id,
                  label: `#${t.id} ${t.filename || ''} (${t.status})`,
                }))}
              />
              <Text type="secondary">惯导源</Text>
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
              轨迹叠加在 OpenStreetMap 底图上；线段颜色表示地速（由东/北分量计算或解析标量速度列）。垂直剖面与右侧视频仍按解析对齐时间关联选点。
            </Text>
            {trajAltOption && (
              <>
                <Text type="secondary" style={{ display: 'block', marginTop: 12 }}>垂直剖面（与地图同一解析数据源）</Text>
                <ReactECharts
                  ref={trajAltChartRef}
                  option={trajAltOption}
                  style={{ height: 260 }}
                  notMerge
                  lazyUpdate
                  theme="dark"
                />
              </>
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
    </div>
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
