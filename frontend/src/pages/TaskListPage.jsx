import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, Table, Tag, Button, Space, message, Tooltip, Progress, Input, Select, DatePicker,
  Typography, Dropdown, Modal, Popconfirm, Row, Col, Empty, Form,
} from 'antd'
import {
  EyeOutlined, LineChartOutlined, ReloadOutlined,
  CheckCircleOutlined, ClockCircleOutlined, LoadingOutlined, CloseCircleOutlined,
  SearchOutlined, DeleteOutlined, StopOutlined, MoreOutlined, RedoOutlined,
  FilterOutlined, TagsOutlined, AppstoreOutlined, UnorderedListOutlined,
} from '@ant-design/icons'
import { parseApi, protocolApi } from '../services/api'
import dayjs from 'dayjs'
import { formatBytes } from '../utils/fileFingerprint'
import AppPageHeader from '../components/AppPageHeader'

const { Text } = Typography
const { RangePicker } = DatePicker

const STATUS_OPTIONS = [
  { value: 'pending', label: '等待中' },
  { value: 'processing', label: '解析中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]

const SOURCE_OPTIONS = [
  { value: 'local', label: '本地上传' },
  { value: 'shared', label: '平台共享' },
]

const STAGE_LABELS = {
  queued: '排队中',
  reading: '读取中',
  parsing: '解析中',
  saving: '写入中',
}

function formatRemaining(ms) {
  if (!ms || ms < 0) return null
  const totalSec = Math.round(ms / 1000)
  if (totalSec < 60) return `约 ${totalSec}s`
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  if (m < 60) return `约 ${m}m${s ? ` ${s}s` : ''}`
  const h = Math.floor(m / 60)
  const mm = m % 60
  return `约 ${h}h${mm ? ` ${mm}m` : ''}`
}

function TaskListPage() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(false)
  const [versions, setVersions] = useState([])
  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 20,
    total: 0,
  })

  // 编辑弹窗：{ task, mode: 'rename' | 'tags' }
  const [editState, setEditState] = useState(null)
  const [editForm] = Form.useForm()
  const [editSubmitting, setEditSubmitting] = useState(false)

  // 过滤器
  const [filterQ, setFilterQ] = useState('')
  const [filterStatus, setFilterStatus] = useState([])
  const [filterSource, setFilterSource] = useState(null)
  const [filterVersion, setFilterVersion] = useState(null)
  const [filterRange, setFilterRange] = useState(null)
  const [filterDevice, setFilterDevice] = useState('')

  const buildParams = useCallback(() => {
    const params = {
      page: pagination.current,
      pageSize: pagination.pageSize,
    }
    if (filterQ) params.q = filterQ
    if (filterStatus.length) params.status = filterStatus.join(',')
    if (filterSource) params.source = filterSource
    if (filterVersion) params.protocol_version_id = filterVersion
    if (filterDevice) params.device = filterDevice.trim()
    if (filterRange && filterRange[0]) params.date_from = filterRange[0].startOf('day').toISOString()
    if (filterRange && filterRange[1]) params.date_to = filterRange[1].endOf('day').toISOString()
    return params
  }, [pagination.current, pagination.pageSize, filterQ, filterStatus, filterSource, filterVersion, filterDevice, filterRange])

  const loadTasks = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const res = await parseApi.listTasks(buildParams())
      setTasks(res.data.items || [])
      setPagination(prev => ({ ...prev, total: res.data.total }))
    } catch (err) {
      if (!silent) message.error('加载任务列表失败')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [buildParams])

  useEffect(() => {
    loadTasks(false)
  }, [loadTasks])

  useEffect(() => {
    // 只获取一次网络配置下拉
    protocolApi.listVersions().then((res) => {
      setVersions(res.data.items || [])
    }).catch(() => setVersions([]))
  }, [])

  useEffect(() => {
    const hasActive = tasks.some(t => t.status === 'pending' || t.status === 'processing')
    if (!hasActive) return undefined
    const id = setInterval(() => loadTasks(true), 3000)
    return () => clearInterval(id)
  }, [tasks, loadTasks])

  const openRename = (task) => {
    editForm.setFieldsValue({ display_name: task.display_name || '' })
    setEditState({ task, mode: 'rename' })
  }

  const openEditTags = (task) => {
    editForm.setFieldsValue({ tags_text: (task.tags || []).join(', ') })
    setEditState({ task, mode: 'tags' })
  }

  const closeEdit = () => {
    if (editSubmitting) return
    setEditState(null)
    editForm.resetFields()
  }

  const submitEdit = async () => {
    if (!editState) return
    try {
      const values = await editForm.validateFields()
      setEditSubmitting(true)
      if (editState.mode === 'rename') {
        const display_name = (values.display_name || '').trim() || null
        await parseApi.updateTaskMeta(editState.task.id, { display_name })
        message.success('已更新任务名称')
      } else {
        const tags = String(values.tags_text || '')
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
        await parseApi.updateTaskMeta(editState.task.id, { tags })
        message.success('已更新标签')
      }
      setEditState(null)
      editForm.resetFields()
      loadTasks(true)
    } catch (err) {
      if (err?.errorFields) return
      message.error(err?.response?.data?.detail || '更新失败')
    } finally {
      setEditSubmitting(false)
    }
  }

  const handleCancel = async (task) => {
    try {
      await parseApi.cancelTask(task.id)
      message.success('已请求取消，稍后将生效')
      loadTasks(true)
    } catch (err) {
      message.error(err.response?.data?.detail || '取消失败')
    }
  }

  const handleDelete = async (task) => {
    try {
      await parseApi.deleteTask(task.id)
      message.success('任务已删除')
      setSelectedRowKeys(prev => prev.filter(id => id !== task.id))
      loadTasks(true)
    } catch (err) {
      message.error(err.response?.data?.detail || '删除失败')
    }
  }

  const handleRerun = async (task) => {
    try {
      const res = await parseApi.rerunTask(task.id)
      message.success('已提交重新解析')
      loadTasks(true)
      if (res.data?.task_id) {
        navigate(`/tasks/${res.data.task_id}`)
      }
    } catch (err) {
      message.error(err.response?.data?.detail || '重试失败')
    }
  }

  const handleBulkDelete = () => {
    if (!selectedRowKeys.length) return
    Modal.confirm({
      title: `确认删除选中的 ${selectedRowKeys.length} 个任务？`,
      content: '将同步清理结果文件。若原始抓包不再被其它任务或共享数据引用，也会从磁盘移除。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await parseApi.bulkDeleteTasks(selectedRowKeys)
          message.success('批量删除已执行')
          setSelectedRowKeys([])
          loadTasks(false)
        } catch (err) {
          message.error(err.response?.data?.detail || '批量删除失败')
        }
      },
    })
  }

  const resetFilters = () => {
    setFilterQ('')
    setFilterStatus([])
    setFilterSource(null)
    setFilterVersion(null)
    setFilterRange(null)
    setFilterDevice('')
    setPagination(prev => ({ ...prev, current: 1 }))
  }

  const activeFilterCount = useMemo(() => {
    let n = 0
    if (filterQ) n += 1
    if (filterStatus.length) n += 1
    if (filterSource) n += 1
    if (filterVersion) n += 1
    if (filterRange) n += 1
    if (filterDevice) n += 1
    return n
  }, [filterQ, filterStatus, filterSource, filterVersion, filterRange, filterDevice])

  const renderStatus = (_, record) => {
    const status = record.status
    const statusMap = {
      pending: { color: 'default', icon: <ClockCircleOutlined />, text: '等待中' },
      processing: { color: 'processing', icon: <LoadingOutlined />, text: '解析中' },
      completed: { color: 'success', icon: <CheckCircleOutlined />, text: '已完成' },
      failed: { color: 'error', icon: <CloseCircleOutlined />, text: '失败' },
      cancelled: { color: 'warning', icon: <StopOutlined />, text: '已取消' },
    }
    const config = statusMap[status] || statusMap.pending
    const pct = typeof record.progress === 'number' ? record.progress : 0
    const remaining = record.estimated_remaining_ms
    const stageLabel = STAGE_LABELS[record.stage] || null
    return (
      <Space direction="vertical" size={4} style={{ width: '100%', minWidth: 160 }}>
        <Space size={4}>
          <Tag color={config.color} icon={config.icon} style={{ margin: 0 }}>{config.text}</Tag>
          {record.cancel_requested && status === 'processing' && (
            <Tag color="warning" style={{ margin: 0 }}>取消中</Tag>
          )}
        </Space>
        {(status === 'processing' || status === 'pending') && (
          <>
            <Progress
              percent={status === 'pending' ? 0 : pct}
              size="small"
              status={status === 'pending' ? 'normal' : 'active'}
              showInfo
              format={(p) => `${p ?? 0}%`}
            />
            <div style={{ fontSize: 11, color: '#a1a1aa' }}>
              {stageLabel || (status === 'pending' ? '排队中' : '')}
              {remaining ? ` · 剩余 ${formatRemaining(remaining)}` : ''}
            </div>
          </>
        )}
        {status === 'failed' && record.error_message && (
          <Tooltip title={record.error_message}>
            <Text type="danger" style={{ fontSize: 11 }} ellipsis={{ tooltip: true }}>
              {record.error_message}
            </Text>
          </Tooltip>
        )}
      </Space>
    )
  }

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 70,
      render: (id) => <span className="mono">#{id}</span>,
    },
    {
      title: '任务',
      key: 'name',
      ellipsis: true,
      render: (_, record) => (
        <Space direction="vertical" size={2} style={{ minWidth: 0 }}>
          <Space size={6} wrap>
            <Text
              strong
              style={{ color: '#f4f4f5' }}
              ellipsis={{ tooltip: record.display_name || record.filename }}
            >
              {record.display_name || record.filename}
            </Text>
            {record.is_shared_source && (
              <Tag style={{ margin: 0, background: 'rgba(139, 92, 246, 0.15)', borderColor: 'rgba(139, 92, 246, 0.4)', color: '#a78bfa' }}>
                共享
              </Tag>
            )}
          </Space>
          {record.display_name && record.filename !== record.display_name && (
            <Text type="secondary" className="mono" style={{ fontSize: 11 }} ellipsis={{ tooltip: record.filename }}>
              {record.filename}
            </Text>
          )}
          <Space size={4} wrap>
            {record.file_size != null && (
              <Text type="secondary" style={{ fontSize: 11 }}>{formatBytes(record.file_size)}</Text>
            )}
            {(record.tags || []).map(t => (
              <Tag key={t} style={{ margin: 0, background: 'rgba(95, 208, 104, 0.12)', borderColor: '#5fd068', color: '#5fd068', fontSize: 11 }}>
                {t}
              </Tag>
            ))}
          </Space>
        </Space>
      ),
    },
    {
      title: '网络配置',
      key: 'network_config',
      width: 180,
      render: (_, record) => (
        record.network_config_name ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
            <span>{record.network_config_name}</span>
            <Tag style={{ margin: 0, background: 'rgba(139, 92, 246, 0.15)', borderColor: 'rgba(139, 92, 246, 0.4)', color: '#a78bfa' }}>{record.network_config_version}</Tag>
          </div>
        ) : (
          <Tag style={{ background: '#18181b', borderColor: '#27272a', color: '#a1a1aa' }}>扫描模式</Tag>
        )
      ),
    },
    {
      title: '设备 / 解析器',
      key: 'parser_profile',
      width: 280,
      render: (_, record) => {
        if (record.device_parsers && record.device_parsers.length > 0) {
          return (
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              {record.device_parsers.map(dp => (
                <div key={dp.device_name} style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                  <Tag style={{ margin: 0, background: 'rgba(212, 168, 67, 0.15)', borderColor: '#d4a843', color: '#d4a843' }}>{dp.device_name}</Tag>
                  <Tag style={{ margin: 0, background: 'rgba(95, 208, 104, 0.15)', borderColor: '#5fd068', color: '#5fd068' }}>{[dp.parser_profile_name, dp.parser_profile_version].filter(Boolean).join(' ')}</Tag>
                </div>
              ))}
            </Space>
          )
        }
        return (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', alignItems: 'center' }}>
            <span style={{ fontWeight: 500 }}>{record.parser_profile_name || '-'}</span>
            {record.parser_profile_version && (
              <Tag style={{ margin: 0, background: 'rgba(95, 208, 104, 0.15)', borderColor: '#5fd068', color: '#5fd068' }}>{record.parser_profile_version}</Tag>
            )}
          </div>
        )
      },
    },
    {
      title: '状态',
      key: 'status',
      width: 210,
      render: renderStatus,
    },
    {
      title: '解析数据量',
      dataIndex: 'parsed_packets',
      width: 110,
      render: (count) => (
        <span className="mono" style={{ color: '#5fd068' }}>
          {count?.toLocaleString() || 0}
        </span>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 160,
      render: (time) => <span style={{ fontSize: 12 }}>{dayjs(time).format('YYYY-MM-DD HH:mm')}</span>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 140,
      fixed: 'right',
      align: 'center',
      render: (_, record) => {
        const canCancel = record.status === 'pending' || record.status === 'processing'
        const canAnalyze = record.status === 'completed'
        const canRerun = record.can_rerun
        const items = [
          {
            key: 'rename',
            icon: <TagsOutlined />,
            label: '重命名',
            onClick: () => openRename(record),
          },
          {
            key: 'tag',
            icon: <TagsOutlined />,
            label: '编辑标签',
            onClick: () => openEditTags(record),
          },
          canRerun ? {
            key: 'rerun',
            icon: <RedoOutlined />,
            label: '重新解析',
            onClick: () => handleRerun(record),
          } : null,
          canCancel ? {
            key: 'cancel',
            icon: <StopOutlined />,
            label: '取消任务',
            onClick: () => handleCancel(record),
          } : null,
          { type: 'divider' },
          {
            key: 'delete',
            icon: <DeleteOutlined />,
            danger: true,
            label: (
              <Popconfirm
                title="确认删除该任务？"
                description="结果数据将被清理；原文件仅在不再被引用时删除。"
                okText="删除"
                okButtonProps={{ danger: true }}
                cancelText="取消"
                onConfirm={() => handleDelete(record)}
              >
                <span>删除</span>
              </Popconfirm>
            ),
          },
        ].filter(Boolean)
        return (
          <Space size={2} onClick={(e) => e.stopPropagation()}>
            <Tooltip title="查看详情">
              <Button
                type="text"
                size="small"
                icon={<EyeOutlined />}
                onClick={() => navigate(`/tasks/${record.id}`)}
              />
            </Tooltip>
            <Tooltip title={canAnalyze ? '异常分析' : '任务完成后可分析'}>
              <Button
                type="text"
                size="small"
                icon={<LineChartOutlined />}
                onClick={() => navigate(`/tasks/${record.id}?tab=anomaly`)}
                disabled={!canAnalyze}
              />
            </Tooltip>
            <Dropdown menu={{ items }} trigger={['click']} placement="bottomRight">
              <Button type="text" size="small" icon={<MoreOutlined />} />
            </Dropdown>
          </Space>
        )
      },
    },
  ]

  return (
    <div className="app-page-shell fade-in">
      <div className="app-page-shell-inner">
        <AppPageHeader
          icon={<UnorderedListOutlined />}
          eyebrow="任务管理"
          title="任务中心"
          subtitle="查看所有解析任务的运行状态、过滤/搜索历史任务、重试失败任务或跳转到结果分析页面。"
          tags={activeFilterCount > 0 ? [{ text: `${activeFilterCount} 项筛选` }] : undefined}
          actions={
            <Space>
              {selectedRowKeys.length > 0 && (
                <Button danger icon={<DeleteOutlined />} onClick={handleBulkDelete}>
                  删除选中（{selectedRowKeys.length}）
                </Button>
              )}
              <Button
                icon={<ReloadOutlined />}
                onClick={() => loadTasks(false)}
                loading={loading}
              >
                刷新
              </Button>
            </Space>
          }
        />
        <div className="app-page-body">
      <Card>
        <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
          <Col xs={24} md={8} lg={6}>
            <Input.Search
              allowClear
              placeholder="搜索文件名 / 显示名"
              prefix={<SearchOutlined />}
              value={filterQ}
              onChange={(e) => setFilterQ(e.target.value)}
              onSearch={() => setPagination(p => ({ ...p, current: 1 }))}
            />
          </Col>
          <Col xs={12} md={4} lg={3}>
            <Select
              allowClear
              placeholder="上传方式"
              style={{ width: '100%' }}
              value={filterSource}
              onChange={(v) => { setFilterSource(v); setPagination(p => ({ ...p, current: 1 })) }}
              options={SOURCE_OPTIONS}
            />
          </Col>
          <Col xs={12} md={4} lg={4}>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="网络配置"
              style={{ width: '100%' }}
              value={filterVersion}
              onChange={(v) => { setFilterVersion(v); setPagination(p => ({ ...p, current: 1 })) }}
              options={versions.map(v => ({ value: v.id, label: `${v.protocol_name} ${v.version}` }))}
            />
          </Col>
          <Col xs={12} md={4} lg={3}>
            <Input
              allowClear
              placeholder="设备"
              prefix={<AppstoreOutlined />}
              value={filterDevice}
              onChange={(e) => setFilterDevice(e.target.value)}
              onPressEnter={() => setPagination(p => ({ ...p, current: 1 }))}
            />
          </Col>
          <Col xs={24} md={8} lg={4}>
            <Select
              mode="multiple"
              allowClear
              placeholder="状态"
              style={{ width: '100%' }}
              value={filterStatus}
              onChange={(v) => { setFilterStatus(v); setPagination(p => ({ ...p, current: 1 })) }}
              options={STATUS_OPTIONS}
              maxTagCount="responsive"
            />
          </Col>
          <Col xs={24} md={8} lg={4}>
            <RangePicker
              style={{ width: '100%' }}
              value={filterRange}
              onChange={(r) => { setFilterRange(r); setPagination(p => ({ ...p, current: 1 })) }}
            />
          </Col>
          {activeFilterCount > 0 && (
            <Col>
              <Button type="text" icon={<FilterOutlined />} onClick={resetFilters}>
                清除筛选
              </Button>
            </Col>
          )}
        </Row>

        <Table
          columns={columns}
          dataSource={tasks}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1600 }}
          rowSelection={{
            selectedRowKeys,
            onChange: setSelectedRowKeys,
            preserveSelectedRowKeys: true,
          }}
          locale={{
            emptyText: loading ? ' ' : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={activeFilterCount > 0 ? '当前筛选条件下没有任务' : '还没有解析任务，点击左侧「上传解析」开始'}
              />
            ),
          }}
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              setPagination(prev => ({ ...prev, current: page, pageSize }))
            },
          }}
        />
      </Card>
        </div>
      </div>
      <Modal
        title={editState?.mode === 'rename' ? '重命名任务' : '编辑任务标签'}
        open={!!editState}
        onCancel={closeEdit}
        onOk={submitEdit}
        confirmLoading={editSubmitting}
        okText="保存"
        cancelText="取消"
        destroyOnClose
      >
        {editState ? (
          <Form form={editForm} layout="vertical" preserve={false}>
            {editState.mode === 'rename' ? (
              <>
                <div style={{ color: '#a1a1aa', fontSize: 12, marginBottom: 8 }}>
                  原文件名：<span className="mono">{editState.task.filename}</span>
                </div>
                <Form.Item
                  name="display_name"
                  label="显示名称"
                  rules={[{ max: 128, message: '不超过 128 个字符' }]}
                  extra="留空则使用原文件名显示"
                >
                  <Input allowClear maxLength={128} placeholder="为该任务起一个便于识别的名称" />
                </Form.Item>
              </>
            ) : (
              <Form.Item
                name="tags_text"
                label="标签"
                extra="多个标签用英文逗号分隔，例如：试飞,A架次,回归"
              >
                <Input.TextArea rows={3} allowClear placeholder="试飞, A架次, 回归" />
              </Form.Item>
            )}
          </Form>
        ) : null}
      </Modal>
    </div>
  )
}

export default TaskListPage
