import React, { useState, useEffect, useCallback } from 'react'
import {
  Card, Button, Space, message, Row, Col, Spin, Empty, Tag, Table,
  Statistic, Progress, Drawer, Timeline, Descriptions, Alert, Upload, Select,
} from 'antd'
import {
  UploadOutlined, ReloadOutlined, CheckCircleOutlined, CloseCircleOutlined,
  MinusCircleOutlined, FileSearchOutlined, ClockCircleOutlined, DownloadOutlined,
} from '@ant-design/icons'
import { standaloneEventApi } from '../services/api'
import dayjs from 'dayjs'

function StandaloneEventPage() {
  const [taskList, setTaskList] = useState([])
  const [listLoading, setListLoading] = useState(false)
  const [currentTaskId, setCurrentTaskId] = useState(null)
  const [analysisTask, setAnalysisTask] = useState(null)
  const [checkResults, setCheckResults] = useState([])
  const [timeline, setTimeline] = useState([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [drawerLoading, setDrawerLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [polling, setPolling] = useState(false)
  const [ruleTemplate, setRuleTemplate] = useState('default_v1')

  const [detailVisible, setDetailVisible] = useState(false)
  const [selectedCheck, setSelectedCheck] = useState(null)
  const [checkDetail, setCheckDetail] = useState(null)
  const [exporting, setExporting] = useState(false)

  const loadTaskList = useCallback(async () => {
    setListLoading(true)
    try {
      const res = await standaloneEventApi.listTasks(1, 50)
      setTaskList(res.data.items || [])
    } catch {
      message.error('加载任务列表失败')
    } finally {
      setListLoading(false)
    }
  }, [])

  const loadTaskDetail = useCallback(async (taskId) => {
    if (!taskId) return
    setDetailLoading(true)
    try {
      const taskRes = await standaloneEventApi.getTask(taskId)
      setAnalysisTask(taskRes.data)
      if (taskRes.data.status === 'completed') {
        const [resultsRes, timelineRes] = await Promise.all([
          standaloneEventApi.getCheckResults(taskId),
          standaloneEventApi.getTimeline(taskId),
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
    loadTaskList()
  }, [loadTaskList])

  useEffect(() => {
    if (currentTaskId) {
      loadTaskDetail(currentTaskId)
    } else {
      setAnalysisTask(null)
      setCheckResults([])
      setTimeline([])
    }
  }, [currentTaskId, loadTaskDetail])

  useEffect(() => {
    let timer = null
    if (polling && analysisTask?.status === 'processing' && currentTaskId) {
      timer = setInterval(async () => {
        try {
          const res = await standaloneEventApi.getTask(currentTaskId)
          setAnalysisTask(res.data)
          if (res.data.status !== 'processing') {
            setPolling(false)
            if (res.data.status === 'completed') {
              message.success('事件分析完成')
              loadTaskDetail(currentTaskId)
              loadTaskList()
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
  }, [polling, analysisTask?.status, currentTaskId, loadTaskDetail, loadTaskList])

  const handleUpload = async (file) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('rule_template', ruleTemplate)
    setUploading(true)
    try {
      const res = await standaloneEventApi.upload(formData)
      message.success(res.data.message || '已开始分析')
      setCurrentTaskId(res.data.task_id)
      setAnalysisTask({
        id: res.data.task_id,
        status: 'processing',
        rule_template: ruleTemplate,
        total_checks: 0,
        passed_checks: 0,
        failed_checks: 0,
      })
      setPolling(true)
      loadTaskList()
    } catch (err) {
      message.error(err.response?.data?.detail || '上传失败')
    } finally {
      setUploading(false)
    }
    return false
  }

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
    if (!currentTaskId || analysisTask?.status !== 'completed') return
    try {
      setExporting(true)
      const res = await standaloneEventApi.exportResults(currentTaskId)
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `event_analysis_standalone_${currentTaskId}.xlsx`)
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
      const res = await standaloneEventApi.getCheckDetail(currentTaskId, record.id)
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

  const historyColumns = [
    {
      title: '任务ID',
      dataIndex: 'id',
      key: 'id',
      width: 90,
      render: (id) => <span style={{ fontFamily: 'monospace' }}>{id}</span>,
    },
    { title: '文件', dataIndex: 'pcap_filename', key: 'pcap_filename', ellipsis: true },
    {
      title: '规则',
      dataIndex: 'rule_template',
      key: 'rule_template',
      width: 100,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (s) => {
        const color = s === 'completed' ? 'green' : s === 'failed' ? 'red' : s === 'processing' ? 'gold' : 'default'
        return <Tag color={color}>{s}</Tag>
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (t) => (t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    {
      title: '操作',
      key: 'op',
      width: 100,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => setCurrentTaskId(record.id)}>
          查看
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
      <Card title="上传 pcap / pcapng 进行事件分析" style={{ marginBottom: 24 }}>
        <Space wrap align="center">
          <span style={{ color: '#8b949e' }}>规则模板</span>
          <Select
            value={ruleTemplate}
            onChange={setRuleTemplate}
            style={{ width: 160 }}
            options={[{ value: 'default_v1', label: '航后检查单 (default_v1)' }]}
          />
          <Upload beforeUpload={handleUpload} showUploadList={false} accept=".pcap,.pcapng,.cap">
            <Button type="primary" icon={<UploadOutlined />} loading={uploading}>
              选择文件并分析
            </Button>
          </Upload>
          <Button icon={<ReloadOutlined />} onClick={loadTaskList} loading={listLoading}>
            刷新列表
          </Button>
        </Space>
        <div style={{ marginTop: 12, color: '#8b949e', fontSize: 12 }}>
          直接读取原始报文，无需先完成端口解析。分析在后台执行，完成后自动刷新结果。
        </div>
      </Card>

      <Card title="历史任务" style={{ marginBottom: 24 }} extra={<Tag>{taskList.length} 条</Tag>}>
        <Table
          rowKey="id"
          size="small"
          loading={listLoading}
          dataSource={taskList}
          columns={historyColumns}
          pagination={false}
          scroll={{ x: 800 }}
        />
      </Card>

      {currentTaskId && (
        <Card style={{ marginBottom: 24 }}>
          <Row gutter={24} align="middle">
            <Col xs={24} md={8}>
              <Statistic
                title="当前任务"
                value={analysisTask?.pcap_filename || `#${currentTaskId}`}
                valueStyle={{ fontSize: 14, fontFamily: 'JetBrains Mono, monospace' }}
              />
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
                  color: isCompleted ? '#3fb950' :
                    analysisTask?.status === 'failed' ? '#f85149' :
                    isProcessing ? '#d29922' : '#8b949e',
                }}
              />
            </Col>
            <Col xs={24} md={12}>
              <Space>
                <Statistic title="检查项" value={analysisTask?.total_checks ?? 0} prefix={<FileSearchOutlined />} />
                <Statistic title="通过" value={analysisTask?.passed_checks ?? 0} valueStyle={{ color: '#3fb950' }} />
                <Statistic title="失败" value={analysisTask?.failed_checks ?? 0} valueStyle={{ color: '#ef4444' }} />
                <Button icon={<ReloadOutlined />} onClick={() => loadTaskDetail(currentTaskId)} loading={detailLoading}>
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
                  <span style={{ color: '#8b949e' }}>通过率</span>
                  <Progress
                    percent={passRate}
                    status={passRate === 100 ? 'success' : passRate < 50 ? 'exception' : 'normal'}
                    style={{ flex: 1, maxWidth: 420 }}
                  />
                  <span style={{ color: '#8b949e' }}>{passedCount}/{checkResults.length}</span>
                </Space>
              </Col>
            </Row>
          )}
        </Card>
      )}

      {analysisTask?.status === 'failed' && (
        <Alert
          type="error"
          message="事件分析失败"
          description={analysisTask.error_message || '未知错误'}
          style={{ marginBottom: 24 }}
          showIcon
        />
      )}

      {currentTaskId && (
        <Card
          title={
            <Space>
              <FileSearchOutlined style={{ color: '#d29922' }} />
              <span>检查单结果</span>
              {isCompleted && <Tag color="green">{checkResults.length} 项</Tag>}
            </Space>
          }
        >
          {detailLoading && !checkResults.length ? (
            <div style={{ textAlign: 'center', padding: 48 }}>
              <Spin />
            </div>
          ) : !isCompleted && isProcessing ? (
            <div style={{ textAlign: 'center', padding: 48, color: '#8b949e' }}>
              <Spin style={{ marginRight: 12 }} />
              正在分析 pcap，请稍候…
            </div>
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
      )}

      {currentTaskId && isCompleted && timeline.length > 0 && (
        <Card title={<Space><ClockCircleOutlined />事件时间线</Space>} style={{ marginTop: 24 }}>
          <Timeline
            items={timeline.map((e) => ({
              color: e.event_type === 'response' ? 'green' : 'blue',
              children: (
                <div>
                  <div style={{ fontWeight: 600 }}>{e.time_str} · {e.event_name}</div>
                  <div style={{ color: '#8b949e', fontSize: 12 }}>{e.event_description}</div>
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
                <div style={{ marginTop: 8, fontSize: 12, color: '#8b949e' }}>
                  {checkDetail.check_result.period_analysis}
                </div>
              </Descriptions.Item>
              <Descriptions.Item label="内容检查">
                {renderResultTag(checkDetail.check_result.content_result)}
                <div style={{ marginTop: 8, fontSize: 12, color: '#8b949e' }}>
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
                      <div style={{ fontSize: 12, color: '#8b949e' }}>{e.event_description}</div>
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

export default StandaloneEventPage
