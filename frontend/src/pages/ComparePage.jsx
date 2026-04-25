import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react'
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
  SwapOutlined,
} from '@ant-design/icons'
import { compareApi, protocolApi, sharedTsnApi } from '../services/api'
import { isParseCompatibleSharedItem } from '../utils/sharedPlatform'
import AppPageHeader from '../components/AppPageHeader'

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

  // Part 2 → Part 3 跳转、Collapse 受控、Part 3 过滤
  const [collapseKeys, setCollapseKeys] = useState(['1', '2', '3', '4'])
  const [gapFilter, setGapFilter] = useState(null) // { port_number, switch_index } | null
  const check3Ref = useRef(null)

  // 顶部历史记录面板
  const [historyActiveKey, setHistoryActiveKey] = useState([])
  const [historyItems, setHistoryItems] = useState([])
  const [historyTotal, setHistoryTotal] = useState(0)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [historyPage, setHistoryPage] = useState(1)
  const historyPageSize = 20

  // 加载 TSN 网络协议版本列表
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
      // 切到新任务时，清除 Part 2→3 跳转过滤
      setGapFilter(null)
      setCollapseKeys(['1', '2', '3', '4'])
    }
  }, [taskId])

  const loadHistory = useCallback(async (page = 1) => {
    try {
      setHistoryLoading(true)
      const res = await compareApi.listTasks(page, historyPageSize)
      setHistoryItems(res.data.items || [])
      setHistoryTotal(res.data.total || 0)
      setHistoryPage(page)
      setHistoryLoaded(true)
    } catch (error) {
      message.error('加载历史记录失败')
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  const handleHistoryCollapseChange = (keys) => {
    const arr = Array.isArray(keys) ? keys : [keys].filter(Boolean)
    setHistoryActiveKey(arr)
    if (arr.includes('history') && !historyLoaded && !historyLoading) {
      loadHistory(1)
    }
  }

  const jumpToGapForPort = useCallback((portNumber, switchIndex) => {
    setGapFilter({ port_number: portNumber, switch_index: switchIndex })
    setCollapseKeys((prev) => {
      const set = new Set(prev)
      set.add('3')
      return Array.from(set)
    })
    // 等 Collapse 动画再滚动
    requestAnimationFrame(() => {
      setTimeout(() => {
        check3Ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 50)
    })
  }, [])

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
      message.error('加载 TSN 网络协议版本失败')
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

  // 派生 (交换机,端口) 维度的行
  const perSwitchPortRows = useMemo(() => {
    const rows = []
    for (const r of portResults) {
      // 是否为"ICD 配置的期望端口"：compare_service 对非配置端口会生成 warning "非网络配置端口"
      const unexpected = r.result === 'warning' && typeof r.detail === 'string' && r.detail.startsWith('非网络配置端口')
      for (const side of [1, 2]) {
        const present = side === 1 ? r.in_switch1 : r.in_switch2
        const count = side === 1 ? r.switch1_count : r.switch2_count
        const gapCount = (side === 1 ? r.gap_count_switch1 : r.gap_count_switch2) || 0
        let status
        if (unexpected) status = 'unexpected'
        else if (!present) status = 'missing'
        else if (gapCount > 0) status = 'gaps'
        else status = 'ok'
        rows.push({
          key: `${r.id}-${side}`,
          port_id: r.id,
          port_number: r.port_number,
          switch_index: side,
          source_device: r.source_device,
          message_name: r.message_name,
          period_ms: r.period_ms,
          packet_count: count || 0,
          gap_count: gapCount,
          status,
        })
      }
    }
    rows.sort((a, b) => {
      if (a.switch_index !== b.switch_index) return a.switch_index - b.switch_index
      return a.port_number - b.port_number
    })
    return rows
  }, [portResults])

  const perSwitchSummary = useMemo(() => {
    const s = { total: perSwitchPortRows.length, s1: 0, s2: 0, ok: 0, gaps: 0, missing: 0, unexpected: 0 }
    for (const r of perSwitchPortRows) {
      if (r.switch_index === 1) s.s1 += 1
      else if (r.switch_index === 2) s.s2 += 1
      s[r.status] = (s[r.status] || 0) + 1
    }
    return s
  }, [perSwitchPortRows])

  const renderStatusTag = (status, gapCount) => {
    if (status === 'ok') return <Tag color="success">正常</Tag>
    if (status === 'gaps') return <Tag color="warning">不连续（{gapCount} 段）</Tag>
    if (status === 'missing') return <Tag color="error">缺失</Tag>
    if (status === 'unexpected') return <Tag color="purple">非配置端口</Tag>
    return <Tag>未知</Tag>
  }

  // 端口结果表格列（(交换机,端口) 级全量）
  const portColumns = [
    {
      title: '交换机',
      dataIndex: 'switch_index',
      key: 'switch_index',
      width: 90,
      filters: [
        { text: '交换机1', value: 1 },
        { text: '交换机2', value: 2 },
      ],
      onFilter: (value, record) => record.switch_index === value,
      sorter: (a, b) => a.switch_index - b.switch_index,
      render: (val) => `交换机${val}`,
    },
    {
      title: '端口号',
      dataIndex: 'port_number',
      key: 'port_number',
      width: 100,
      sorter: (a, b) => a.port_number - b.port_number,
      defaultSortOrder: 'ascend',
    },
    {
      title: '源设备',
      dataIndex: 'source_device',
      key: 'source_device',
      width: 150,
      render: (val) => val || '-',
    },
    {
      title: '消息名称',
      dataIndex: 'message_name',
      key: 'message_name',
      width: 200,
      render: (val) => val || '-',
    },
    {
      title: '周期(ms)',
      dataIndex: 'period_ms',
      key: 'period_ms',
      width: 100,
      render: (val) => (val ? val.toFixed(1) : '-'),
    },
    {
      title: '包数',
      dataIndex: 'packet_count',
      key: 'packet_count',
      width: 100,
      sorter: (a, b) => a.packet_count - b.packet_count,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 150,
      filters: [
        { text: '正常', value: 'ok' },
        { text: '不连续', value: 'gaps' },
        { text: '缺失', value: 'missing' },
        { text: '非配置端口', value: 'unexpected' },
      ],
      onFilter: (value, record) => record.status === value,
      render: (val, record) => renderStatusTag(val, record.gap_count),
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      render: (_, record) =>
        record.status === 'gaps' ? (
          <Button
            type="link"
            size="small"
            onClick={() => jumpToGapForPort(record.port_number, record.switch_index)}
          >
            查看丢包详情
          </Button>
        ) : null,
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

  // 历史记录表格列
  const historyColumns = [
    {
      title: '任务ID',
      dataIndex: 'id',
      key: 'id',
      width: 90,
      render: (val) => `#${val}`,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (val) => (val ? new Date(val).toLocaleString('zh-CN') : '-'),
    },
    {
      title: '交换机1 文件',
      dataIndex: 'filename_1',
      key: 'filename_1',
      ellipsis: true,
    },
    {
      title: '交换机2 文件',
      dataIndex: 'filename_2',
      key: 'filename_2',
      ellipsis: true,
    },
    {
      title: 'TSN 版本',
      dataIndex: 'bundle_version_label',
      key: 'bundle_version_label',
      width: 130,
      render: (val, record) =>
        record.bundle_version_id ? (
          <Tag color="purple">{val || `v${record.bundle_version_id}`}</Tag>
        ) : (
          '-'
        ),
    },
    {
      title: '整体结果',
      dataIndex: 'overall_result',
      key: 'overall_result',
      width: 100,
      render: (val) => getResultTag(val),
    },
    {
      title: '丢包端口',
      dataIndex: 'ports_with_gaps',
      key: 'ports_with_gaps',
      width: 90,
      render: (val) => (val > 0 ? <Tag color="warning">{val}</Tag> : val ?? 0),
    },
    {
      title: '缺失',
      dataIndex: 'missing_count',
      key: 'missing_count',
      width: 80,
      render: (val) => (val > 0 ? <Tag color="error">{val}</Tag> : val ?? 0),
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, record) => (
        <Button
          type="link"
          size="small"
          onClick={() => navigate(`/compare/${record.id}`)}
        >
          查看
        </Button>
      ),
    },
  ]

  // Part 3 的过滤结果
  const filteredGapRecords = useMemo(() => {
    if (!gapFilter) return gapRecords
    return gapRecords.filter(
      (g) =>
        g.port_number === gapFilter.port_number &&
        g.switch_index === gapFilter.switch_index,
    )
  }, [gapRecords, gapFilter])

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

  // 历史记录折叠面板（上传页 & 详情页共用）
  const renderHistoryPanel = () => (
    <Collapse
      activeKey={historyActiveKey}
      onChange={handleHistoryCollapseChange}
      style={{ marginBottom: 16 }}
    >
      <Panel
        header={
          <Space>
            <span>历史记录</span>
            {historyLoaded ? (
              <Tag>{historyTotal} 条</Tag>
            ) : (
              <Tag color="default">点击展开查看</Tag>
            )}
          </Space>
        }
        key="history"
      >
        <Table
          columns={historyColumns}
          dataSource={historyItems}
          rowKey="id"
          size="small"
          loading={historyLoading}
          scroll={{ x: 1100 }}
          pagination={{
            current: historyPage,
            pageSize: historyPageSize,
            total: historyTotal,
            showSizeChanger: false,
            onChange: (p) => loadHistory(p),
          }}
        />
      </Panel>
    </Collapse>
  )

  // 上传区
  if (!taskId) {
    return (
      <div style={{ maxWidth: 1000, margin: '0 auto' }}>
        <AppPageHeader
          variant="lite"
          icon={<SwapOutlined />}
          eyebrow="数据质量"
          title="TSN 数据异常检查"
          subtitle="上传两个交换机的抓包文件，系统将执行四项检查：记录时间同步性、端口覆盖完整性、周期端口数据连续性（丢包检测），以及端口周期正确性与抖动分析。"
        />
        {renderHistoryPanel()}
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
            label="TSN 网络协议版本"
            rules={[{ required: true, message: '请选择 TSN 网络协议版本' }]}
            tooltip="用于获取端口定义和周期信息"
          >
            <Select
              placeholder="选择 TSN 网络协议版本"
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
      </div>
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
      {renderHistoryPanel()}
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
          <Collapse
            activeKey={collapseKeys}
            onChange={(keys) => setCollapseKeys(Array.isArray(keys) ? keys : [keys].filter(Boolean))}
          >
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
                  <Statistic title="协议约定端口总数" value={task.expected_port_count} />
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
              {perSwitchPortRows.length > 0 ? (
                <>
                  <Alert
                    message={
                      <span>
                        共 {perSwitchSummary.total} 行（交换机1: {perSwitchSummary.s1}，
                        交换机2: {perSwitchSummary.s2}）　·　
                        <Tag color="success">正常 {perSwitchSummary.ok || 0}</Tag>
                        <Tag color="warning">不连续 {perSwitchSummary.gaps || 0}</Tag>
                        <Tag color="error">缺失 {perSwitchSummary.missing || 0}</Tag>
                        <Tag color="purple">非配置端口 {perSwitchSummary.unexpected || 0}</Tag>
                      </span>
                    }
                    type="info"
                    showIcon
                    style={{ marginBottom: 12 }}
                  />
                  <Table
                    columns={portColumns}
                    dataSource={perSwitchPortRows}
                    rowKey="key"
                    size="small"
                    scroll={{ x: 1100 }}
                    pagination={{
                      pageSize: 20,
                      showSizeChanger: true,
                      pageSizeOptions: ['10', '20', '50', '100'],
                    }}
                    rowClassName={(record) => {
                      if (record.status === 'missing') return 'table-row-fail'
                      if (record.status === 'gaps' || record.status === 'unexpected')
                        return 'table-row-warning'
                      return ''
                    }}
                  />
                </>
              ) : (
                <Alert message="无端口数据" type="info" showIcon />
              )}
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
              <div ref={check3Ref} id="check3-anchor">
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
                {gapFilter && (
                  <Alert
                    style={{ marginBottom: 12 }}
                    type="info"
                    showIcon
                    message={
                      <Space>
                        <span>
                          当前仅查看端口 <strong>{gapFilter.port_number}</strong> · 交换机
                          {gapFilter.switch_index}，筛出 {filteredGapRecords.length} 条丢包段
                        </span>
                        <Button
                          type="link"
                          size="small"
                          onClick={() => setGapFilter(null)}
                        >
                          查看全部
                        </Button>
                      </Space>
                    }
                  />
                )}
                {filteredGapRecords.length > 0 ? (
                  <Table
                    columns={gapColumns}
                    dataSource={filteredGapRecords}
                    rowKey="id"
                    size="small"
                    pagination={{ pageSize: 20 }}
                  />
                ) : gapFilter ? (
                  <Alert
                    message="该端口/该交换机暂无丢包明细"
                    type="success"
                    showIcon
                  />
                ) : (
                  <Alert message="未检测到丢包" type="success" showIcon />
                )}
              </div>
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
