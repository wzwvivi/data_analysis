import React, { useState, useEffect, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card,
  Upload,
  Button,
  Select,
  Form,
  message,
  Progress,
  Collapse,
  Table,
  Tag,
  Space,
  Statistic,
  Row,
  Col,
  Alert,
  Spin,
  Slider,
  Tabs,
  Radio,
} from 'antd'
import {
  UploadOutlined,
  DownloadOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import { compareApi, protocolApi, sharedTsnApi } from '../services/api'
import { isParseCompatibleSharedItem } from '../utils/sharedPlatform'

const { Panel } = Collapse

function ComparePage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  
  // 上传状态
  const [form] = Form.useForm()
  const [file1, setFile1] = useState(null)
  const [file2, setFile2] = useState(null)
  const [sharedList, setSharedList] = useState([])
  const [mode1, setMode1] = useState('platform')
  const [mode2, setMode2] = useState('platform')
  const [sharedId1, setSharedId1] = useState(null)
  const [sharedId2, setSharedId2] = useState(null)
  const [versions, setVersions] = useState([])
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  
  // 任务状态
  const [task, setTask] = useState(null)
  const [portResults, setPortResults] = useState([])
  const [gapRecords, setGapRecords] = useState([])
  const [timingResults, setTimingResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [polling, setPolling] = useState(false)
  const [exporting, setExporting] = useState(false)

  // 加载网络配置版本列表
  useEffect(() => {
    loadVersions()
  }, [])

  useEffect(() => {
    sharedTsnApi.list().then((r) => setSharedList(r.data || [])).catch(() => setSharedList([]))
  }, [])

  const parseSharedList = useMemo(
    () => sharedList.filter(isParseCompatibleSharedItem),
    [sharedList],
  )

  // 如果有taskId，加载任务详情并轮询直到完成
  useEffect(() => {
    if (taskId) {
      loadTask()
    }
  }, [taskId])

  useEffect(() => {
    if (!polling) return
    const interval = setInterval(() => {
      loadTask()
    }, 2000)
    return () => clearInterval(interval)
  }, [polling])

  const loadVersions = async () => {
    try {
      const res = await protocolApi.listVersions()
      setVersions(res.data.items || [])
    } catch (error) {
      message.error('加载网络配置版本失败')
    }
  }

  const loadTask = async () => {
    try {
      setLoading(true)
      const res = await compareApi.getTask(taskId)
      setTask(res.data)
      
      if (res.data.status === 'completed') {
        setPolling(false)
        const [portsRes, gapsRes] = await Promise.all([
          compareApi.getPortResults(taskId),
          compareApi.getGaps(taskId),
        ])
        setPortResults(portsRes.data.items || [])
        setGapRecords(gapsRes.data.items || [])
        try {
          const timingRes = await compareApi.getTimingResults(taskId)
          setTimingResults(timingRes.data.items || [])
        } catch {
          setTimingResults([])
        }
      } else if (res.data.status === 'failed') {
        setPolling(false)
      } else if (res.data.status === 'processing' || res.data.status === 'pending') {
        setPolling(true)
      }
    } catch (error) {
      if (!polling) {
        message.error('加载任务失败')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleUpload = async (values) => {
    const ok1 = (mode1 === 'local' && file1) || (mode1 === 'platform' && sharedId1)
    const ok2 = (mode2 === 'local' && file2) || (mode2 === 'platform' && sharedId2)
    if (!ok1 || !ok2) {
      message.error('请为交换机1、交换机2 各选择一种数据来源（本地上传或平台数据）')
      return
    }

    const formData = new FormData()
    formData.append('protocol_version_id', values.protocol_version_id)
    formData.append('jitter_threshold_pct', values.jitter_threshold_pct || 10.0)
    if (mode1 === 'local') {
      formData.append('file_1', file1)
    } else {
      formData.append('shared_id_1', String(sharedId1))
    }
    if (mode2 === 'local') {
      formData.append('file_2', file2)
    } else {
      formData.append('shared_id_2', String(sharedId2))
    }

    try {
      setUploading(true)
      setUploadProgress(0)
      const hasLocalFile = mode1 === 'local' || mode2 === 'local'
      const res = await compareApi.upload(formData, hasLocalFile ? (e) => {
        if (e.total) setUploadProgress(Math.round((e.loaded * 100) / e.total))
      } : undefined)
      message.success('任务已创建，开始检查')
      navigate(`/compare/${res.data.task_id}`)
    } catch (error) {
      message.error(error.response?.data?.detail || '提交失败')
    } finally {
      setUploading(false)
      setUploadProgress(0)
    }
  }

  const handleExport = async () => {
    try {
      setExporting(true)
      const res = await compareApi.exportReport(taskId)
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `compare_report_task${taskId}.xlsx`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
      message.success('导出成功')
    } catch (error) {
      message.error('导出失败')
    } finally {
      setExporting(false)
    }
  }

  const getResultIcon = (result) => {
    if (result === 'pass') return <CheckCircleOutlined style={{ color: '#5fd068' }} />
    if (result === 'fail') return <CloseCircleOutlined style={{ color: '#f05050' }} />
    if (result === 'warning') return <WarningOutlined style={{ color: '#d4a843' }} />
    return null
  }

  const getResultTag = (result) => {
    if (result === 'pass') return <Tag color="success">通过</Tag>
    if (result === 'fail') return <Tag color="error">失败</Tag>
    if (result === 'warning') return <Tag color="warning">警告</Tag>
    return <Tag>未知</Tag>
  }

  const formatTimestamp = (ts) => {
    if (!ts) return '-'
    const date = new Date(ts * 1000)
    return date.toLocaleString('zh-CN', { 
      hour12: false,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      fractionalSecondDigits: 3
    })
  }

  // 端口结果表格列
  const portColumns = [
    {
      title: '端口号',
      dataIndex: 'port_number',
      key: 'port_number',
      width: 100,
      sorter: (a, b) => a.port_number - b.port_number,
    },
    {
      title: '源设备',
      dataIndex: 'source_device',
      key: 'source_device',
      width: 150,
    },
    {
      title: '消息名称',
      dataIndex: 'message_name',
      key: 'message_name',
      width: 200,
    },
    {
      title: '周期(ms)',
      dataIndex: 'period_ms',
      key: 'period_ms',
      width: 100,
      render: (val) => val ? val.toFixed(1) : '-',
    },
    {
      title: '交换机1',
      key: 'switch1',
      width: 120,
      render: (_, record) => (
        <Space direction="vertical" size="small">
          <div>{record.in_switch1 ? `${record.switch1_count} 包` : '该端口未出现'}</div>
          {record.gap_count_switch1 > 0 && (
            <Tag color="warning">{record.gap_count_switch1} 段丢包</Tag>
          )}
        </Space>
      ),
    },
    {
      title: '交换机2',
      key: 'switch2',
      width: 120,
      render: (_, record) => (
        <Space direction="vertical" size="small">
          <div>{record.in_switch2 ? `${record.switch2_count} 包` : '该端口未出现'}</div>
          {record.gap_count_switch2 > 0 && (
            <Tag color="warning">{record.gap_count_switch2} 段丢包</Tag>
          )}
        </Space>
      ),
    },
    {
      title: '包数差',
      dataIndex: 'count_diff',
      key: 'count_diff',
      width: 100,
      render: (val) => val > 0 ? <Tag color="orange">{val}</Tag> : '-',
    },
    {
      title: '结果',
      dataIndex: 'result',
      key: 'result',
      width: 100,
      render: (val) => getResultTag(val),
    },
    {
      title: '说明',
      dataIndex: 'detail',
      key: 'detail',
      width: 250,
    },
  ]

  // 周期统计表格列
  const timingColumns = [
    {
      title: '端口号',
      dataIndex: 'port_number',
      key: 'port_number',
      width: 100,
      sorter: (a, b) => a.port_number - b.port_number,
    },
    {
      title: '源设备',
      dataIndex: 'source_device',
      key: 'source_device',
      width: 150,
    },
    {
      title: '消息名称',
      dataIndex: 'message_name',
      key: 'message_name',
      width: 180,
    },
    {
      title: '预期周期(ms)',
      dataIndex: 'expected_period_ms',
      key: 'expected_period_ms',
      width: 110,
      render: (val) => val?.toFixed(1) || '-',
    },
    {
      title: '实际均值(ms)',
      dataIndex: 'actual_mean_interval_ms',
      key: 'actual_mean_interval_ms',
      width: 110,
      render: (val) => val?.toFixed(2) || '-',
    },
    {
      title: '标准差(ms)',
      dataIndex: 'actual_std_interval_ms',
      key: 'actual_std_interval_ms',
      width: 100,
      render: (val) => val?.toFixed(2) || '-',
    },
    {
      title: '抖动%',
      dataIndex: 'jitter_pct',
      key: 'jitter_pct',
      width: 90,
      sorter: (a, b) => (a.jitter_pct || 0) - (b.jitter_pct || 0),
      render: (val) => val ? `${val.toFixed(1)}%` : '-',
    },
    {
      title: '达标率%',
      dataIndex: 'compliance_rate_pct',
      key: 'compliance_rate_pct',
      width: 100,
      sorter: (a, b) => (a.compliance_rate_pct || 0) - (b.compliance_rate_pct || 0),
      render: (val) => val ? `${val.toFixed(1)}%` : '-',
    },
    {
      title: '最小间隔(ms)',
      dataIndex: 'actual_min_interval_ms',
      key: 'actual_min_interval_ms',
      width: 110,
      render: (val) => val?.toFixed(2) || '-',
    },
    {
      title: '最大间隔(ms)',
      dataIndex: 'actual_max_interval_ms',
      key: 'actual_max_interval_ms',
      width: 110,
      render: (val) => val?.toFixed(2) || '-',
    },
    {
      title: '结果',
      dataIndex: 'result',
      key: 'result',
      width: 90,
      render: (val) => getResultTag(val),
    },
    {
      title: '说明',
      dataIndex: 'detail',
      key: 'detail',
      width: 180,
    },
  ]

  // 丢包记录表格列
  const gapColumns = [
    {
      title: '端口号',
      dataIndex: 'port_number',
      key: 'port_number',
      width: 100,
      sorter: (a, b) => a.port_number - b.port_number,
    },
    {
      title: '交换机',
      dataIndex: 'switch_index',
      key: 'switch_index',
      width: 100,
      render: (val) => `交换机${val}`,
    },
    {
      title: '丢包起始时间',
      dataIndex: 'gap_start_ts',
      key: 'gap_start_ts',
      width: 200,
      render: formatTimestamp,
    },
    {
      title: '丢包结束时间',
      dataIndex: 'gap_end_ts',
      key: 'gap_end_ts',
      width: 200,
      render: formatTimestamp,
    },
    {
      title: '间隔时长(ms)',
      dataIndex: 'gap_duration_ms',
      key: 'gap_duration_ms',
      width: 120,
      sorter: (a, b) => a.gap_duration_ms - b.gap_duration_ms,
      render: (val) => val.toFixed(2),
    },
    {
      title: '预期周期(ms)',
      dataIndex: 'expected_period_ms',
      key: 'expected_period_ms',
      width: 120,
      render: (val) => val.toFixed(1),
    },
    {
      title: '预估缺失包数',
      dataIndex: 'estimated_missing_packets',
      key: 'estimated_missing_packets',
      width: 120,
      render: (val) => val || 0,
    },
  ]

  // 上传区
  if (!taskId) {
    return (
      <Card title="TSN数据异常检查" style={{ maxWidth: 800, margin: '0 auto' }}>
        <Alert
          message="功能说明"
          description="上传两个交换机的抓包文件，系统将执行四项检查：1) 记录时间同步性 2) 端口覆盖完整性 3) 周期端口数据连续性（丢包检测） 4) 端口周期正确性与抖动分析"
          type="info"
          showIcon
          style={{ marginBottom: 24 }}
        />
        
        <Form form={form} layout="vertical" onFinish={handleUpload}>
          <Form.Item label="交换机1 数据来源" required>
            <Radio.Group
              value={mode1}
              onChange={(e) => {
                setMode1(e.target.value)
                setFile1(null)
                setSharedId1(null)
              }}
            >
              <Radio.Button value="platform">平台共享</Radio.Button>
              <Radio.Button value="local">本地上传</Radio.Button>
            </Radio.Group>
          </Form.Item>
          {mode1 === 'platform' ? (
            <Form.Item label="交换机1 平台数据">
              <Select
                placeholder="选择平台共享抓包"
                style={{ width: '100%' }}
                value={sharedId1}
                onChange={setSharedId1}
                allowClear
                showSearch
                optionFilterProp="label"
                options={parseSharedList.map((s) => ({
                  value: s.id,
                  label: `#${s.id} ${s.original_filename}${s.asset_label ? ` · ${s.asset_label}` : ''}${s.sortie_label ? ` · ${s.sortie_label}` : ''}`,
                }))}
              />
            </Form.Item>
          ) : (
            <Form.Item label="交换机1 文件" tooltip="第一个交换机的 pcap/pcapng">
              <Upload
                beforeUpload={(f) => {
                  setFile1(f)
                  return false
                }}
                onRemove={() => setFile1(null)}
                maxCount={1}
                accept=".pcap,.pcapng,.cap"
              >
                <Button icon={<UploadOutlined />}>选择文件</Button>
              </Upload>
            </Form.Item>
          )}

          <Form.Item label="交换机2 数据来源" required>
            <Radio.Group
              value={mode2}
              onChange={(e) => {
                setMode2(e.target.value)
                setFile2(null)
                setSharedId2(null)
              }}
            >
              <Radio.Button value="platform">平台共享</Radio.Button>
              <Radio.Button value="local">本地上传</Radio.Button>
            </Radio.Group>
          </Form.Item>
          {mode2 === 'platform' ? (
            <Form.Item label="交换机2 平台数据">
              <Select
                placeholder="选择平台共享抓包"
                style={{ width: '100%' }}
                value={sharedId2}
                onChange={setSharedId2}
                allowClear
                showSearch
                optionFilterProp="label"
                options={parseSharedList.map((s) => ({
                  value: s.id,
                  label: `#${s.id} ${s.original_filename}${s.asset_label ? ` · ${s.asset_label}` : ''}${s.sortie_label ? ` · ${s.sortie_label}` : ''}`,
                }))}
              />
            </Form.Item>
          ) : (
            <Form.Item label="交换机2 文件">
              <Upload
                beforeUpload={(f) => {
                  setFile2(f)
                  return false
                }}
                onRemove={() => setFile2(null)}
                maxCount={1}
                accept=".pcap,.pcapng,.cap"
              >
                <Button icon={<UploadOutlined />}>选择文件</Button>
              </Upload>
            </Form.Item>
          )}

          <Form.Item
            name="protocol_version_id"
            label="网络配置版本"
            rules={[{ required: true, message: '请选择网络配置版本' }]}
            tooltip="用于获取端口定义和周期信息"
          >
            <Select
              placeholder="选择网络配置版本"
              showSearch
              optionFilterProp="children"
            >
              {versions.map((v) => (
                <Select.Option key={v.id} value={v.id}>
                  {v.protocol_name} - {v.version}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item
            name="jitter_threshold_pct"
            label="抖动阈值 (%)"
            initialValue={10}
            tooltip="允许的传输间隔抖动百分比，用于判定端口周期是否正确"
          >
            <Slider
              min={1}
              max={50}
              marks={{
                1: '1%',
                10: '10%',
                20: '20%',
                30: '30%',
                50: '50%'
              }}
              tooltip={{ formatter: (value) => `±${value}%` }}
            />
          </Form.Item>

          <Form.Item>
            {uploading && uploadProgress > 0 && (
              <Progress percent={uploadProgress} status="active" style={{ marginBottom: 12 }} />
            )}
            <Button
              type="primary"
              htmlType="submit"
              loading={uploading}
              disabled={
                !(
                  ((mode1 === 'local' && file1) || (mode1 === 'platform' && sharedId1))
                  && ((mode2 === 'local' && file2) || (mode2 === 'platform' && sharedId2))
                )
              }
              block
            >
              {uploading
                ? ((mode1 === 'local' || mode2 === 'local') ? `上传中 ${uploadProgress}%` : '提交中...')
                : '开始检查'}
            </Button>
          </Form.Item>
        </Form>
      </Card>
    )
  }

  // 结果区
  if (loading && !task) {
    return (
      <div style={{ textAlign: 'center', padding: 100 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  if (!task) {
    return <Alert message="任务不存在" type="error" />
  }

  return (
    <div>
      <Card
        title={
          <Space>
            <span>检查任务 #{task.id}</span>
            {getResultIcon(task.overall_result)}
            {getResultTag(task.overall_result)}
          </Space>
        }
        extra={
          <Space>
            {task.status === 'completed' && (
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                loading={exporting}
                onClick={handleExport}
              >
                导出报告
              </Button>
            )}
            <Button onClick={() => navigate('/compare')}>新建检查</Button>
          </Space>
        }
      >
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <div>交换机1: {task.filename_1}</div>
          </Col>
          <Col span={6}>
            <div>交换机2: {task.filename_2}</div>
          </Col>
          <Col span={6}>
            <div>状态: {task.status}</div>
          </Col>
          <Col span={6}>
            <div>创建时间: {new Date(task.created_at).toLocaleString('zh-CN')}</div>
          </Col>
        </Row>
        {task.bundle_version_id ? (
          <div style={{ marginBottom: 8 }}>
            <Tag
              color="purple"
              title={`本次异常检查基于 TSN 协议版本 #${task.bundle_version_id}`}
            >
              TSN {task.bundle_version_label
                ? task.bundle_version_label
                : `v${task.bundle_version_id}`}
            </Tag>
          </div>
        ) : null}

        {task.status === 'processing' && (
          <Progress percent={task.progress} status="active" />
        )}

        {task.status === 'failed' && (
          <Alert message="检查失败" description={task.error_message} type="error" showIcon />
        )}
      </Card>

      {task.status === 'completed' && (
        <div style={{ marginTop: 16 }}>
          <Collapse defaultActiveKey={['1', '2', '3', '4']}>
            {/* 检查1: 记录时间同步性 */}
            <Panel
              header={
                <Space>
                  <span>检查1: 记录时间同步性</span>
                  {getResultIcon(task.sync_result)}
                  {getResultTag(task.sync_result)}
                </Space>
              }
              key="1"
            >
              <Row gutter={16}>
                <Col span={8}>
                  <Statistic
                    title="交换机1首包时间"
                    value={formatTimestamp(task.switch1_first_ts)}
                  />
                </Col>
                <Col span={8}>
                  <Statistic
                    title="交换机2首包时间"
                    value={formatTimestamp(task.switch2_first_ts)}
                  />
                </Col>
                <Col span={8}>
                  <Statistic
                    title="时间差"
                    value={task.time_diff_ms?.toFixed(3) || '-'}
                    suffix="ms"
                    valueStyle={{
                      color: task.sync_result === 'pass' ? '#5fd068' : 
                             task.sync_result === 'warning' ? '#d4a843' : '#f05050'
                    }}
                  />
                </Col>
              </Row>
              <Alert
                style={{ marginTop: 16 }}
                message={
                  task.sync_result === 'pass' ? '两个交换机记录时间同步良好 (≤1ms)' :
                  task.sync_result === 'warning' ? '两个交换机记录时间存在一定偏差 (1-100ms)' :
                  '两个交换机记录时间偏差较大 (>100ms)'
                }
                type={task.sync_result === 'pass' ? 'success' : task.sync_result === 'warning' ? 'warning' : 'error'}
                showIcon
              />
            </Panel>

            {/* 检查2: 端口覆盖完整性 */}
            <Panel
              header={
                <Space>
                  <span>检查2: 端口覆盖完整性</span>
                  {task.missing_count === 0 ? getResultIcon('pass') : getResultIcon('fail')}
                </Space>
              }
              key="2"
            >
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={6}>
                  <Statistic title="网络配置端口总数" value={task.expected_port_count} />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="两边都有数据"
                    value={task.both_present_count}
                    valueStyle={{ color: '#5fd068' }}
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="至少一边缺失"
                    value={task.missing_count}
                    valueStyle={{ color: task.missing_count > 0 ? '#f05050' : '#5fd068' }}
                  />
                </Col>
              </Row>
              {(() => {
                const problemPorts = portResults.filter(r => r.result !== 'pass')
                return problemPorts.length > 0 ? (
                  <>
                    <Alert
                      message={`共 ${portResults.length} 个端口，其中 ${problemPorts.length} 个有问题（以下仅显示有问题的端口）`}
                      type="info"
                      showIcon
                      style={{ marginBottom: 12 }}
                    />
                    <Table
                      columns={portColumns}
                      dataSource={problemPorts}
                      rowKey="id"
                      size="small"
                      scroll={{ x: 1200 }}
                      pagination={{ pageSize: 20 }}
                      rowClassName={(record) => {
                        if (record.result === 'fail') return 'table-row-fail'
                        if (record.result === 'warning') return 'table-row-warning'
                        return ''
                      }}
                    />
                  </>
                ) : (
                  <Alert message="所有端口数据完整，无异常" type="success" showIcon />
                )
              })()}
            </Panel>

            {/* 检查3: 周期端口数据连续性 */}
            <Panel
              header={
                <Space>
                  <span>检查3: 周期端口数据连续性（丢包检测）</span>
                  {task.ports_with_gaps === 0 ? getResultIcon('pass') : getResultIcon('warning')}
                </Space>
              }
              key="3"
            >
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={6}>
                  <Statistic title="周期类端口总数" value={task.periodic_port_count} />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="存在丢包的端口"
                    value={task.ports_with_gaps}
                    valueStyle={{ color: task.ports_with_gaps > 0 ? '#d4a843' : '#5fd068' }}
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="总丢包段数"
                    value={task.total_gap_count}
                    valueStyle={{ color: task.total_gap_count > 0 ? '#d4a843' : '#5fd068' }}
                  />
                </Col>
              </Row>
              {gapRecords.length > 0 ? (
                <Table
                  columns={gapColumns}
                  dataSource={gapRecords}
                  rowKey="id"
                  size="small"
                  pagination={{ pageSize: 20 }}
                />
              ) : (
                <Alert message="未检测到丢包" type="success" showIcon />
              )}
            </Panel>

            {/* 检查4: 端口周期正确性与抖动分析 */}
            <Panel
              header={
                <Space>
                  <span>检查4: 端口周期正确性与抖动分析</span>
                  {task.timing_fail_count === 0 && task.timing_warning_count === 0 
                    ? getResultIcon('pass') 
                    : task.timing_fail_count > 0 
                    ? getResultIcon('fail') 
                    : getResultIcon('warning')}
                </Space>
              }
              key="4"
            >
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={6}>
                  <Statistic 
                    title="抖动阈值" 
                    value={task.jitter_threshold_pct} 
                    suffix="%" 
                  />
                </Col>
                <Col span={6}>
                  <Statistic 
                    title="检查端口数" 
                    value={task.timing_checked_port_count} 
                  />
                </Col>
                <Col span={4}>
                  <Statistic
                    title="通过"
                    value={task.timing_pass_count}
                    valueStyle={{ color: '#5fd068' }}
                  />
                </Col>
                <Col span={4}>
                  <Statistic
                    title="警告"
                    value={task.timing_warning_count}
                    valueStyle={{ color: '#d4a843' }}
                  />
                </Col>
                <Col span={4}>
                  <Statistic
                    title="失败"
                    value={task.timing_fail_count}
                    valueStyle={{ color: '#f05050' }}
                  />
                </Col>
              </Row>
              
              {timingResults.length > 0 ? (
                <Tabs
                  items={[
                    {
                      key: '1',
                      label: '交换机1',
                      children: (
                        <Table
                          columns={timingColumns}
                          dataSource={timingResults.filter(r => r.switch_index === 1)}
                          rowKey="id"
                          size="small"
                          scroll={{ x: 1500 }}
                          pagination={{ pageSize: 20 }}
                          rowClassName={(record) => {
                            if (record.result === 'fail') return 'table-row-fail'
                            if (record.result === 'warning') return 'table-row-warning'
                            return ''
                          }}
                        />
                      ),
                    },
                    {
                      key: '2',
                      label: '交换机2',
                      children: (
                        <Table
                          columns={timingColumns}
                          dataSource={timingResults.filter(r => r.switch_index === 2)}
                          rowKey="id"
                          size="small"
                          scroll={{ x: 1500 }}
                          pagination={{ pageSize: 20 }}
                          rowClassName={(record) => {
                            if (record.result === 'fail') return 'table-row-fail'
                            if (record.result === 'warning') return 'table-row-warning'
                            return ''
                          }}
                        />
                      ),
                    },
                  ]}
                />
              ) : (
                <Alert message="无周期端口数据或分析未完成" type="info" showIcon />
              )}
            </Panel>
          </Collapse>
        </div>
      )}

      <style>{`
        .table-row-fail {
          background-color: rgba(240, 80, 80, 0.08);
        }
        .table-row-warning {
          background-color: rgba(212, 168, 67, 0.08);
        }
      `}</style>
    </div>
  )
}

export default ComparePage
