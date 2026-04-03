import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Select, Button, Space, message, Row, Col, Spin, Empty, Checkbox, Tag
} from 'antd'
import {
  ArrowLeftOutlined, DownloadOutlined, ReloadOutlined
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { parseApi } from '../services/api'
import dayjs from 'dayjs'

const { Option } = Select

const ANALYSIS_COLORS = ['#58a6ff', '#3fb950', '#d29922', '#a371f7', '#f85149', '#14b8a6']

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

function AnalysisPage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const [task, setTask] = useState(null)
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(true)
  const [activePort, setActivePort] = useState(null)
  const [availableFields, setAvailableFields] = useState([])
  const [selectedFields, setSelectedFields] = useState([])
  const [chartData, setChartData] = useState({})
  const [chartLoading, setChartLoading] = useState(false)

  useEffect(() => {
    loadTask()
  }, [taskId])

  useEffect(() => {
    if (activePort) {
      loadAvailableFields()
    }
  }, [activePort])

  useEffect(() => {
    if (selectedFields.length > 0) {
      loadChartData()
    }
  }, [selectedFields])

  const loadTask = async () => {
    setLoading(true)
    try {
      const res = await parseApi.getTask(taskId)
      setTask(res.data.task)
      setResults(res.data.results || [])
      
      if (res.data.results?.length > 0) {
        setActivePort(res.data.results[0].port_number)
      }
    } catch (err) {
      message.error('加载任务详情失败')
    } finally {
      setLoading(false)
    }
  }

  const loadAvailableFields = async () => {
    try {
      const res = await parseApi.getData(taskId, activePort, { page: 1, page_size: 1 })
      const cols = (res.data.columns || []).filter(c => c !== 'timestamp' && c !== 'raw_data')
      setAvailableFields(cols)
      setSelectedFields([])
      setChartData({})
    } catch (err) {
      message.error('加载字段列表失败')
    }
  }

  const loadChartData = async () => {
    setChartLoading(true)
    const newData = {}
    
    try {
      for (const field of selectedFields) {
        if (!chartData[field]) {
          const res = await parseApi.getTimeSeries(taskId, activePort, field, {
            max_points: 2000
          })
          newData[field] = {
            timestamps: res.data.timestamps,
            values: res.data.values,
          }
        } else {
          newData[field] = chartData[field]
        }
      }
      setChartData(newData)
    } catch (err) {
      message.error('加载时序数据失败')
    } finally {
      setChartLoading(false)
    }
  }

  const getChartOption = () => {
    if (selectedFields.length === 0 || Object.keys(chartData).length === 0) {
      return {}
    }

    const allSeriesData = {}
    const series = selectedFields.map((field, index) => {
      const data = chartData[field]
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

    const yAxis = selectedFields.length > 1 ? [
      {
        type: 'value', name: selectedFields[0],
        axisLabel: { color: '#8b949e' },
        axisLine: { lineStyle: { color: '#30363d' } },
        splitLine: { lineStyle: { color: '#30363d' } },
      },
      {
        type: 'value', name: selectedFields[1] || '',
        axisLabel: { color: '#8b949e' },
        axisLine: { lineStyle: { color: '#30363d' } },
        splitLine: { show: false },
      }
    ] : {
      type: 'value',
      axisLabel: { color: '#8b949e' },
      axisLine: { lineStyle: { color: '#30363d' } },
      splitLine: { lineStyle: { color: '#30363d' } },
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
            const color = ANALYSIS_COLORS[idx % ANALYSIS_COLORS.length]
            html += `<div style="display:flex;justify-content:space-between;gap:20px">
              <span><span style="display:inline-block;margin-right:4px;border-radius:50%;width:10px;height:10px;background:${color}"></span> ${name}</span>
              <span style="font-family:JetBrains Mono">${val?.toFixed(6) ?? '-'}</span>
            </div>`
          })
          return html
        }
      },
      legend: { data: selectedFields, textStyle: { color: '#8b949e' }, top: 10 },
      grid: {
        left: 60,
        right: selectedFields.length > 1 ? 60 : 40,
        top: 60, bottom: 60,
      },
      xAxis: {
        type: 'time', axisPointer: { snap: true },
        axisLabel: { color: '#8b949e', formatter: (value) => dayjs(value).format('HH:mm:ss') },
        axisLine: { lineStyle: { color: '#30363d' } },
        splitLine: { show: false },
      },
      yAxis, series,
      dataZoom: [
        { type: 'inside', start: 0, end: 100 },
        {
          type: 'slider', start: 0, end: 100, height: 20, bottom: 10,
          borderColor: '#30363d', backgroundColor: '#161b22',
          fillerColor: 'rgba(45, 85, 130, 0.3)',
          handleStyle: { color: '#58a6ff' }, textStyle: { color: '#8b949e' },
        }
      ],
      color: ANALYSIS_COLORS,
    }
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 100 }}>
        <Spin size="large" />
      </div>
    )
  }

  return (
    <div className="fade-in">
      {/* 控制面板 */}
      <Card style={{ marginBottom: 24 }}>
        <Row gutter={24} align="middle">
          <Col span={1}>
            <Button
              icon={<ArrowLeftOutlined />}
              onClick={() => navigate(`/tasks/${taskId}`)}
            />
          </Col>
          <Col span={5}>
            <div style={{ color: '#8b949e', marginBottom: 4 }}>选择端口</div>
            <Select
              value={activePort}
              onChange={(val) => {
                setActivePort(val)
                setSelectedFields([])
                setChartData({})
              }}
              style={{ width: '100%' }}
            >
              {results.map(r => (
                <Option key={r.port_number} value={r.port_number}>
                  <Space>
                    <span className="mono">{r.port_number}</span>
                    {r.message_name && <Tag color="blue">{r.message_name}</Tag>}
                  </Space>
                </Option>
              ))}
            </Select>
          </Col>
          <Col span={14}>
            <div style={{ color: '#8b949e', marginBottom: 4 }}>选择字段（可多选）</div>
            <Select
              mode="multiple"
              value={selectedFields}
              onChange={setSelectedFields}
              style={{ width: '100%' }}
              placeholder="选择要分析的字段"
              maxTagCount={4}
            >
              {availableFields.map(field => (
                <Option key={field} value={field}>{field}</Option>
              ))}
            </Select>
          </Col>
          <Col span={4}>
            <Button
              icon={<ReloadOutlined />}
              onClick={loadChartData}
              loading={chartLoading}
              disabled={selectedFields.length === 0}
            >
              刷新图表
            </Button>
          </Col>
        </Row>
      </Card>

      {/* 图表 */}
      <Card title="时序分析">
        {selectedFields.length === 0 ? (
          <Empty description="请选择要分析的字段" />
        ) : chartLoading ? (
          <div style={{ textAlign: 'center', padding: 100 }}>
            <Spin size="large" />
          </div>
        ) : (
          <ReactECharts
            option={getChartOption()}
            style={{ height: 500 }}
            notMerge={true}
          />
        )}
      </Card>

      {/* 快速选择 */}
      {availableFields.length > 0 && (
        <Card title="快速选择字段" style={{ marginTop: 24 }}>
          <Checkbox.Group
            value={selectedFields}
            onChange={setSelectedFields}
          >
            <Row gutter={[16, 16]}>
              {availableFields.map(field => (
                <Col span={6} key={field}>
                  <Checkbox value={field}>
                    <span className="mono">{field}</span>
                  </Checkbox>
                </Col>
              ))}
            </Row>
          </Checkbox.Group>
        </Card>
      )}
    </div>
  )
}

export default AnalysisPage
