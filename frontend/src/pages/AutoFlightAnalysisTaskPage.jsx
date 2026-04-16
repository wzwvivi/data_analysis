import React, { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Button, Space, message, Row, Col, Spin, Empty, Tag, Table,
  Statistic, Progress, Drawer, Alert, Tabs,
} from 'antd'
import {
  ArrowLeftOutlined, ReloadOutlined, ClockCircleOutlined, DownloadOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { autoFlightAnalysisApi } from '../services/api'

const RATING_COLOR = {
  normal: 'green',
  attention: 'orange',
  heavy: 'red',
}

function AutoFlightAnalysisTaskPage() {
  const { taskId } = useParams()
  const navigate = useNavigate()

  const [task, setTask] = useState(null)
  const [touchdowns, setTouchdowns] = useState([])
  const [steadyStates, setSteadyStates] = useState([])
  const [loading, setLoading] = useState(false)
  const [polling, setPolling] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [detailVisible, setDetailVisible] = useState(false)
  const [detailType, setDetailType] = useState(null) // touchdown / steady
  const [detailData, setDetailData] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const loadTaskDetail = useCallback(async (id) => {
    if (!id) return
    setLoading(true)
    try {
      const tRes = await autoFlightAnalysisApi.getTask(id)
      setTask(tRes.data)
      if (tRes.data.status === 'completed') {
        const [tdRes, ssRes] = await Promise.all([
          autoFlightAnalysisApi.getTouchdowns(id),
          autoFlightAnalysisApi.getSteadyStates(id),
        ])
        setTouchdowns(tdRes.data.items || [])
        setSteadyStates(ssRes.data.items || [])
      } else {
        setTouchdowns([])
        setSteadyStates([])
      }
    } catch {
      message.error('加载任务详情失败')
      setTask(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!taskId) {
      navigate('/auto-flight-analysis', { replace: true })
      return
    }
    loadTaskDetail(taskId)
  }, [taskId, navigate, loadTaskDetail])

  useEffect(() => {
    let timer = null
    if (polling && task?.status === 'processing' && taskId) {
      timer = setInterval(async () => {
        try {
          const res = await autoFlightAnalysisApi.getTask(taskId)
          setTask(res.data)
          if (res.data.status !== 'processing') {
            setPolling(false)
            if (res.data.status === 'completed') {
              message.success('自动飞行性能分析完成')
              loadTaskDetail(taskId)
            } else if (res.data.status === 'failed') {
              message.error(res.data.error_message || '分析失败')
            }
          }
        } catch { /* ignore */ }
      }, 2000)
    }
    return () => { if (timer) clearInterval(timer) }
  }, [polling, task?.status, taskId, loadTaskDetail])

  useEffect(() => {
    if (task?.status === 'processing') setPolling(true)
  }, [task?.status])

  const openTouchdownDetail = async (row) => {
    if (!taskId) return
    setDetailVisible(true)
    setDetailType('touchdown')
    setDetailLoading(true)
    try {
      const res = await autoFlightAnalysisApi.getTouchdownDetail(taskId, row.id)
      setDetailData(res.data)
    } catch {
      message.error('加载触底详情失败')
    } finally {
      setDetailLoading(false)
    }
  }

  const openSteadyDetail = async (row) => {
    if (!taskId) return
    setDetailVisible(true)
    setDetailType('steady')
    setDetailLoading(true)
    try {
      const res = await autoFlightAnalysisApi.getSteadyStateDetail(taskId, row.id)
      setDetailData(res.data)
    } catch {
      message.error('加载稳态详情失败')
    } finally {
      setDetailLoading(false)
    }
  }

  const handleExport = async () => {
    if (!taskId || task?.status !== 'completed') return
    setExporting(true)
    try {
      const res = await autoFlightAnalysisApi.exportResults(taskId)
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `auto_flight_analysis_${taskId}.xlsx`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
      message.success('导出成功')
    } catch (err) {
      message.error(err.response?.data?.detail || '导出失败')
    } finally {
      setExporting(false)
    }
  }

  const isCompleted = task?.status === 'completed'
  const isProcessing = task?.status === 'processing'

  const touchdownColumns = [
    { title: '序号', dataIndex: 'sequence', key: 'sequence', width: 64, align: 'center' },
    { title: '触底时间', dataIndex: 'touchdown_time', key: 'touchdown_time', width: 180 },
    { title: 'IRS1 Vz', dataIndex: 'irs1_vz', key: 'irs1_vz', width: 96, render: (v) => (v == null ? '-' : Number(v).toFixed(3)) },
    { title: 'IRS2 Vz', dataIndex: 'irs2_vz', key: 'irs2_vz', width: 96, render: (v) => (v == null ? '-' : Number(v).toFixed(3)) },
    { title: 'IRS3 Vz', dataIndex: 'irs3_vz', key: 'irs3_vz', width: 96, render: (v) => (v == null ? '-' : Number(v).toFixed(3)) },
    { title: 'Vz差值', dataIndex: 'vz_spread', key: 'vz_spread', width: 96, render: (v) => (v == null ? '-' : Number(v).toFixed(3)) },
    { title: 'IRS1 |Az|峰值', dataIndex: 'irs1_az_peak', key: 'irs1_az_peak', width: 110, render: (v) => (v == null ? '-' : Number(v).toFixed(3)) },
    { title: 'IRS2 |Az|峰值', dataIndex: 'irs2_az_peak', key: 'irs2_az_peak', width: 110, render: (v) => (v == null ? '-' : Number(v).toFixed(3)) },
    { title: 'IRS3 |Az|峰值', dataIndex: 'irs3_az_peak', key: 'irs3_az_peak', width: 110, render: (v) => (v == null ? '-' : Number(v).toFixed(3)) },
    { title: 'Az峰值差值', dataIndex: 'az_peak_spread', key: 'az_peak_spread', width: 104, render: (v) => (v == null ? '-' : Number(v).toFixed(3)) },
    {
      title: '评级',
      dataIndex: 'rating',
      key: 'rating',
      width: 80,
      render: (v) => <Tag color={RATING_COLOR[v] || 'default'}>{v || '-'}</Tag>,
    },
    {
      title: '操作',
      key: 'op',
      width: 80,
      render: (_, row) => <Button type="link" onClick={() => openTouchdownDetail(row)}>曲线</Button>,
    },
  ]

  const steadyColumns = [
    { title: '序号', dataIndex: 'sequence', key: 'sequence', width: 64, align: 'center' },
    { title: '开始时间', dataIndex: 'start_time', key: 'start_time', width: 180 },
    { title: '结束时间', dataIndex: 'end_time', key: 'end_time', width: 180 },
    { title: '持续(s)', dataIndex: 'duration_s', key: 'duration_s', width: 80, render: (v) => (v == null ? '-' : Number(v).toFixed(1)) },
    { title: '高度RMS', dataIndex: 'alt_rms', key: 'alt_rms', width: 96, render: (v) => (v == null ? '-' : Number(v).toFixed(3)) },
    { title: '水平RMS', dataIndex: 'lat_rms', key: 'lat_rms', width: 96, render: (v) => (v == null ? '-' : Number(v).toFixed(3)) },
    { title: '速度RMS', dataIndex: 'spd_rms', key: 'spd_rms', width: 96, render: (v) => (v == null ? '-' : Number(v).toFixed(3)) },
    {
      title: '评级',
      dataIndex: 'rating',
      key: 'rating',
      width: 80,
      render: (v) => <Tag color={RATING_COLOR[v] || 'default'}>{v || '-'}</Tag>,
    },
    {
      title: '操作',
      key: 'op',
      width: 80,
      render: (_, row) => <Button type="link" onClick={() => openSteadyDetail(row)}>曲线</Button>,
    },
  ]

  const renderTouchdownChart = (chartData) => {
    const series = chartData?.series || []
    const x = []
    series.forEach((s) => {
      ;(s.t_rel || []).forEach((v) => x.push(v))
    })
    const xSorted = Array.from(new Set(x)).sort((a, b) => a - b)
    const option = {
      tooltip: { trigger: 'axis' },
      legend: {
        top: 0,
        type: 'scroll',
        icon: 'circle',
        itemWidth: 10,
        itemHeight: 10,
        itemGap: 14,
        textStyle: {
          color: '#a1a1aa',
          fontSize: 12,
          fontWeight: 500,
        },
        inactiveColor: '#71717a',
        pageTextStyle: { color: '#a1a1aa' },
      },
      grid: { left: 50, right: 24, top: 36, bottom: 40 },
      xAxis: {
        type: 'value',
        name: 't(s)',
        nameTextStyle: { color: '#a1a1aa' },
        axisLabel: { color: '#71717a' },
      },
      yAxis: [
        { type: 'value', name: 'Vz(m/s)', nameTextStyle: { color: '#a1a1aa' }, axisLabel: { color: '#71717a' } },
        { type: 'value', name: 'Az(m/s²)', nameTextStyle: { color: '#a1a1aa' }, axisLabel: { color: '#71717a' } },
      ],
      series: series.flatMap((s) => ([
        {
          name: `${s.irs}-Vz`,
          type: 'line',
          yAxisIndex: 0,
          showSymbol: false,
          data: (s.t_rel || []).map((t, i) => [t, (s.vertical_velocity || [])[i]]),
        },
        {
          name: `${s.irs}-Az`,
          type: 'line',
          yAxisIndex: 1,
          showSymbol: false,
          data: (s.t_rel || []).map((t, i) => [t, (s.accel_z || [])[i]]),
        },
      ])),
      dataZoom: [{ type: 'inside' }, { type: 'slider' }],
    }
    return <ReactECharts option={option} style={{ height: 420 }} notMerge />
  }

  const renderSteadyChart = (chartData) => {
    const ts = chartData?.timestamps || []
    const t0 = ts.length ? ts[0] : 0
    const rel = ts.map((t) => t - t0)
    const option = {
      tooltip: { trigger: 'axis' },
      legend: {
        top: 0,
        type: 'scroll',
        icon: 'circle',
        itemWidth: 10,
        itemHeight: 10,
        itemGap: 14,
        textStyle: {
          color: '#a1a1aa',
          fontSize: 12,
          fontWeight: 500,
        },
        inactiveColor: '#71717a',
        pageTextStyle: { color: '#a1a1aa' },
      },
      grid: { left: 50, right: 24, top: 36, bottom: 40 },
      xAxis: {
        type: 'value',
        name: 't(s)',
        nameTextStyle: { color: '#a1a1aa' },
        axisLabel: { color: '#71717a' },
      },
      yAxis: {
        type: 'value',
        name: '误差',
        nameTextStyle: { color: '#a1a1aa' },
        axisLabel: { color: '#71717a' },
      },
      series: [
        {
          name: '高度偏差',
          type: 'line',
          showSymbol: false,
          data: rel.map((t, i) => [t, (chartData.alt_error || [])[i]]),
        },
        {
          name: '水平偏差',
          type: 'line',
          showSymbol: false,
          data: rel.map((t, i) => [t, (chartData.lat_error || [])[i]]),
        },
        {
          name: '速度偏差',
          type: 'line',
          showSymbol: false,
          data: rel.map((t, i) => [t, (chartData.spd_error || [])[i]]),
        },
      ],
      dataZoom: [{ type: 'inside' }, { type: 'slider' }],
    }
    return <ReactECharts option={option} style={{ height: 420 }} notMerge />
  }

  return (
    <div className="fade-in">
      <Card style={{ marginBottom: 24 }}>
        <Row gutter={16} align="middle">
          <Col>
            <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/auto-flight-analysis')}>
              返回历史列表
            </Button>
          </Col>
        </Row>
      </Card>

      <Card style={{ marginBottom: 24 }}>
        <Row gutter={24} align="middle">
          <Col xs={24} md={8}>
            <Statistic
              title="当前任务"
              value={task?.name || (taskId ? `#${taskId}` : '-')}
              valueStyle={{ fontSize: 14 }}
            />
            {task?.created_at && (
              <div style={{ marginTop: 8, color: '#a1a1aa', fontSize: 12 }}>
                创建时间 {dayjs(task.created_at).format('YYYY-MM-DD HH:mm:ss')}
              </div>
            )}
          </Col>
          <Col xs={24} md={4}>
            <Statistic
              title="状态"
              value={
                isProcessing ? '分析中…' :
                isCompleted ? '已完成' :
                task?.status === 'failed' ? '失败' : '加载中'
              }
              valueStyle={{
                fontSize: 14,
                color: isCompleted ? '#5fd068' :
                  task?.status === 'failed' ? '#f05050' :
                  isProcessing ? '#d4a843' : '#a1a1aa',
              }}
            />
          </Col>
          <Col xs={24} md={12}>
            <Space wrap>
              <Statistic title="触底次数" value={task?.touchdown_count ?? 0} />
              <Statistic title="稳态段数" value={task?.steady_count ?? 0} />
              <Button icon={<ReloadOutlined />} onClick={() => loadTaskDetail(taskId)} loading={loading}>
                刷新结果
              </Button>
              <Button icon={<DownloadOutlined />} loading={exporting} disabled={!isCompleted} onClick={handleExport}>
                导出 Excel
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      {task?.status === 'failed' && (
        <Alert
          type="error"
          message="自动飞行性能分析失败"
          description={task.error_message || '未知错误'}
          style={{ marginBottom: 24 }}
          showIcon
        />
      )}

      <Card title={<Space><ClockCircleOutlined />分析结果</Space>}>
        {loading && !task ? (
          <div style={{ textAlign: 'center', padding: 48 }}><Spin /></div>
        ) : !isCompleted && isProcessing ? (
          <div style={{ textAlign: 'center', padding: 48, color: '#a1a1aa' }}>
            <Spin style={{ marginRight: 12 }} />
            正在分析自动飞行数据，请稍候…
            {typeof task?.progress === 'number' && task.progress > 0 && (
              <Progress
                percent={task.progress}
                status="active"
                style={{ marginTop: 16, maxWidth: 400, marginLeft: 'auto', marginRight: 'auto' }}
              />
            )}
          </div>
        ) : task?.status === 'failed' ? (
          <Empty description="分析失败，请查看上方错误说明" />
        ) : (
          <Tabs
            className="auto-flight-task-tabs"
            items={[
              {
                key: 'touchdown',
                label: `触底分析 (${touchdowns.length})`,
                children: (
                  <Table
                    rowKey="id"
                    columns={touchdownColumns}
                    dataSource={touchdowns}
                    pagination={false}
                    scroll={{ x: 1520 }}
                  />
                ),
              },
              {
                key: 'steady',
                label: `稳态误差分析 (${steadyStates.length})`,
                children: (
                  <Table
                    rowKey="id"
                    columns={steadyColumns}
                    dataSource={steadyStates}
                    pagination={false}
                    scroll={{ x: 1080 }}
                  />
                ),
              },
            ]}
          />
        )}
      </Card>

      <Drawer
        title={detailType === 'touchdown' ? '触底曲线详情' : '稳态曲线详情'}
        open={detailVisible}
        onClose={() => setDetailVisible(false)}
        width={900}
      >
        {detailLoading ? (
          <Spin />
        ) : detailData ? (
          <>
            <div style={{ marginBottom: 12, color: '#a1a1aa' }}>{detailData.summary || '-'}</div>
            {detailType === 'touchdown'
              ? renderTouchdownChart(detailData.chart_data || {})
              : renderSteadyChart(detailData.chart_data || {})}
          </>
        ) : null}
      </Drawer>
    </div>
  )
}

export default AutoFlightAnalysisTaskPage
