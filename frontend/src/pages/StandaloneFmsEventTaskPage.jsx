import React, { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Button, Space, message, Row, Col, Spin, Empty, Tag, Table,
  Statistic, Progress, Drawer, Timeline, Descriptions, Alert,
} from 'antd'
import {
  ArrowLeftOutlined, ReloadOutlined, CheckCircleOutlined, CloseCircleOutlined,
  MinusCircleOutlined, FileSearchOutlined, ClockCircleOutlined, DownloadOutlined,
} from '@ant-design/icons'
import { standaloneFmsEventApi } from '../services/api'
import dayjs from 'dayjs'

/**
 * 独立事件分析：单任务详情（从历史「查看」或上传完成后进入，避免结果叠在列表下方不易发现）
 */
function StandaloneFmsEventTaskPage() {
  const { analysisTaskId } = useParams()
  const navigate = useNavigate()

  const [analysisTask, setAnalysisTask] = useState(null)
  const [checkResults, setCheckResults] = useState([])
  const [timeline, setTimeline] = useState([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [drawerLoading, setDrawerLoading] = useState(false)
  const [polling, setPolling] = useState(false)
  const [detailVisible, setDetailVisible] = useState(false)
  const [selectedCheck, setSelectedCheck] = useState(null)
  const [checkDetail, setCheckDetail] = useState(null)
  const [exporting, setExporting] = useState(false)

  const taskId = analysisTaskId ? String(analysisTaskId) : null

  const loadTaskDetail = useCallback(async (id) => {
    if (!id) return
    setDetailLoading(true)
    try {
      const taskRes = await standaloneFmsEventApi.getTask(id)
      setAnalysisTask(taskRes.data)
      if (taskRes.data.status === 'completed') {
        const [resultsRes, timelineRes] = await Promise.all([
          standaloneFmsEventApi.getCheckResults(id),
          standaloneFmsEventApi.getTimeline(id),
        ])
        setCheckResults(resultsRes.data.items || [])
        setTimeline(timelineRes.data.items || [])
      } else {
        setCheckResults([])
        setTimeline([])
      }
    } catch {
      message.error('加载任务详情失败')
      setAnalysisTask(null)
    } finally {
      setDetailLoading(false)
    }
  }, [])

  useEffect(() => {
    window.scrollTo(0, 0)
  }, [taskId])

  useEffect(() => {
    setPolling(false)
  }, [taskId])

  useEffect(() => {
    if (!taskId) {
      navigate('/event-analysis', { replace: true })
      return
    }
    loadTaskDetail(taskId)
  }, [taskId, loadTaskDetail, navigate])

  useEffect(() => {
    let timer = null
    if (polling && analysisTask?.status === 'processing' && taskId) {
      timer = setInterval(async () => {
        try {
          const res = await standaloneFmsEventApi.getTask(taskId)
          setAnalysisTask(res.data)
          if (res.data.status !== 'processing') {
            setPolling(false)
            if (res.data.status === 'completed') {
              message.success('事件分析完成')
              loadTaskDetail(taskId)
            } else if (res.data.status === 'failed') {
              message.error(res.data.error_message || '事件分析失败')
            }
          }
        } catch {
          /* ignore */
        }
      }, 2000)
    }
    return () => {
      if (timer) clearInterval(timer)
    }
  }, [polling, analysisTask?.status, taskId, loadTaskDetail])

  useEffect(() => {
    if (analysisTask?.status === 'processing' && taskId) {
      setPolling(true)
    }
  }, [analysisTask?.status, taskId])

  const renderResultTag = (result) => {
    if (result === 'pass') {
      return <Tag color="success" icon={<CheckCircleOutlined />}>通过</Tag>
    }
    if (result === 'fail') {
      return <Tag color="error" icon={<CloseCircleOutlined />}>失败</Tag>
    }
    if (result === 'warning') {
      return <Tag color="warning">警告</Tag>
    }
    return <Tag color="default" icon={<MinusCircleOutlined />}>N/A</Tag>
  }

  const handleExport = async () => {
    if (!taskId || analysisTask?.status !== 'completed') return
    try {
      setExporting(true)
      const res = await standaloneFmsEventApi.exportResults(taskId)
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `event_analysis_standalone_${taskId}.xlsx`)
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

  const handleViewDetail = async (record) => {
    setSelectedCheck(record)
    setDetailVisible(true)
    setDrawerLoading(true)
    try {
      const res = await standaloneFmsEventApi.getCheckDetail(taskId, record.id)
      setCheckDetail(res.data)
    } catch {
      message.error('加载详情失败')
    } finally {
      setDrawerLoading(false)
    }
  }

  const columns = [
    { title: '序号', dataIndex: 'sequence', key: 'sequence', width: 70, align: 'center' },
    {
      title: '检查项',
      dataIndex: 'check_name',
      key: 'check_name',
      width: 260,
      render: (text, record) => (
        <Space direction="vertical" size={0}>
          <span style={{ fontWeight: 500 }}>{text}</span>
          {record.category && <Tag color="blue">{record.category}</Tag>}
        </Space>
      ),
    },
    { title: '事件时间', dataIndex: 'event_time', key: 'event_time', width: 100, render: (t) => t || '-' },
    { title: '事件描述', dataIndex: 'event_description', key: 'event_description', ellipsis: true },
    { title: '周期', dataIndex: 'period_result', key: 'period_result', width: 88, align: 'center', render: renderResultTag },
    { title: '内容', dataIndex: 'content_result', key: 'content_result', width: 88, align: 'center', render: renderResultTag },
    { title: '响应', dataIndex: 'response_result', key: 'response_result', width: 88, align: 'center', render: renderResultTag },
    { title: '综合', dataIndex: 'overall_result', key: 'overall_result', width: 96, align: 'center', render: renderResultTag },
    {
      title: '操作',
      key: 'action',
      width: 88,
      align: 'center',
      render: (_, record) => (
        <Button type="link" icon={<FileSearchOutlined />} onClick={() => handleViewDetail(record)}>
          详情
        </Button>
      ),
    },
  ]

  const isProcessing = analysisTask?.status === 'processing'
  const isCompleted = analysisTask?.status === 'completed'
  const passedCount = checkResults.filter((r) => r.overall_result === 'pass').length
  const passRate = checkResults.length > 0 ? Math.round((passedCount / checkResults.length) * 100) : 0

  return (
    <div className="fade-in">
      <Card style={{ marginBottom: 24 }}>
        <Row gutter={16} align="middle">
          <Col>
            <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/event-analysis')}>
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
              value={analysisTask?.pcap_filename || (taskId ? `#${taskId}` : '-')}
              valueStyle={{ fontSize: 14, fontFamily: 'JetBrains Mono, monospace' }}
            />
            {analysisTask?.created_at && (
              <div style={{ marginTop: 8, color: '#a1a1aa', fontSize: 12 }}>
                创建时间 {dayjs(analysisTask.created_at).format('YYYY-MM-DD HH:mm:ss')}
              </div>
            )}
            {analysisTask?.bundle_version_id ? (
              <div style={{ marginTop: 6 }}>
                <Tag
                  color="purple"
                  title={`本次分析基于 TSN 协议版本 #${analysisTask.bundle_version_id} 跑出`}
                  style={{ fontSize: 11 }}
                >
                  TSN {analysisTask.bundle_version_label
                    ? analysisTask.bundle_version_label
                    : `v${analysisTask.bundle_version_id}`}
                </Tag>
              </div>
            ) : null}
          </Col>
          <Col xs={24} md={4}>
            <Statistic
              title="状态"
              value={
                isProcessing ? '分析中…' :
                isCompleted ? '已完成' :
                analysisTask?.status === 'failed' ? '失败' : '加载中'
              }
              valueStyle={{
                fontSize: 14,
                color: isCompleted ? '#5fd068' :
                  analysisTask?.status === 'failed' ? '#f05050' :
                  isProcessing ? '#d4a843' : '#a1a1aa',
              }}
            />
          </Col>
          <Col xs={24} md={12}>
            <Space wrap>
              <Statistic title="检查项" value={analysisTask?.total_checks ?? 0} prefix={<FileSearchOutlined />} />
              <Statistic title="通过" value={analysisTask?.passed_checks ?? 0} valueStyle={{ color: '#5fd068' }} />
              <Statistic title="失败" value={analysisTask?.failed_checks ?? 0} valueStyle={{ color: '#f05050' }} />
              <Button icon={<ReloadOutlined />} onClick={() => loadTaskDetail(taskId)} loading={detailLoading}>
                刷新结果
              </Button>
              <Button
                icon={<DownloadOutlined />}
                loading={exporting}
                disabled={!isCompleted}
                onClick={handleExport}
              >
                导出 Excel
              </Button>
            </Space>
          </Col>
        </Row>
        {isCompleted && checkResults.length > 0 && (
          <Row style={{ marginTop: 16 }}>
            <Col span={24}>
              <Space align="center" style={{ width: '100%' }}>
                <span style={{ color: '#a1a1aa' }}>通过率</span>
                <Progress
                  percent={passRate}
                  status={passRate === 100 ? 'success' : passRate < 50 ? 'exception' : 'normal'}
                  style={{ flex: 1, maxWidth: 420 }}
                />
                <span style={{ color: '#a1a1aa' }}>{passedCount}/{checkResults.length}</span>
              </Space>
            </Col>
          </Row>
        )}
      </Card>

      {analysisTask?.status === 'failed' && (
        <Alert
          type="error"
          message="事件分析失败"
          description={analysisTask.error_message || '未知错误'}
          style={{ marginBottom: 24 }}
          showIcon
        />
      )}

      <Card
        title={
          <Space>
            <FileSearchOutlined style={{ color: '#d4a843' }} />
            <span>检查单结果</span>
            {isCompleted && <Tag color="green">{checkResults.length} 项</Tag>}
          </Space>
        }
      >
        {detailLoading && !analysisTask ? (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin />
          </div>
        ) : !isCompleted && isProcessing ? (
          <div style={{ textAlign: 'center', padding: 48, color: '#a1a1aa' }}>
            <Spin style={{ marginRight: 12 }} />
            正在分析 pcap，请稍候…
            {typeof analysisTask?.progress === 'number' && analysisTask.progress > 0 && (
              <Progress
                percent={analysisTask.progress}
                status="active"
                style={{ marginTop: 16, maxWidth: 400, marginLeft: 'auto', marginRight: 'auto' }}
              />
            )}
          </div>
        ) : analysisTask?.status === 'failed' ? (
          <Empty description="分析失败，请查看上方错误说明" />
        ) : checkResults.length === 0 && isCompleted ? (
          <Empty description="无检查结果" />
        ) : (
          <Table
            rowKey="id"
            columns={columns}
            dataSource={checkResults}
            scroll={{ x: 1200 }}
            pagination={{ pageSize: 30, showSizeChanger: true }}
          />
        )}
      </Card>

      {taskId && isCompleted && timeline.length > 0 && (
        <Card title={<Space><ClockCircleOutlined />事件时间线</Space>} style={{ marginTop: 24 }}>
          <Timeline
            items={timeline.map((e) => ({
              color: e.event_type === 'response' ? 'green' : 'blue',
              children: (
                <div>
                  <div style={{ fontWeight: 600 }}>{e.time_str} · {e.event_name}</div>
                  <div style={{ color: '#a1a1aa', fontSize: 12 }}>{e.event_description}</div>
                  <Tag>端口 {e.port}</Tag>
                  {e.device && <Tag color="purple">{e.device}</Tag>}
                </div>
              ),
            }))}
          />
        </Card>
      )}

      <Drawer
        title={selectedCheck?.check_name || '检查项详情'}
        open={detailVisible}
        onClose={() => setDetailVisible(false)}
        width={560}
      >
        {drawerLoading ? (
          <Spin />
        ) : checkDetail?.check_result ? (
          <>
            <Descriptions column={1} bordered size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="综合结论">
                {renderResultTag(checkDetail.check_result.overall_result)}
              </Descriptions.Item>
              <Descriptions.Item label="事件时间">{checkDetail.check_result.event_time || '-'}</Descriptions.Item>
              <Descriptions.Item label="周期检查">
                {renderResultTag(checkDetail.check_result.period_result)}
                <div style={{ marginTop: 8, fontSize: 12, color: '#a1a1aa' }}>
                  {checkDetail.check_result.period_analysis}
                </div>
              </Descriptions.Item>
              <Descriptions.Item label="内容检查">
                {renderResultTag(checkDetail.check_result.content_result)}
                <div style={{ marginTop: 8, fontSize: 12, color: '#a1a1aa' }}>
                  {checkDetail.check_result.content_analysis}
                </div>
              </Descriptions.Item>
            </Descriptions>
            {checkDetail.timeline_events?.length > 0 && (
              <Timeline
                items={checkDetail.timeline_events.map((e) => ({
                  children: (
                    <div>
                      <div>{e.time_str} {e.event_name}</div>
                      <div style={{ fontSize: 12, color: '#a1a1aa' }}>{e.event_description}</div>
                    </div>
                  ),
                }))}
              />
            )}
          </>
        ) : null}
      </Drawer>
    </div>
  )
}

export default StandaloneFmsEventTaskPage
