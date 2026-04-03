import React, { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Button, Space, message, Row, Col, Spin, Empty, Tag, Table,
  Statistic, Progress, Drawer, Timeline, Descriptions, Alert,
} from 'antd'
import {
  ArrowLeftOutlined, PlayCircleOutlined, ReloadOutlined,
  CheckCircleOutlined, CloseCircleOutlined, MinusCircleOutlined,
  ClockCircleOutlined, FileSearchOutlined, DownloadOutlined,
} from '@ant-design/icons'
import { parseApi, eventAnalysisApi } from '../services/api'
import dayjs from 'dayjs'

function EventAnalysisPage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  
  // 状态
  const [parseTask, setParseTask] = useState(null)
  const [analysisTask, setAnalysisTask] = useState(null)
  const [checkResults, setCheckResults] = useState([])
  const [timeline, setTimeline] = useState([])
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [polling, setPolling] = useState(false)
  
  // 详情抽屉
  const [detailVisible, setDetailVisible] = useState(false)
  const [selectedCheck, setSelectedCheck] = useState(null)
  const [checkDetail, setCheckDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  
  // 加载数据
  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      // 加载解析任务信息
      const parseRes = await parseApi.getTask(taskId)
      setParseTask(parseRes.data.task)
      
      // 尝试加载事件分析结果
      try {
        const analysisRes = await eventAnalysisApi.getTask(taskId)
        setAnalysisTask(analysisRes.data)
        
        if (analysisRes.data.status === 'completed') {
          const resultsRes = await eventAnalysisApi.getCheckResults(taskId)
          setCheckResults(resultsRes.data.items || [])
          
          const timelineRes = await eventAnalysisApi.getTimeline(taskId)
          setTimeline(timelineRes.data.items || [])
        }
      } catch (err) {
        // 分析任务可能还不存在
        setAnalysisTask(null)
      }
    } catch (err) {
      message.error('加载数据失败')
    } finally {
      setLoading(false)
    }
  }, [taskId])
  
  useEffect(() => {
    loadData()
  }, [loadData])
  
  // 轮询检查分析状态
  useEffect(() => {
    let timer = null
    
    if (polling && analysisTask?.status === 'processing') {
      timer = setInterval(async () => {
        try {
          const res = await eventAnalysisApi.getTask(taskId)
          setAnalysisTask(res.data)
          
          if (res.data.status !== 'processing') {
            setPolling(false)
            if (res.data.status === 'completed') {
              message.success('事件分析完成')
              loadData()
            } else if (res.data.status === 'failed') {
              message.error('事件分析失败: ' + (res.data.error_message || '未知错误'))
            }
          }
        } catch (err) {
          // 忽略轮询错误
        }
      }, 2000)
    }
    
    return () => {
      if (timer) clearInterval(timer)
    }
  }, [polling, analysisTask?.status, taskId, loadData])
  
  // 运行事件分析
  const handleRunAnalysis = async () => {
    setRunning(true)
    try {
      const res = await eventAnalysisApi.run(taskId)
      message.success(res.data.message || '事件分析任务已启动')
      
      // 更新状态并开始轮询
      setAnalysisTask({ ...analysisTask, status: 'processing' })
      setPolling(true)
    } catch (err) {
      message.error(err.response?.data?.detail || '启动事件分析失败')
    } finally {
      setRunning(false)
    }
  }
  
  const handleExport = async () => {
    if (analysisTask?.status !== 'completed') return
    try {
      setExporting(true)
      const res = await eventAnalysisApi.exportResults(taskId)
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `event_analysis_parse_${taskId}.xlsx`)
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

  // 查看检查项详情
  const handleViewDetail = async (record) => {
    setSelectedCheck(record)
    setDetailVisible(true)
    setDetailLoading(true)
    
    try {
      const res = await eventAnalysisApi.getCheckDetail(taskId, record.id)
      setCheckDetail(res.data)
    } catch (err) {
      message.error('加载详情失败')
    } finally {
      setDetailLoading(false)
    }
  }
  
  // 结果状态渲染
  const renderResultTag = (result) => {
    if (result === 'pass') {
      return <Tag color="success" icon={<CheckCircleOutlined />}>通过</Tag>
    } else if (result === 'fail') {
      return <Tag color="error" icon={<CloseCircleOutlined />}>失败</Tag>
    } else if (result === 'warning') {
      return <Tag color="warning">警告</Tag>
    } else {
      return <Tag color="default" icon={<MinusCircleOutlined />}>N/A</Tag>
    }
  }
  
  // 表格列
  const columns = [
    {
      title: '序号',
      dataIndex: 'sequence',
      key: 'sequence',
      width: 70,
      align: 'center',
    },
    {
      title: '检查项',
      dataIndex: 'check_name',
      key: 'check_name',
      width: 250,
      render: (text, record) => (
        <Space direction="vertical" size={0}>
          <span style={{ fontWeight: 500 }}>{text}</span>
          {record.category && (
            <Tag color="blue" style={{ marginTop: 4 }}>{record.category}</Tag>
          )}
        </Space>
      )
    },
    {
      title: '事件时间',
      dataIndex: 'event_time',
      key: 'event_time',
      width: 100,
      render: (text) => text || '-'
    },
    {
      title: '事件描述',
      dataIndex: 'event_description',
      key: 'event_description',
      ellipsis: true,
    },
    {
      title: '周期检查',
      dataIndex: 'period_result',
      key: 'period_result',
      width: 90,
      align: 'center',
      render: renderResultTag
    },
    {
      title: '内容检查',
      dataIndex: 'content_result',
      key: 'content_result',
      width: 90,
      align: 'center',
      render: renderResultTag
    },
    {
      title: '响应检查',
      dataIndex: 'response_result',
      key: 'response_result',
      width: 90,
      align: 'center',
      render: renderResultTag
    },
    {
      title: '综合结论',
      dataIndex: 'overall_result',
      key: 'overall_result',
      width: 100,
      align: 'center',
      render: renderResultTag
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      align: 'center',
      render: (_, record) => (
        <Button
          type="link"
          icon={<FileSearchOutlined />}
          onClick={() => handleViewDetail(record)}
        >
          详情
        </Button>
      )
    }
  ]
  
  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 100 }}>
        <Spin size="large" />
      </div>
    )
  }
  
  const isProcessing = analysisTask?.status === 'processing'
  const isCompleted = analysisTask?.status === 'completed'
  const passedCount = checkResults.filter(r => r.overall_result === 'pass').length
  const failedCount = checkResults.filter(r => r.overall_result === 'fail').length
  const passRate = checkResults.length > 0 
    ? Math.round((passedCount / checkResults.length) * 100) 
    : 0
  
  return (
    <div className="fade-in">
      {/* 顶部信息 */}
      <Card style={{ marginBottom: 24 }}>
        <Row gutter={24} align="middle">
          <Col span={1}>
            <Button
              icon={<ArrowLeftOutlined />}
              onClick={() => navigate(`/tasks/${taskId}`)}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="文件名"
              value={parseTask?.filename || '-'}
              valueStyle={{ fontSize: 14, fontFamily: 'JetBrains Mono' }}
            />
          </Col>
          <Col span={4}>
            <Statistic
              title="分析状态"
              value={
                isProcessing ? '分析中...' :
                isCompleted ? '已完成' :
                analysisTask?.status === 'failed' ? '失败' :
                '未分析'
              }
              valueStyle={{ 
                fontSize: 14,
                color: isCompleted ? '#3fb950' : 
                       analysisTask?.status === 'failed' ? '#f85149' :
                       isProcessing ? '#d29922' : '#8b949e'
              }}
            />
          </Col>
          <Col span={3}>
            <Statistic
              title="检查项"
              value={analysisTask?.total_checks || 0}
              prefix={<FileSearchOutlined />}
            />
          </Col>
          <Col span={3}>
            <Statistic
              title="通过"
              value={analysisTask?.passed_checks || 0}
              valueStyle={{ color: '#3fb950' }}
              prefix={<CheckCircleOutlined />}
            />
          </Col>
          <Col span={3}>
            <Statistic
              title="失败"
              value={analysisTask?.failed_checks || 0}
              valueStyle={{ color: '#ef4444' }}
              prefix={<CloseCircleOutlined />}
            />
          </Col>
          <Col span={4}>
            <Space>
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                onClick={handleRunAnalysis}
                loading={running || isProcessing}
                disabled={parseTask?.status !== 'completed'}
              >
                {isProcessing ? '分析中...' : isCompleted ? '重新分析' : '运行分析'}
              </Button>
              <Button
                icon={<ReloadOutlined />}
                onClick={loadData}
                loading={loading}
              >
                刷新
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
              <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                <span style={{ color: '#8b949e' }}>通过率:</span>
                <Progress 
                  percent={passRate} 
                  status={passRate === 100 ? 'success' : passRate < 50 ? 'exception' : 'normal'}
                  style={{ flex: 1, maxWidth: 400 }}
                />
                <span style={{ color: '#8b949e' }}>
                  {passedCount}/{checkResults.length} 项通过
                </span>
              </div>
            </Col>
          </Row>
        )}
      </Card>
      
      {/* 分析失败提示 */}
      {analysisTask?.status === 'failed' && (
        <Alert
          type="error"
          message="事件分析失败"
          description={analysisTask.error_message || '未知错误'}
          style={{ marginBottom: 24 }}
          showIcon
        />
      )}
      
      {/* 检查结果表格 */}
      <Card 
        title={
          <Space>
            <FileSearchOutlined style={{ color: '#d29922' }} />
            <span>检查单结果</span>
            {isCompleted && (
              <Tag color="green">{checkResults.length} 项</Tag>
            )}
          </Space>
        }
      >
        {!isCompleted ? (
          <Empty
            description={
              isProcessing ? '正在分析中，请稍候...' :
              analysisTask?.status === 'failed' ? '分析失败，请检查错误信息后重试' :
              '尚未运行事件分析'
            }
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            {!isProcessing && analysisTask?.status !== 'failed' && (
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                onClick={handleRunAnalysis}
                loading={running}
                disabled={parseTask?.status !== 'completed'}
              >
                运行事件分析
              </Button>
            )}
          </Empty>
        ) : (
          <Table
            columns={columns}
            dataSource={checkResults}
            rowKey="id"
            pagination={false}
            size="middle"
            scroll={{ y: 500 }}
            rowClassName={(record) => {
              if (record.overall_result === 'fail') return 'row-fail'
              if (record.overall_result === 'pass') return 'row-pass'
              return ''
            }}
          />
        )}
      </Card>
      
      {/* 事件时间线卡片 */}
      {isCompleted && timeline.length > 0 && (
        <Card 
          title={
            <Space>
              <ClockCircleOutlined style={{ color: '#58a6ff' }} />
              <span>事件时间线</span>
              <Tag color="blue">{timeline.length} 个事件</Tag>
            </Space>
          }
          style={{ marginTop: 24 }}
        >
          <Timeline
            mode="left"
            items={timeline.slice(0, 20).map((event, index) => ({
              color: event.event_type === 'first_send' ? 'green' : 'blue',
              label: event.time_str,
              children: (
                <div>
                  <div style={{ fontWeight: 500 }}>{event.event_name}</div>
                  <div style={{ color: '#8b949e', fontSize: 12 }}>
                    {event.device} - 端口 {event.port}
                  </div>
                  {event.event_description && (
                    <div style={{ color: '#8b949e', fontSize: 12, marginTop: 4 }}>
                      {event.event_description}
                    </div>
                  )}
                </div>
              )
            }))}
          />
          {timeline.length > 20 && (
            <div style={{ textAlign: 'center', color: '#8b949e', marginTop: 16 }}>
              ... 还有 {timeline.length - 20} 个事件
            </div>
          )}
        </Card>
      )}
      
      {/* 检查项详情抽屉 */}
      <Drawer
        title={
          <Space>
            <FileSearchOutlined />
            <span>检查项详情</span>
            {selectedCheck && renderResultTag(selectedCheck.overall_result)}
          </Space>
        }
        placement="right"
        width={700}
        open={detailVisible}
        onClose={() => {
          setDetailVisible(false)
          setSelectedCheck(null)
          setCheckDetail(null)
        }}
      >
        {detailLoading ? (
          <div style={{ textAlign: 'center', padding: 50 }}>
            <Spin />
          </div>
        ) : checkDetail ? (
          <div>
            {/* 基本信息 */}
            <Descriptions
              title="基本信息"
              column={1}
              bordered
              size="small"
              style={{ marginBottom: 24 }}
            >
              <Descriptions.Item label="检查项名称">
                {checkDetail.check_result.check_name}
              </Descriptions.Item>
              <Descriptions.Item label="分类">
                {checkDetail.check_result.category || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="事件时间">
                {checkDetail.check_result.event_time || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="事件描述">
                {checkDetail.check_result.event_description || '-'}
              </Descriptions.Item>
              {checkDetail.check_result.wireshark_filter && (
                <Descriptions.Item label="Wireshark过滤器">
                  <code style={{ 
                    background: '#161b22', 
                    padding: '4px 8px', 
                    borderRadius: 4,
                    fontSize: 12
                  }}>
                    {checkDetail.check_result.wireshark_filter}
                  </code>
                </Descriptions.Item>
              )}
            </Descriptions>
            
            {/* 周期检查 */}
            <Descriptions
              title={
                <Space>
                  <span>周期检查</span>
                  {renderResultTag(checkDetail.check_result.period_result)}
                </Space>
              }
              column={1}
              bordered
              size="small"
              style={{ marginBottom: 24 }}
            >
              <Descriptions.Item label="预期结果">
                {checkDetail.check_result.period_expected || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="实际结果">
                {checkDetail.check_result.period_actual || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="分析说明">
                {checkDetail.check_result.period_analysis || '-'}
              </Descriptions.Item>
            </Descriptions>
            
            {/* 内容检查 */}
            <Descriptions
              title={
                <Space>
                  <span>内容检查</span>
                  {renderResultTag(checkDetail.check_result.content_result)}
                </Space>
              }
              column={1}
              bordered
              size="small"
              style={{ marginBottom: 24 }}
            >
              <Descriptions.Item label="预期结果">
                {checkDetail.check_result.content_expected || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="实际结果">
                {checkDetail.check_result.content_actual || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="分析说明">
                {checkDetail.check_result.content_analysis || '-'}
              </Descriptions.Item>
            </Descriptions>
            
            {/* 响应检查 */}
            <Descriptions
              title={
                <Space>
                  <span>响应检查</span>
                  {renderResultTag(checkDetail.check_result.response_result)}
                </Space>
              }
              column={1}
              bordered
              size="small"
              style={{ marginBottom: 24 }}
            >
              <Descriptions.Item label="预期结果">
                {checkDetail.check_result.response_expected || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="实际结果">
                {checkDetail.check_result.response_actual || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="分析说明">
                {checkDetail.check_result.response_analysis || '-'}
              </Descriptions.Item>
            </Descriptions>
            
            {/* 相关事件时间线 */}
            {checkDetail.timeline_events && checkDetail.timeline_events.length > 0 && (
              <Card title="相关事件" size="small">
                <Timeline
                  items={checkDetail.timeline_events.map(event => ({
                    color: 'green',
                    children: (
                      <div>
                        <div style={{ fontWeight: 500 }}>{event.event_name}</div>
                        <div style={{ color: '#8b949e', fontSize: 12 }}>
                          {event.time_str} - {event.device}
                        </div>
                      </div>
                    )
                  }))}
                />
              </Card>
            )}
          </div>
        ) : null}
      </Drawer>
      
      <style>{`
        .row-fail {
          background-color: rgba(239, 68, 68, 0.1) !important;
        }
        .row-pass {
          background-color: rgba(16, 185, 129, 0.05) !important;
        }
      `}</style>
    </div>
  )
}

export default EventAnalysisPage
