import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Row, Col, Card, Statistic, Table, Tag, Progress, Button, Space, Typography, Spin, Empty, Tooltip, message,
} from 'antd'
import {
  DashboardOutlined, ReloadOutlined, DatabaseOutlined, FileSearchOutlined,
  SwapOutlined, CloudUploadOutlined, TeamOutlined, ApartmentOutlined,
  CheckCircleOutlined, ClockCircleOutlined, LoadingOutlined, CloseCircleOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { dashboardApi } from '../services/api'
import { useAuth } from '../context/AuthContext'

const { Title, Text } = Typography

const ACCENT = {
  purple: '#8b5cf6',
  green: '#5fd068',
  orange: '#d4a843',
  red: '#f05050',
  blue: '#60a5fa',
}

function MetricCard({ title, value, suffix, icon, hint, color = ACCENT.purple }) {
  return (
    <Card bordered={false} style={{ height: '100%' }}>
      <Space align="start" style={{ width: '100%', justifyContent: 'space-between' }}>
        <div>
          <Text type="secondary" style={{ fontSize: 12, letterSpacing: 0.2 }}>{title}</Text>
          <div style={{ marginTop: 6 }}>
            <Statistic
              value={value}
              suffix={suffix}
              valueStyle={{ color: '#e4e4e7', fontSize: 28, fontWeight: 600, lineHeight: 1.1 }}
            />
          </div>
          {hint && (
            <div style={{ marginTop: 8, color: '#9393a1', fontSize: 12 }}>{hint}</div>
          )}
        </div>
        <div style={{
          width: 40, height: 40, borderRadius: 12,
          background: `linear-gradient(135deg, ${color}33 0%, ${color}11 100%)`,
          border: `1px solid ${color}44`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color,
          fontSize: 18,
        }}>
          {icon}
        </div>
      </Space>
    </Card>
  )
}

function StatusBadges({ breakdown }) {
  if (!breakdown) return null
  return (
    <Space size={6} wrap>
      <Tag color="success" icon={<CheckCircleOutlined />}>完成 {breakdown.completed || 0}</Tag>
      <Tag color="processing" icon={<LoadingOutlined />}>进行中 {breakdown.processing || 0}</Tag>
      <Tag color="default" icon={<ClockCircleOutlined />}>等待 {breakdown.pending || 0}</Tag>
      <Tag color="error" icon={<CloseCircleOutlined />}>失败 {breakdown.failed || 0}</Tag>
    </Space>
  )
}

function DashboardPage() {
  const navigate = useNavigate()
  const { user, isAdmin } = useAuth()
  const [overview, setOverview] = useState(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const r = await dashboardApi.getOverview()
      setOverview(r.data)
    } catch (e) {
      if (!silent) message.error(e?.response?.data?.detail || '加载平台总览失败')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(false)
    const t = setInterval(() => load(true), 30000)
    return () => clearInterval(t)
  }, [load])

  const trendOption = useMemo(() => {
    const series = overview?.parse_tasks_trend_7d || []
    return {
      backgroundColor: 'transparent',
      grid: { left: 40, right: 18, top: 24, bottom: 32 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'line' } },
      xAxis: {
        type: 'category',
        data: series.map(d => dayjs(d.date).format('MM-DD')),
        axisLine: { lineStyle: { color: '#3f3f46' } },
        axisLabel: { color: '#9393a1', fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
        axisLine: { show: false },
        splitLine: { lineStyle: { color: 'rgba(63, 63, 70, 0.35)' } },
        axisLabel: { color: '#9393a1', fontSize: 11 },
      },
      series: [{
        name: '解析任务',
        type: 'bar',
        barMaxWidth: 22,
        data: series.map(d => d.count),
        itemStyle: {
          borderRadius: [6, 6, 0, 0],
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(139, 92, 246, 0.95)' },
              { offset: 1, color: 'rgba(139, 92, 246, 0.25)' },
            ],
          },
        },
      }],
    }
  }, [overview])

  const eventPieOption = useMemo(() => {
    const ea = overview?.event_analysis
    const fcc = overview?.fcc_event_analysis
    if (!ea && !fcc) return null
    const passed = (ea?.passed_checks || 0) + (fcc?.passed_checks || 0)
    const failed = (ea?.failed_checks || 0) + (fcc?.failed_checks || 0)
    const totalChecks = (ea?.total_checks || 0) + (fcc?.total_checks || 0)
    const other = Math.max(totalChecks - passed - failed, 0)
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, textStyle: { color: '#9393a1', fontSize: 12 } },
      series: [{
        name: '检查结果',
        type: 'pie',
        radius: ['55%', '78%'],
        center: ['50%', '44%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: 'rgba(18, 18, 23, 0.94)', borderWidth: 2 },
        label: { show: false },
        labelLine: { show: false },
        data: [
          { value: passed, name: '通过', itemStyle: { color: ACCENT.green } },
          { value: failed, name: '失败', itemStyle: { color: ACCENT.red } },
          { value: other, name: '其他', itemStyle: { color: '#52525b' } },
        ],
      }],
    }
  }, [overview])

  const recentColumns = [
    {
      title: '文件名', dataIndex: 'filename', key: 'filename',
      render: (v) => <Tooltip title={v}><span style={{ maxWidth: 240, display: 'inline-block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', verticalAlign: 'middle' }}>{v}</span></Tooltip>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 160,
      render: (_, rec) => {
        const map = {
          pending: { color: 'default', icon: <ClockCircleOutlined />, text: '等待中' },
          processing: { color: 'processing', icon: <LoadingOutlined />, text: '解析中' },
          completed: { color: 'success', icon: <CheckCircleOutlined />, text: '已完成' },
          failed: { color: 'error', icon: <CloseCircleOutlined />, text: '失败' },
        }
        const cfg = map[rec.status] || map.pending
        const pct = typeof rec.progress === 'number' ? rec.progress : 0
        return (
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            <Tag color={cfg.color} icon={cfg.icon}>{cfg.text}</Tag>
            {(rec.status === 'processing' || rec.status === 'pending') && (
              <Progress percent={pct} size="small" showInfo={false} strokeColor={ACCENT.purple} />
            )}
          </Space>
        )
      },
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (v) => v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-',
    },
    {
      title: '操作', key: 'op', width: 120,
      render: (_, rec) => (
        <Button type="link" size="small" onClick={() => navigate(`/tasks/${rec.id}`)}>查看</Button>
      ),
    },
  ]

  const parseBreakdown = overview?.parse_tasks
  const users = overview?.users
  const sharedTsn = overview?.shared_tsn
  const eventAnalysis = overview?.event_analysis
  const fccEventAnalysis = overview?.fcc_event_analysis
  const autoFlight = overview?.auto_flight_analysis
  const compareSummary = overview?.compare_tasks

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <Title level={3} style={{ margin: 0, color: '#e4e4e7', fontWeight: 600, letterSpacing: '-0.01em' }}>
            <DashboardOutlined style={{ marginRight: 10, color: ACCENT.purple }} />
            平台仪表盘
          </Title>
          <Text type="secondary" style={{ fontSize: 13 }}>
            {user ? `欢迎回来，${user.username}` : '欢迎使用 TSN 日志分析平台'}
            {overview?.generated_at && ` · 数据刷新于 ${dayjs(overview.generated_at).format('HH:mm:ss')}`}
          </Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => load(false)} loading={loading}>刷新</Button>
        </Space>
      </div>

      <Spin spinning={loading && !overview}>
        {!overview && !loading ? (
          <Card><Empty description="暂无数据" /></Card>
        ) : (
          <>
            <Row gutter={[16, 16]}>
              <Col xs={24} sm={12} md={8} lg={6}>
                <MetricCard
                  title="解析任务总数"
                  value={parseBreakdown?.total ?? 0}
                  icon={<DatabaseOutlined />}
                  color={ACCENT.purple}
                  hint={<StatusBadges breakdown={parseBreakdown} />}
                />
              </Col>
              <Col xs={24} sm={12} md={8} lg={6}>
                <MetricCard
                  title="事件分析 (飞管/飞控)"
                  value={(eventAnalysis?.total || 0) + (fccEventAnalysis?.total || 0)}
                  icon={<FileSearchOutlined />}
                  color={ACCENT.blue}
                  hint={
                    <Space size={6} wrap>
                      <Tag color="geekblue">飞管 {eventAnalysis?.total || 0}</Tag>
                      <Tag color="cyan">飞控 {fccEventAnalysis?.total || 0}</Tag>
                    </Space>
                  }
                />
              </Col>
              <Col xs={24} sm={12} md={8} lg={6}>
                <MetricCard
                  title="自动飞行性能分析"
                  value={autoFlight?.total ?? 0}
                  icon={<ThunderboltOutlined />}
                  color={ACCENT.orange}
                  hint={
                    <Space size={6} wrap>
                      <Tag color="orange">着陆事件 {autoFlight?.touchdown_count || 0}</Tag>
                      <Tag color="gold">稳态段 {autoFlight?.steady_count || 0}</Tag>
                    </Space>
                  }
                />
              </Col>
              <Col xs={24} sm={12} md={8} lg={6}>
                <MetricCard
                  title="双交换机比对"
                  value={compareSummary?.total ?? 0}
                  icon={<SwapOutlined />}
                  color={ACCENT.green}
                  hint={
                    <Space size={6} wrap>
                      <Tag color="success">通过 {compareSummary?.pass_count || 0}</Tag>
                      <Tag color="warning">告警 {compareSummary?.warning_count || 0}</Tag>
                      <Tag color="error">失败 {compareSummary?.fail_count || 0}</Tag>
                    </Space>
                  }
                />
              </Col>
              <Col xs={24} sm={12} md={8} lg={6}>
                <MetricCard
                  title="平台共享 TSN"
                  value={sharedTsn?.total ?? 0}
                  icon={<CloudUploadOutlined />}
                  color={ACCENT.purple}
                  hint={sharedTsn?.latest_at ? `最新上传 ${dayjs(sharedTsn.latest_at).format('YYYY-MM-DD HH:mm')}` : '暂无上传'}
                />
              </Col>
              <Col xs={24} sm={12} md={8} lg={6}>
                <MetricCard
                  title="解析结果条目"
                  value={overview?.parse_results_total ?? 0}
                  suffix="条"
                  icon={<DatabaseOutlined />}
                  color={ACCENT.blue}
                  hint="累计已解析的端口记录数"
                />
              </Col>
              <Col xs={24} sm={12} md={8} lg={6}>
                <MetricCard
                  title="协议设备总数"
                  value={overview?.protocol_devices_total ?? 0}
                  icon={<ApartmentOutlined />}
                  color={ACCENT.green}
                  hint="协议库中登记的设备数"
                />
              </Col>
              {isAdmin && (
                <Col xs={24} sm={12} md={8} lg={6}>
                  <MetricCard
                    title="平台用户数"
                    value={users?.total ?? 0}
                    icon={<TeamOutlined />}
                    color={ACCENT.orange}
                    hint={`其中管理员 ${users?.admin_total || 0} 名`}
                  />
                </Col>
              )}
            </Row>

            <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
              <Col xs={24} lg={14}>
                <Card
                  title={<span style={{ color: '#e4e4e7' }}>近 7 天解析任务趋势</span>}
                  bordered={false}
                  extra={<Text type="secondary" style={{ fontSize: 12 }}>按创建时间聚合</Text>}
                >
                  <ReactECharts option={trendOption} style={{ height: 260 }} notMerge lazyUpdate theme="dark" />
                </Card>
              </Col>
              <Col xs={24} lg={10}>
                <Card
                  title={<span style={{ color: '#e4e4e7' }}>事件分析检查结果构成</span>}
                  bordered={false}
                  extra={
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      总检查 {(eventAnalysis?.total_checks || 0) + (fccEventAnalysis?.total_checks || 0)} 项
                    </Text>
                  }
                >
                  {eventPieOption ? (
                    <ReactECharts option={eventPieOption} style={{ height: 260 }} notMerge lazyUpdate theme="dark" />
                  ) : (
                    <Empty description="暂无事件分析数据" />
                  )}
                </Card>
              </Col>
            </Row>

            <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
              <Col xs={24}>
                <Card
                  title={<span style={{ color: '#e4e4e7' }}>最近解析任务</span>}
                  bordered={false}
                  extra={<Button type="link" size="small" onClick={() => navigate('/tasks')}>查看全部 →</Button>}
                >
                  <Table
                    size="middle"
                    rowKey="id"
                    columns={recentColumns}
                    dataSource={overview?.recent_parse_tasks || []}
                    pagination={false}
                    locale={{ emptyText: '暂无解析任务' }}
                  />
                </Card>
              </Col>
            </Row>
          </>
        )}
      </Spin>
    </div>
  )
}

export default DashboardPage
