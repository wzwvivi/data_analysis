import React, { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Button, Space, message, Row, Col, Spin, Empty, Tag, Table,
  Statistic, Progress, Drawer, Timeline, Descriptions, Alert,
} from 'antd'
import {
  ArrowLeftOutlined, ReloadOutlined, CheckCircleOutlined, CloseCircleOutlined,
  MinusCircleOutlined, FileSearchOutlined, ClockCircleOutlined, DownloadOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { fccEventAnalysisApi } from '../services/api'
import dayjs from 'dayjs'

function FccEventAnalysisTaskPage() {
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
      const taskRes = await fccEventAnalysisApi.getTask(id)
      setAnalysisTask(taskRes.data)
      if (taskRes.data.status === 'completed') {
        const [resultsRes, timelineRes] = await Promise.all([
          fccEventAnalysisApi.getCheckResults(id),
          fccEventAnalysisApi.getTimeline(id),
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

  useEffect(() => { window.scrollTo(0, 0) }, [taskId])
  useEffect(() => { setPolling(false) }, [taskId])

  useEffect(() => {
    if (!taskId) {
      navigate('/fcc-event-analysis', { replace: true })
      return
    }
    loadTaskDetail(taskId)
  }, [taskId, loadTaskDetail, navigate])

  useEffect(() => {
    let timer = null
    if (polling && analysisTask?.status === 'processing' && taskId) {
      timer = setInterval(async () => {
        try {
          const res = await fccEventAnalysisApi.getTask(taskId)
          setAnalysisTask(res.data)
          if (res.data.status !== 'processing') {
            setPolling(false)
            if (res.data.status === 'completed') {
              message.success('飞控事件分析完成')
              loadTaskDetail(taskId)
            } else if (res.data.status === 'failed') {
              message.error(res.data.error_message || '飞控事件分析失败')
            }
          }
        } catch { /* ignore */ }
      }, 2000)
    }
    return () => { if (timer) clearInterval(timer) }
  }, [polling, analysisTask?.status, taskId, loadTaskDetail])

  useEffect(() => {
    if (analysisTask?.status === 'processing' && taskId) {
      setPolling(true)
    }
  }, [analysisTask?.status, taskId])

  const renderResultTag = (result) => {
    if (result === 'detected') return <Tag color="orange" icon={<WarningOutlined />}>已发生</Tag>
    if (result === 'not_detected') return <Tag color="green" icon={<CheckCircleOutlined />}>未发生</Tag>
    return <Tag color="default" icon={<MinusCircleOutlined />}>N/A</Tag>
  }

  const handleExport = async () => {
    if (!taskId || analysisTask?.status !== 'completed') return
    try {
      setExporting(true)
      const res = await fccEventAnalysisApi.exportResults(taskId)
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `fcc_event_analysis_${taskId}.xlsx`)
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
      const res = await fccEventAnalysisApi.getCheckDetail(taskId, record.id)
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
      width: 220,
      render: (text, record) => (
        <Space direction="vertical" size={0}>
          <span style={{ fontWeight: 500 }}>{text}</span>
          {record.category && <Tag color="blue">{record.category}</Tag>}
        </Space>
      ),
    },
    { title: '事件时间', dataIndex: 'event_time', key: 'event_time', width: 120, render: (t) => t || '-' },
    { title: '事件描述', dataIndex: 'event_description', key: 'event_description', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'overall_result',
      key: 'overall_result',
      width: 96,
      align: 'center',
      render: renderResultTag,
    },
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
  const detectedCount = checkResults.filter((r) => r.overall_result === 'detected').length
  const notDetectedCount = checkResults.filter((r) => r.overall_result === 'not_detected').length

  return (
    <div className="fade-in">
      <Card style={{ marginBottom: 24 }}>
        <Row gutter={16} align="middle">
          <Col>
            <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/fcc-event-analysis')}>
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
              <Statistic title="已发生" value={detectedCount} valueStyle={{ color: '#d4a843' }} />
              <Statistic title="未发生" value={notDetectedCount} valueStyle={{ color: '#5fd068' }} />
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
      </Card>

      {analysisTask?.status === 'failed' && (
        <Alert
          type="error"
          message="飞控事件分析失败"
          description={analysisTask.error_message || '未知错误'}
          style={{ marginBottom: 24 }}
          showIcon
        />
      )}

      <Card
        title={
          <Space>
            <FileSearchOutlined style={{ color: '#d4a843' }} />
            <span>飞控事件检查结果</span>
            {isCompleted && <Tag color="green">{checkResults.length} 项</Tag>}
          </Space>
        }
      >
        {detailLoading && !analysisTask ? (
          <div style={{ textAlign: 'center', padding: 48 }}><Spin /></div>
        ) : !isCompleted && isProcessing ? (
          <div style={{ textAlign: 'center', padding: 48, color: '#a1a1aa' }}>
            <Spin style={{ marginRight: 12 }} />
            正在分析飞控数据，请稍候…
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
            scroll={{ x: 900 }}
            pagination={false}
          />
        )}
      </Card>

      {taskId && isCompleted && timeline.length > 0 && (
        <Card title={<Space><ClockCircleOutlined />飞控事件时间线</Space>} style={{ marginTop: 24 }}>
          <Timeline
            items={timeline.map((e) => ({
              color: e.event_type === 'causal_chain' ? 'orange' : e.event_type === 'state_change' ? 'blue' : 'gray',
              children: (
                <div>
                  <div style={{ fontWeight: 600 }}>{e.time_str} · {e.event_name}</div>
                  <div style={{ color: '#a1a1aa', fontSize: 12 }}>{e.event_description}</div>
                  {e.port > 0 && <Tag>端口 {e.port}</Tag>}
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
              <Descriptions.Item label="检测状态">
                {renderResultTag(checkDetail.check_result.overall_result)}
              </Descriptions.Item>
              <Descriptions.Item label="事件时间">{checkDetail.check_result.event_time || '-'}</Descriptions.Item>
              <Descriptions.Item label="事件描述">{checkDetail.check_result.event_description || '-'}</Descriptions.Item>
              {checkDetail.check_result.content_analysis && (
                <Descriptions.Item label="详细信息">
                  <div style={{ fontSize: 12, color: '#a1a1aa' }}>
                    {checkDetail.check_result.content_analysis}
                  </div>
                </Descriptions.Item>
              )}
            </Descriptions>
            {checkDetail.timeline_events?.length > 0 && (
              <>
                <h4 style={{ marginBottom: 12 }}>关联时间线</h4>
                <Timeline
                  items={checkDetail.timeline_events.map((e) => ({
                    color: e.event_type === 'causal_chain' ? 'orange' : 'blue',
                    children: (
                      <div>
                        <div>{e.time_str} {e.event_name}</div>
                        <div style={{ fontSize: 12, color: '#a1a1aa' }}>{e.event_description}</div>
                      </div>
                    ),
                  }))}
                />
              </>
            )}
          </>
        ) : null}
      </Drawer>
    </div>
  )
}

export default FccEventAnalysisTaskPage
