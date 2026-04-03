import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import {
  Card, Table, Tabs, Tag, Button, Space, message, Statistic, Row, Col,
  Spin, Empty, Select, Radio, Checkbox, Alert, Progress, InputNumber, Divider,
} from 'antd'
import {
  DownloadOutlined, LineChartOutlined, ReloadOutlined,
  DatabaseOutlined, ApiOutlined, RocketOutlined,
  DesktopOutlined, FilterOutlined,
  BarChartOutlined, SwapOutlined, WarningOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { parseApi } from '../services/api'
import dayjs from 'dayjs'

const { Option } = Select

const CHART_COLORS = [
  '#58a6ff', '#3fb950', '#d29922', '#a371f7', '#f85149',
  '#14b8a6', '#f59e0b', '#ef4444', '#6366f1', '#84cc16'
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

function binarySearchNearest(data, targetTime) {
  if (!data || data.length === 0) return null
  let lo = 0, hi = data.length - 1
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (data[mid][0] < targetTime) lo = mid + 1
    else hi = mid
  }
  if (lo > 0 && Math.abs(data[lo - 1][0] - targetTime) < Math.abs(data[lo][0] - targetTime)) lo--
  return data[lo][1]
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

function ResultPage() {
  const { taskId } = useParams()
  const [task, setTask] = useState(null)
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(true)
  const [activeResult, setActiveResult] = useState(null)
  const [portData, setPortData] = useState([])
  const [portColumns, setPortColumns] = useState([])
  const [dataLoading, setDataLoading] = useState(false)
  const [pagination, setPagination] = useState({
    current: 1, pageSize: 100, total: 0,
  })
  const [selectedDevice, setSelectedDevice] = useState(null)
  const [selectedParser, setSelectedParser] = useState(null)

  const [mainTab, setMainTab] = useState('table')

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
  // cross_port mode
  const [cpSelectedResults, setCpSelectedResults] = useState([])
  const [cpCommonFields, setCpCommonFields] = useState([])
  const [cpSelectedCommonFields, setCpSelectedCommonFields] = useState([])
  const [cpSelectedUniqueFields, setCpSelectedUniqueFields] = useState({})
  const [cpChartData, setCpChartData] = useState({})
  const [cpFieldsPerResult, setCpFieldsPerResult] = useState({})
  const [cpSkippedSeries, setCpSkippedSeries] = useState([])
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

  useEffect(() => {
    if (activeResult) loadPortData()
  }, [activeResult, pagination.current, pagination.pageSize])

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
      const cols = (res.data.columns || []).map(col => ({
        title: col, dataIndex: col, key: col,
        width: col === 'timestamp' ? 180 : col === '核对' ? 560 : 120,
        render: (value) => {
          if (col === 'timestamp') return dayjs(value * 1000).format('YYYY-MM-DD HH:mm:ss.SSS')
          if (col === '核对') {
            return (
              <span
                className="mono"
                style={{
                  whiteSpace: 'normal',
                  wordBreak: 'break-word',
                  display: 'block',
                  maxWidth: 540,
                  lineHeight: 1.45,
                }}
              >
                {value != null ? String(value) : ''}
              </span>
            )
          }
          if (typeof value === 'number') return <span className="mono">{value.toFixed(6)}</span>
          return <span className="mono">{value}</span>
        },
      }))
      setPortColumns(cols)
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
      const params = {}
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
      link.setAttribute('download', `port_${activeResult.port_number}${suffix}.${format === 'excel' ? 'xlsx' : format}`)
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

  const handleBatchExport = async () => {
    if (!results || results.length === 0) return
    const hide = message.loading('正在批量导出，请稍候...', 0)
    try {
      const ports = results.map(r => r.port_number)
      const parserIds = results.map(r => r.parser_profile_id ? String(r.parser_profile_id) : '')
      const res = await parseApi.exportBatch(taskId, ports, parserIds)
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `task_${taskId}_all_ports.xlsx`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
      hide()
      message.success(`已导出 ${ports.length} 个端口的数据`)
    } catch (err) {
      hide()
      message.error('批量导出失败: ' + (err.response?.data?.detail || err.message))
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
      const cols = (res.data.columns || []).filter(c => !SKIP_FIELDS.has(c))
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
    if (!spActiveResult || spSelectedFields.length === 0) return
    setChartLoading(true)
    try {
      const newData = {}
      await Promise.all(spSelectedFields.map(async (field) => {
        if (spChartData[field]) {
          newData[field] = spChartData[field]
          return
        }
        const params = { max_points: 2000 }
        if (spActiveResult.parser_profile_id) params.parser_id = spActiveResult.parser_profile_id
        const res = await parseApi.getTimeSeries(taskId, spActiveResult.port_number, field, params)
        newData[field] = { timestamps: res.data.timestamps, values: res.data.values }
      }))
      setSpChartData(newData)
    } catch {
      message.error('加载时序数据失败')
    } finally {
      setChartLoading(false)
    }
  }, [taskId, spActiveResult, spSelectedFields, spChartData])

  useEffect(() => {
    if (compareMode === 'single_port' && spSelectedFields.length > 0) {
      loadSpChartData()
    }
  }, [spSelectedFields])

  const getSpChartOption = () => {
    if (spSelectedFields.length === 0 || Object.keys(spChartData).length === 0) return {}
    const allSeriesData = {}
    const series = spSelectedFields.map((field, index) => {
      const data = spChartData[field]
      if (!data) return null
      const points = data.timestamps.map((t, i) => [t * 1000, data.values[i]])
      allSeriesData[field] = points
      return {
        name: field, type: 'line', data: points,
        smooth: true, symbol: 'circle', symbolSize: 4, showSymbol: false,
        lineStyle: { width: 1.5 },
        emphasis: { focus: 'series', lineStyle: { width: 3 }, itemStyle: { borderWidth: 2 } },
        yAxisIndex: index < 2 ? index : 0,
      }
    }).filter(Boolean)

    const seriesNames = series.map(s => s.name)

    const yAxis = spSelectedFields.length > 1 ? [
      { type: 'value', name: spSelectedFields[0],
        axisLabel: { color: '#8b949e' }, axisLine: { lineStyle: { color: '#30363d' } },
        splitLine: { lineStyle: { color: '#30363d' } } },
      { type: 'value', name: spSelectedFields[1] || '',
        axisLabel: { color: '#8b949e' }, axisLine: { lineStyle: { color: '#30363d' } },
        splitLine: { show: false } }
    ] : {
      type: 'value', axisLabel: { color: '#8b949e' },
      axisLine: { lineStyle: { color: '#30363d' } },
      splitLine: { lineStyle: { color: '#30363d' } }
    }

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis', backgroundColor: '#161b22', borderColor: '#30363d',
        textStyle: { color: '#c9d1d9' },
        axisPointer: {
          type: 'cross', snap: true,
          crossStyle: { color: '#8b949e' },
          lineStyle: { color: '#58a6ff', type: 'dashed' },
          label: { backgroundColor: '#21262d', color: '#c9d1d9' },
        },
        formatter: (params) => {
          if (!params || params.length === 0) return ''
          const time = params[0].value[0]
          let html = `<div style="font-weight:600;margin-bottom:8px">${dayjs(time).format('HH:mm:ss.SSS')}</div>`
          const matched = new Set(params.map(p => p.seriesName))
          params.forEach(p => {
            html += `<div style="display:flex;justify-content:space-between;gap:20px">
              <span>${p.marker} ${p.seriesName}</span>
              <span style="font-family:JetBrains Mono">${p.value[1]?.toFixed(6) ?? '-'}</span>
            </div>`
          })
          seriesNames.forEach((name, idx) => {
            if (matched.has(name)) return
            const val = binarySearchNearest(allSeriesData[name], time)
            const color = CHART_COLORS[idx % CHART_COLORS.length]
            html += `<div style="display:flex;justify-content:space-between;gap:20px">
              <span><span style="display:inline-block;margin-right:4px;border-radius:50%;width:10px;height:10px;background:${color}"></span> ${name}</span>
              <span style="font-family:JetBrains Mono">${val?.toFixed(6) ?? '-'}</span>
            </div>`
          })
          return html
        }
      },
      legend: { data: spSelectedFields, textStyle: { color: '#8b949e' }, top: 10 },
      grid: { left: 60, right: spSelectedFields.length > 1 ? 60 : 40, top: 60, bottom: 60 },
      xAxis: {
        type: 'time',
        axisPointer: { snap: true },
        axisLabel: { color: '#8b949e', formatter: (v) => dayjs(v).format('HH:mm:ss') },
        axisLine: { lineStyle: { color: '#30363d' } }, splitLine: { show: false }
      },
      yAxis, series,
      dataZoom: [
        { type: 'inside', start: 0, end: 100 },
        { type: 'slider', start: 0, end: 100, height: 20, bottom: 10,
          borderColor: '#30363d', backgroundColor: '#161b22',
          fillerColor: 'rgba(88, 166, 255, 0.2)',
          handleStyle: { color: '#58a6ff' }, textStyle: { color: '#8b949e' } }
      ],
      color: CHART_COLORS,
    }
  }

  // ======== Cross-port multi-field analysis ========

  const loadCpFieldsForResults = useCallback(async (selectedKeys) => {
    const fieldsMap = {}
    await Promise.all(selectedKeys.map(async (key) => {
      const result = results.find(r => getResultKey(r) === key)
      if (!result) return
      try {
        const params = { page: 1, page_size: 1 }
        if (result.parser_profile_id) params.parser_id = result.parser_profile_id
        const res = await parseApi.getData(taskId, result.port_number, params)
        const cols = (res.data.columns || []).filter(c => !SKIP_FIELDS.has(c))
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
      const points = d.timestamps.map((t, i) => [t * 1000, d.values[i]])
      allSeriesData[d.label] = points
      return {
        name: d.label, type: 'line', data: points,
        smooth: true, symbol: 'circle', symbolSize: 4, showSymbol: false,
        lineStyle: { width: 1.5 },
        emphasis: { focus: 'series', lineStyle: { width: 3 }, itemStyle: { borderWidth: 2 } },
      }
    })

    const seriesNames = series.map(s => s.name)

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis', backgroundColor: '#161b22', borderColor: '#30363d',
        textStyle: { color: '#c9d1d9' },
        axisPointer: {
          type: 'cross', snap: true,
          crossStyle: { color: '#8b949e' },
          lineStyle: { color: '#58a6ff', type: 'dashed' },
          label: { backgroundColor: '#21262d', color: '#c9d1d9' },
        },
        formatter: (params) => {
          if (!params || params.length === 0) return ''
          const time = params[0].value[0]
          let html = `<div style="font-weight:600;margin-bottom:8px">${dayjs(time).format('HH:mm:ss.SSS')}</div>`
          const matched = new Set(params.map(p => p.seriesName))
          params.forEach(p => {
            html += `<div style="display:flex;justify-content:space-between;gap:20px">
              <span>${p.marker} ${p.seriesName}</span>
              <span style="font-family:JetBrains Mono">${p.value[1]?.toFixed(6) ?? '-'}</span>
            </div>`
          })
          seriesNames.forEach((name, idx) => {
            if (matched.has(name)) return
            const val = binarySearchNearest(allSeriesData[name], time)
            const color = CHART_COLORS[idx % CHART_COLORS.length]
            html += `<div style="display:flex;justify-content:space-between;gap:20px">
              <span><span style="display:inline-block;margin-right:4px;border-radius:50%;width:10px;height:10px;background:${color}"></span> ${name}</span>
              <span style="font-family:JetBrains Mono">${val?.toFixed(6) ?? '-'}</span>
            </div>`
          })
          return html
        }
      },
      legend: {
        data: seriesNames,
        textStyle: { color: '#8b949e' }, top: 10,
        type: 'scroll',
      },
      grid: { left: 60, right: 40, top: 60, bottom: 60 },
      xAxis: {
        type: 'time',
        axisPointer: { snap: true },
        axisLabel: { color: '#8b949e', formatter: (v) => dayjs(v).format('HH:mm:ss') },
        axisLine: { lineStyle: { color: '#30363d' } }, splitLine: { show: false }
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#8b949e' },
        axisLine: { lineStyle: { color: '#30363d' } },
        splitLine: { lineStyle: { color: '#30363d' } }
      },
      series,
      dataZoom: [
        { type: 'inside', start: 0, end: 100 },
        { type: 'slider', start: 0, end: 100, height: 20, bottom: 10,
          borderColor: '#30363d', backgroundColor: '#161b22',
          fillerColor: 'rgba(88, 166, 255, 0.2)',
          handleStyle: { color: '#58a6ff' }, textStyle: { color: '#8b949e' } }
      ],
      color: CHART_COLORS,
    }
  }

  // ======== Render helpers ========

  const renderComparePanel = () => {
    if (compareMode === 'single_port') {
      return (
        <>
          <Row gutter={16} align="bottom" style={{ marginBottom: 24 }}>
            <Col flex="240px">
              <div style={{ color: '#8b949e', marginBottom: 8, fontSize: 13 }}>选择端口</div>
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
              <div style={{ color: '#8b949e', marginBottom: 8, fontSize: 13 }}>选择字段（可多选）</div>
              <Select
                mode="multiple"
                value={spSelectedFields}
                onChange={setSpSelectedFields}
                style={{ width: '100%' }}
                placeholder="选择要分析的字段"
                maxTagCount={6}
                disabled={spAvailableFields.length === 0}
              >
                {spAvailableFields.map(f => <Option key={f} value={f}>{f}</Option>)}
              </Select>
            </Col>
            <Col flex="100px">
              <Button
                type="primary"
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

          {spSelectedFields.length === 0 ? (
            <Empty description="请选择端口和字段" style={{ padding: '60px 0' }} />
          ) : chartLoading ? (
            <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
          ) : Object.keys(spChartData).length > 0 ? (
            <ReactECharts option={getSpChartOption()} style={{ height: 500 }} notMerge />
          ) : null}

          {spAvailableFields.length > 0 && (
            <div style={{ marginTop: 24, padding: '16px', backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '8px' }}>
              <div style={{ color: '#8b949e', marginBottom: 12, fontSize: 13, fontWeight: 500 }}>快速选择字段</div>
              <Checkbox.Group value={spSelectedFields} onChange={setSpSelectedFields} style={{ width: '100%' }}>
                <Row gutter={[16, 12]}>
                  {spAvailableFields.map(f => (
                    <Col span={6} key={f}>
                      <Checkbox value={f}><span className="mono" style={{ fontSize: 13, color: '#c9d1d9' }}>{f}</span></Checkbox>
                    </Col>
                  ))}
                </Row>
              </Checkbox.Group>
            </div>
          )}
        </>
      )
    }

    // cross_port mode
    return (
      <>
        <Row gutter={16} align="bottom" style={{ marginBottom: 24 }}>
          <Col flex="auto">
            <div style={{ color: '#8b949e', marginBottom: 8, fontSize: 13 }}>选择端口/设备（至少两个）</div>
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
                    {r.source_device && <Tag color="orange" style={{ margin: 0, background: 'rgba(210, 153, 34, 0.15)', borderColor: '#d29922', color: '#d29922' }}>{r.source_device}</Tag>}
                    {r.parser_profile_name && <Tag color="green" style={{ margin: 0, background: 'rgba(63, 185, 80, 0.15)', borderColor: '#3fb950', color: '#3fb950' }}>{r.parser_profile_name}</Tag>}
                  </Space>
                </Option>
              ))}
            </Select>
          </Col>
          <Col flex="100px">
            <Button
              type="primary"
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
          <div style={{ marginBottom: 16, padding: 16, backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: 8 }}>
            <div style={{ color: '#58a6ff', marginBottom: 12, fontSize: 13, fontWeight: 500 }}>
              共同字段 <span style={{ color: '#8b949e', fontWeight: 400 }}>（对所有已选设备生效）</span>
            </div>
            <Checkbox.Group value={cpSelectedCommonFields} onChange={setCpSelectedCommonFields} style={{ width: '100%' }}>
              <Row gutter={[16, 12]}>
                {cpCommonFields.map(f => (
                  <Col span={6} key={f}>
                    <Checkbox value={f}><span className="mono" style={{ fontSize: 13, color: '#c9d1d9' }}>{f}</span></Checkbox>
                  </Col>
                ))}
              </Row>
            </Checkbox.Group>
          </div>
        )}

        {cpSelectedResults.length >= 2 && cpSelectedResults.some(key => (cpUniqueFieldsPerResult[key] || []).length > 0) && (
          <div style={{ marginBottom: 16, padding: 16, backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: 8 }}>
            <div style={{ color: '#d29922', marginBottom: 16, fontSize: 13, fontWeight: 500 }}>
              设备独有字段 <span style={{ color: '#8b949e', fontWeight: 400 }}>（仅对对应设备生效）</span>
            </div>
            {cpSelectedResults.map(key => {
              const result = results.find(r => getResultKey(r) === key)
              const uniqueFields = cpUniqueFieldsPerResult[key] || []
              if (uniqueFields.length === 0) return null
              return (
                <div key={key} style={{ marginBottom: 16, paddingBottom: 12, borderBottom: '1px solid #21262d' }}>
                  <div style={{ color: '#c9d1d9', marginBottom: 8, fontSize: 13 }}>
                    {result && (
                      <Space size={4}>
                        <span className="mono" style={{ fontWeight: 600 }}>{result.port_number}</span>
                        {result.source_device && <Tag color="orange" style={{ margin: 0, background: 'rgba(210, 153, 34, 0.15)', borderColor: '#d29922', color: '#d29922' }}>{result.source_device}</Tag>}
                        {result.parser_profile_name && <Tag color="green" style={{ margin: 0, background: 'rgba(63, 185, 80, 0.15)', borderColor: '#3fb950', color: '#3fb950' }}>{result.parser_profile_name}</Tag>}
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
                          <Checkbox value={f}><span className="mono" style={{ fontSize: 13, color: '#c9d1d9' }}>{f}</span></Checkbox>
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
              <span style={{ color: '#8b949e', fontSize: 13 }}>
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

        {cpHasSelection && cpSelectedResults.length >= 2 ? (
          chartLoading ? (
            <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
          ) : Object.keys(cpChartData).length > 0 ? (
            <ReactECharts option={getCpChartOption()} style={{ height: 500 }} notMerge />
          ) : null
        ) : null}
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
      return <Empty description="暂无解析结果" />
    }
    return (
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
          <Space wrap>
            {(deviceList.length > 0 || parserList.length > 1) && (
              <>
                <span style={{ color: '#8b949e' }}><FilterOutlined /> 筛选:</span>
                {deviceList.length > 0 && (
                  <Select placeholder="按设备筛选" allowClear style={{ width: 160 }}
                    size="middle" value={selectedDevice} onChange={handleDeviceFilter}>
                    {deviceList.map(d => <Option key={d} value={d}>{d}</Option>)}
                  </Select>
                )}
                {parserList.length > 1 && (
                  <Select placeholder="按解析器筛选" allowClear style={{ width: 160 }}
                    size="middle" value={selectedParser} onChange={handleParserFilter}>
                    {parserList.map(p => <Option key={p.id} value={p.id}>{p.name}</Option>)}
                  </Select>
                )}
              </>
            )}
          </Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => loadAnomalyDefaults()}
            disabled={anomalyDefaultsLoading || !activeResult}
          >
            刷新字段与默认阈值
          </Button>
        </div>

        <Tabs
          items={tabItems}
          activeKey={activeResult ? getResultKey(activeResult) : undefined}
          onChange={(key) => {
            const result = filteredResults.find(r => getResultKey(r) === key)
            if (result) {
              setActiveResult(result)
              setPagination(prev => ({ ...prev, current: 1 }))
            }
          }}
          style={{ marginBottom: 16 }}
        />

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
                  <span style={{ color: '#8b949e' }}>分析字段:</span>
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
                      <Checkbox value={f}><span className="mono">{f}</span></Checkbox>
                    </Col>
                  ))}
                </Row>
              </Checkbox.Group>

              <Divider orientation="left" plain style={{ color: '#8b949e' }}>
                跳变阈值（%，相对卡尔曼预测值）
              </Divider>
              <Row gutter={[12, 12]} style={{ marginBottom: 20 }}>
                {anomalySelectedFields.map((f) => (
                  <Col xs={24} sm={12} md={8} key={f}>
                    <Space>
                      <span className="mono" style={{ color: '#c9d1d9', minWidth: 120 }}>{f}</span>
                      <InputNumber
                        min={0.01}
                        max={500}
                        step={0.5}
                        value={anomalyThresholdEdits[f]}
                        onChange={(v) => setAnomalyThresholdEdits((prev) => ({ ...prev, [f]: v }))}
                        size="small"
                      />
                      <span style={{ color: '#8b949e', fontSize: 12 }}>
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
                <Statistic title="跳变告警数" value={anomalyResult.summary?.jump_count ?? 0} valueStyle={{ color: '#f85149' }} />
              </Col>
              <Col span={6}>
                <Statistic title="卡死区间数" value={anomalyResult.summary?.stuck_count ?? 0} valueStyle={{ color: '#d29922' }} />
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
                <div style={{ color: '#8b949e', marginBottom: 8 }}>异常时间点速览（点击复制时间戳）</div>
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
                <span style={{ color: '#8b949e' }}>按字段筛选:</span>
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
                <span style={{ color: '#8b949e' }}>按字段筛选:</span>
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
            <h2 style={{ marginTop: 28, marginBottom: 8, color: '#c9d1d9', fontWeight: 600 }}>
              {task.status === 'pending' ? '等待开始解析…' : '正在解析数据…'}
            </h2>
            <p className="mono" style={{ color: '#8b949e', marginBottom: 24, wordBreak: 'break-all' }}>
              {task.filename}
            </p>
            <Progress
              percent={task.status === 'pending' ? 0 : pct}
              status={task.status === 'pending' ? 'normal' : 'active'}
              strokeColor={{ from: '#58a6ff', to: '#3fb950' }}
              style={{ marginBottom: 12 }}
            />
            <p style={{ color: '#8b949e', fontSize: 13 }}>
              {task.status === 'pending'
                ? '任务已排队，解析即将开始'
                : `已读取约 ${pct}%（按文件字节估算，保存结果阶段可能停留在 99%）`}
            </p>
          </div>
        </Card>
      </div>
    )
  }

  const tabItems = filteredResults.map(result => ({
    key: getResultKey(result),
    label: (
      <Space>
        <span className="mono">{result.port_number}</span>
        {result.source_device && <Tag color="orange" style={{ background: 'rgba(210, 153, 34, 0.15)', borderColor: '#d29922', color: '#d29922' }}>{result.source_device}</Tag>}
        {result.parser_profile_name && parserList.length > 1 && (
          <Tag color="green" style={{ background: 'rgba(63, 185, 80, 0.15)', borderColor: '#3fb950', color: '#3fb950' }}>{result.parser_profile_name}</Tag>
        )}
        <Tag style={{ background: '#21262d', borderColor: '#30363d', color: '#8b949e' }}>{result.record_count.toLocaleString()} 条</Tag>
      </Space>
    ),
  }))

  return (
    <div className="fade-in">
      {/* Task overview */}
      <Card style={{ marginBottom: 24 }}>
        <Row gutter={[24, 16]} align="middle">
          <Col xs={24} sm={12} md={8} lg={6}>
            <Statistic
              title="文件名" value={task.filename}
              valueStyle={{ fontSize: 14, fontFamily: 'JetBrains Mono', wordBreak: 'break-all', color: '#c9d1d9' }}
            />
          </Col>
          <Col xs={12} sm={6} md={4} lg={4}>
            <Statistic
              title={<Space size={4}><ApiOutlined style={{ color: '#58a6ff' }} /><span>网络配置</span></Space>}
              value={task.network_config_name ? `${task.network_config_name} ${task.network_config_version}` : '扫描模式'}
              valueStyle={{ fontSize: 13, color: task.network_config_name ? '#58a6ff' : '#8b949e' }}
            />
          </Col>
          <Col xs={12} sm={6} md={4} lg={4}>
            <Statistic
              title={<Space size={4}><RocketOutlined style={{ color: '#3fb950' }} /><span>解析器</span></Space>}
              value={
                task.device_parsers?.length > 0
                  ? `${task.device_parsers.length} 设备`
                  : task.parser_profiles?.length > 0
                    ? `${task.parser_profiles.length} 个解析器`
                    : (task.parser_profile_name || '-')
              }
              valueStyle={{ fontSize: 13, color: '#3fb950' }}
            />
          </Col>
          <Col xs={12} sm={6} md={4} lg={3}>
            <Statistic title="解析端口数" value={results.length}
              prefix={<DatabaseOutlined />} valueStyle={{ color: '#3fb950' }} />
          </Col>
          <Col xs={12} sm={6} md={4} lg={3}>
            <Statistic title="总数据量" value={task.parsed_packets}
              valueStyle={{ color: '#d29922' }} />
          </Col>
        </Row>

        {task.device_parsers && task.device_parsers.length > 0 ? (
          <div style={{ marginTop: 16 }}>
            <Space wrap>
              <DesktopOutlined style={{ color: '#d29922' }} />
              <span style={{ color: '#8b949e' }}>设备解析配置:</span>
              {task.device_parsers.map(dp => (
                <Space key={dp.device_name} size={2}>
                  <Tag color="orange" style={{ background: 'rgba(210, 153, 34, 0.15)', borderColor: '#d29922', color: '#d29922' }}>{dp.device_name}</Tag>
                  <span style={{ color: '#8b949e' }}>→</span>
                  <Tag color="green" style={{ background: 'rgba(63, 185, 80, 0.15)', borderColor: '#3fb950', color: '#3fb950' }}>{[dp.parser_profile_name, dp.parser_profile_version].filter(Boolean).join(' ')}</Tag>
                </Space>
              ))}
            </Space>
          </div>
        ) : (
          <>
            {task.selected_devices && task.selected_devices.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <Space>
                  <DesktopOutlined style={{ color: '#d29922' }} />
                  <span style={{ color: '#8b949e' }}>选中设备:</span>
                  {task.selected_devices.map(d => <Tag key={d} color="orange" style={{ background: 'rgba(210, 153, 34, 0.15)', borderColor: '#d29922', color: '#d29922' }}>{d}</Tag>)}
                </Space>
              </div>
            )}
            {task.parser_profiles && task.parser_profiles.length > 1 && (
              <div style={{ marginTop: 8 }}>
                <Space>
                  <RocketOutlined style={{ color: '#3fb950' }} />
                  <span style={{ color: '#8b949e' }}>解析器:</span>
                  {task.parser_profiles.map(p => <Tag key={p.id} color="green" style={{ background: 'rgba(63, 185, 80, 0.15)', borderColor: '#3fb950', color: '#3fb950' }}>{p.name}</Tag>)}
                </Space>
              </div>
            )}
          </>
        )}
      </Card>

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
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
                  <Space>
                    {(deviceList.length > 0 || parserList.length > 1) && (
                      <>
                        <span style={{ color: '#8b949e' }}><FilterOutlined /> 筛选:</span>
                        {deviceList.length > 0 && (
                          <Select placeholder="按设备筛选" allowClear style={{ width: 160 }}
                            size="middle" value={selectedDevice} onChange={handleDeviceFilter}>
                            {deviceList.map(d => <Option key={d} value={d}>{d}</Option>)}
                          </Select>
                        )}
                        {parserList.length > 1 && (
                          <Select placeholder="按解析器筛选" allowClear style={{ width: 160 }}
                            size="middle" value={selectedParser} onChange={handleParserFilter}>
                            {parserList.map(p => <Option key={p.id} value={p.id}>{p.name}</Option>)}
                          </Select>
                        )}
                      </>
                    )}
                  </Space>
            <Space>
                    {activeResult && (
                      <>
                        <Button icon={<DownloadOutlined />} onClick={() => handleExport('csv')}>导出CSV</Button>
                        <Button icon={<DownloadOutlined />} onClick={() => handleExport('excel')}>导出Excel</Button>
                        <Button icon={<DownloadOutlined />} onClick={() => handleExport('parquet')}>导出Parquet</Button>
                      </>
                    )}
                    {results.length > 0 && (
                      <Button type="primary" icon={<DownloadOutlined />} onClick={handleBatchExport}>
                        批量导出全部Excel
              </Button>
                    )}
            </Space>
                </div>

                {filteredResults.length > 0 ? (
          <>
            <Tabs
              items={tabItems}
                      activeKey={activeResult ? getResultKey(activeResult) : undefined}
              onChange={(key) => {
                        const result = filteredResults.find(r => getResultKey(r) === key)
                        if (result) {
                          setActiveResult(result)
                setPagination(prev => ({ ...prev, current: 1 }))
                        }
              }}
            />
            <Table
                      columns={portColumns} dataSource={portData}
                      rowKey={(_, index) => index} loading={dataLoading}
                      scroll={{ x: 'max-content' }} size="small"
              pagination={{
                        ...pagination, showSizeChanger: true, showQuickJumper: true,
                showTotal: (total) => `共 ${total} 条`,
                pageSizeOptions: [50, 100, 200, 500],
                        onChange: (page, pageSize) => setPagination(prev => ({ ...prev, current: page, pageSize })),
              }}
            />
          </>
        ) : (
          <Empty description="暂无解析结果" />
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
    </div>
  )
}

export default ResultPage
