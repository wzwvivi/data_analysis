import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Alert,
  Badge,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  ClockCircleOutlined,
  StopOutlined,
  SearchOutlined,
  DownOutlined,
  UpOutlined,
  UnorderedListOutlined,
  BranchesOutlined,
  ThunderboltFilled,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
import { networkConfigApi } from '../../services/api'
import { useAuth } from '../../context/AuthContext'
import {
  DIRECTION_TABS,
  ICD_COLUMN_SETS,
  buildFilters,
  matchPortKeyword,
} from './icdColumns'
import ActivationPanel from './ActivationPanel'

const { Text, Paragraph } = Typography

const STATUS_META = {
  Available:   { color: 'success',    label: '可用',        icon: <SafetyCertificateOutlined /> },
  PendingCode: { color: 'processing', label: '待代码就绪',  icon: <ClockCircleOutlined /> },
  Deprecated:  { color: 'default',    label: '已弃用',      icon: <StopOutlined /> },
}

function formatTime(value) {
  if (!value) return '-'
  try {
    return dayjs(value).format('YYYY-MM-DD HH:mm:ss')
  } catch {
    return String(value)
  }
}

function formatRelative(value) {
  if (!value) return ''
  try {
    return dayjs(value).locale('zh-cn').fromNow()
  } catch {
    return ''
  }
}

/** 字段子表（只读） */
function FieldSubTable({ port, fields, loading }) {
  const rows = fields || []

  const columns = useMemo(() => [
    {
      title: '消息内数据集',
      dataIndex: 'field_name',
      width: 220,
      filters: buildFilters(rows, 'field_name'),
      filterSearch: true,
      onFilter: (v, r) => (r.field_name || '') === v,
    },
    {
      title: '消息内偏移',
      dataIndex: 'field_offset',
      width: 110,
      sorter: (a, b) => (a.field_offset ?? 0) - (b.field_offset ?? 0),
      defaultSortOrder: 'ascend',
    },
    {
      title: '长度',
      dataIndex: 'field_length',
      width: 90,
      sorter: (a, b) => (a.field_length ?? 0) - (b.field_length ?? 0),
    },
    {
      title: <Tooltip title="平台解析扩展列，非 ICD 原表头">数据类型 <span style={{ color: '#a1a1aa' }}>*</span></Tooltip>,
      dataIndex: 'data_type',
      width: 110,
      filters: buildFilters(rows, 'data_type'),
      onFilter: (v, r) => (r.data_type || '') === v,
    },
    {
      title: <Tooltip title="平台解析扩展列，非 ICD 原表头">字节序 <span style={{ color: '#a1a1aa' }}>*</span></Tooltip>,
      dataIndex: 'byte_order',
      width: 90,
      filters: buildFilters(rows, 'byte_order'),
      onFilter: (v, r) => (r.byte_order || '') === v,
    },
    {
      title: <Tooltip title="平台解析扩展列，非 ICD 原表头">系数 <span style={{ color: '#a1a1aa' }}>*</span></Tooltip>,
      dataIndex: 'scale_factor',
      width: 80,
    },
    {
      title: <Tooltip title="平台解析扩展列，非 ICD 原表头">单位 <span style={{ color: '#a1a1aa' }}>*</span></Tooltip>,
      dataIndex: 'unit',
      width: 80,
      filters: buildFilters(rows, 'unit'),
      filterSearch: true,
      onFilter: (v, r) => (r.unit || '') === v,
    },
    {
      title: <Tooltip title="平台解析扩展列，非 ICD 原表头">说明 <span style={{ color: '#a1a1aa' }}>*</span></Tooltip>,
      dataIndex: 'description',
      ellipsis: true,
    },
  ], [rows])

  return (
    <div style={{
      padding: '8px 12px',
      background: 'rgba(250, 250, 252, 0.02)',
      borderLeft: '3px solid #6d28d9',
      borderRadius: 4,
    }}>
      <Space style={{ marginBottom: 8 }} wrap>
        <Text strong>
          端口 {port.port_number} · {port.message_name || '—'} 的字段（ICD 数据集）
        </Text>
        <Tag color="default">共 {rows.length} 个字段</Tag>
      </Space>
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={rows}
        columns={columns}
        pagination={false}
      />
    </div>
  )
}

function VersionViewerPage() {
  const { id: versionId } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const canWrite = user && ['admin', 'network_team'].includes((user.role || '').trim())
  const isAdmin = user && (user.role || '').trim() === 'admin'

  const [loading, setLoading] = useState(false)
  const [version, setVersion] = useState(null)
  const [ports, setPorts] = useState([])
  const [activeDir, setActiveDir] = useState('uplink')
  const [expandedRowKeys, setExpandedRowKeys] = useState([])
  const [portKeyword, setPortKeyword] = useState('')

  // port.id -> { loading, fields: [] }
  const [fieldCache, setFieldCache] = useState({})

  // Modal: clone from this version
  const [cloneOpen, setCloneOpen] = useState(false)
  const [cloneForm] = Form.useForm()

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      const [detailRes, portsRes] = await Promise.all([
        networkConfigApi.getVersion(versionId),
        networkConfigApi.getVersionPorts(versionId),
      ])
      setVersion(detailRes.data)
      setPorts(portsRes.data?.items || [])
    } catch (err) {
      message.error(err?.response?.data?.detail || '加载版本失败')
    } finally {
      setLoading(false)
    }
  }, [versionId])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  const portsByDir = useMemo(() => {
    const map = { uplink: [], downlink: [], network: [] }
    for (const p of ports) {
      const dir = (p.data_direction || 'network').toLowerCase()
      ;(map[dir] || map.network).push(p)
    }
    return map
  }, [ports])

  const loadPortFields = useCallback(async (port) => {
    if (fieldCache[port.id]?.fields) return
    setFieldCache((prev) => ({
      ...prev,
      [port.id]: { loading: true, fields: prev[port.id]?.fields || [] },
    }))
    try {
      const res = await networkConfigApi.getPortDetail(versionId, port.port_number)
      setFieldCache((prev) => ({
        ...prev,
        [port.id]: { loading: false, fields: res.data?.fields || [] },
      }))
    } catch (err) {
      setFieldCache((prev) => ({
        ...prev,
        [port.id]: { loading: false, fields: [] },
      }))
      message.error(err?.response?.data?.detail || `加载端口 ${port.port_number} 字段失败`)
    }
  }, [versionId, fieldCache])

  const makePortColumns = (rowsForDir, dirKey) => {
    const icdCols = ICD_COLUMN_SETS[dirKey] || ICD_COLUMN_SETS.uplink
    const base = icdCols.map((c) => {
      const col = {
        title: c.title,
        dataIndex: c.dataIndex,
        width: c.width,
        ellipsis: c.ellipsis,
        filters: buildFilters(rowsForDir, c.dataIndex),
        filterSearch: true,
        onFilter: (value, record) => String(record[c.dataIndex] ?? '') === String(value),
      }
      if (c.fixed) col.fixed = c.fixed
      if (c.sort) {
        col.sorter = (a, b) => (Number(a[c.dataIndex]) || 0) - (Number(b[c.dataIndex]) || 0)
        col.defaultSortOrder = 'ascend'
      }
      if (c.dataIndex === 'port_number') {
        col.render = (v) => <Text strong>{v}</Text>
      }
      return col
    })

    const extra = [
      {
        title: '协议族（平台扩展）',
        dataIndex: 'protocol_family',
        width: 150,
        filters: buildFilters(rowsForDir, 'protocol_family_resolved'),
        filterSearch: true,
        onFilter: (value, record) =>
          (record.protocol_family || record.protocol_family_resolved || '') === value,
        render: (v, r) => {
          if (!v && r.protocol_family_resolved) {
            return <Tooltip title="由端口号兜底映射"><Tag>{r.protocol_family_resolved} (兜底)</Tag></Tooltip>
          }
          if (!v && !r.protocol_family_resolved) return <Tag color="warning">未映射</Tag>
          return <Tag color="blue">{v}</Tag>
        },
      },
      {
        title: '端口角色',
        dataIndex: 'port_role',
        width: 160,
        filters: [
          { text: 'TSN 异常检查', value: 'tsn_anomaly' },
          { text: '飞管事件分析', value: 'fms_event' },
          { text: '飞控事件分析 · 状态帧', value: 'fcc_status' },
          { text: '飞控事件分析 · 通道选择', value: 'fcc_channel' },
          { text: '飞控事件分析 · 故障码', value: 'fcc_fault' },
          { text: '飞控事件分析（聚合）', value: 'fcc_event' },
          { text: '自动飞行分析', value: 'auto_flight' },
          { text: '自动飞行分析 · IRS 输入', value: 'irs_input' },
          { text: '其它 / 未分类', value: 'other' },
        ],
        onFilter: (value, record) => (record.port_role || '') === value,
        render: (v) => {
          const labels = {
            tsn_anomaly: 'TSN 异常检查',
            fms_event:   '飞管事件分析',
            fcc_status:  '飞控事件分析 · 状态帧',
            fcc_channel: '飞控事件分析 · 通道选择',
            fcc_fault:   '飞控事件分析 · 故障码',
            fcc_event:   '飞控事件分析（聚合）',
            auto_flight: '自动飞行分析',
            irs_input:   '自动飞行分析 · IRS 输入',
            other:       '其它 / 未分类',
          }
          return v
            ? <Tag color="geekblue">{labels[v] || v}</Tag>
            : <Tag color="default">未指定</Tag>
        },
      },
      {
        title: '字段详情',
        dataIndex: 'field_count',
        width: 150,
        align: 'center',
        fixed: 'right',
        render: (count, record) => {
          const isOpen = expandedRowKeys.includes(record.id)
          return (
            <Button
              size="small"
              type={isOpen ? 'primary' : 'default'}
              icon={isOpen ? <UpOutlined /> : <DownOutlined />}
              onClick={(e) => {
                e.stopPropagation()
                setExpandedRowKeys((prev) => {
                  if (prev.includes(record.id)) {
                    return prev.filter((k) => k !== record.id)
                  }
                  loadPortFields(record)
                  return [...prev, record.id]
                })
              }}
            >
              {isOpen ? '收起' : `展开 ${count ?? 0} 字段`}
            </Button>
          )
        },
      },
    ]

    return [...base, ...extra]
  }

  const filterPorts = (list) => list.filter((p) => matchPortKeyword(p, portKeyword))

  const tabItems = DIRECTION_TABS.map((dir) => {
    const list = portsByDir[dir.key] || []
    const filtered = filterPorts(list)
    const columns = makePortColumns(list, dir.key)
    return {
      key: dir.key,
      label: (
        <Space>
          <span>{dir.icon}</span>
          <span>{dir.label}</span>
          <Badge count={list.length} showZero style={{ backgroundColor: '#52525b' }} />
        </Space>
      ),
      children: (
        <>
          <Space style={{ marginBottom: 10 }} wrap>
            <Input
              allowClear
              size="small"
              prefix={<SearchOutlined />}
              placeholder="搜索端口号 / 消息名称 / 设备 / 组播IP / 说明"
              value={portKeyword}
              onChange={(e) => setPortKeyword(e.target.value)}
              style={{ width: 340 }}
            />
            <Button
              size="small"
              icon={<UnorderedListOutlined />}
              onClick={() => {
                if (expandedRowKeys.length === filtered.length && filtered.length > 0) {
                  setExpandedRowKeys([])
                } else {
                  const keys = filtered.map((r) => r.id)
                  setExpandedRowKeys(keys)
                  filtered.forEach((p) => loadPortFields(p))
                }
              }}
            >
              {expandedRowKeys.length === filtered.length && filtered.length > 0 ? '全部收起' : '全部展开字段'}
            </Button>
            <Text type="secondary" style={{ fontSize: 12 }}>
              列头漏斗图标可筛选；只读视图，如需修改请创建草稿。
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              显示 {filtered.length} / 共 {list.length} 个端口
            </Text>
          </Space>
          <Table
            rowKey="id"
            size="small"
            dataSource={filtered}
            columns={columns}
            pagination={{ pageSize: 30, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
            scroll={{ x: 'max-content' }}
            expandable={{
              expandedRowKeys,
              onExpandedRowsChange: (keys) => {
                setExpandedRowKeys(keys)
                const newlyOpened = keys.filter((k) => !fieldCache[k]?.fields)
                newlyOpened.forEach((k) => {
                  const port = ports.find((p) => p.id === k)
                  if (port) loadPortFields(port)
                })
              },
              showExpandColumn: false,
              expandedRowRender: (record) => (
                <FieldSubTable
                  port={record}
                  fields={fieldCache[record.id]?.fields}
                  loading={fieldCache[record.id]?.loading}
                />
              ),
              rowExpandable: () => true,
            }}
          />
        </>
      ),
    }
  })

  const handleClone = async () => {
    try {
      const values = await cloneForm.validateFields()
      const res = await networkConfigApi.createDraftFromVersion({
        base_version_id: version.id,
        target_version: values.target_version,
        name: values.name,
        description: values.description,
      })
      message.success('已创建草稿')
      setCloneOpen(false)
      navigate(`/network-config/drafts/${res.data.id}`)
    } catch (err) {
      if (err?.errorFields) return
      message.error(err?.response?.data?.detail || '创建草稿失败')
    }
  }

  const openCloneModal = () => {
    cloneForm.resetFields()
    cloneForm.setFieldsValue({
      target_version: `${version.version}-draft`,
      name: `${version.protocol_name || ''} ${version.version} 迭代草稿`,
    })
    setCloneOpen(true)
  }

  const handleDeprecate = async () => {
    try {
      await networkConfigApi.deprecateVersion(version.id)
      message.success(`版本 ${version.version} 已置为 Deprecated`)
      loadAll()
    } catch (err) {
      message.error(err?.response?.data?.detail || '弃用失败')
    }
  }

  if (!version && loading) {
    return <div style={{ padding: 100, textAlign: 'center', color: '#a1a1aa' }}>加载中…</div>
  }
  if (!version) {
    return <Empty description="未找到该版本" />
  }

  const statusMeta = STATUS_META[version.availability_status] || { color: 'default', label: version.availability_status }
  const unknownPorts = version.ports_summary?.unknown_family_ports || []
  const isDeprecated = version.availability_status === 'Deprecated'

  const portCountTotal = version.ports_summary?.total ?? version.port_count ?? 0

  return (
    <div>
      <div className="page-hero" style={{ marginBottom: 16 }}>
        <Space style={{ marginBottom: 12 }}>
          <Button
            size="small"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/network-config')}
          >
            返回版本列表
          </Button>
        </Space>

        <div style={{
          display: 'flex',
          gap: 16,
          alignItems: 'flex-start',
          flexWrap: 'wrap',
        }}>
          <div style={{ flex: '1 1 360px', minWidth: 0 }}>
            <Space size={10} wrap>
              <h1 className="page-hero-title gradient-text">
                {version.protocol_name || '—'} <span style={{ color: '#c4b5fd' }}>{version.version}</span>
              </h1>
              <Tag color={statusMeta.color} icon={statusMeta.icon} style={{ fontSize: 12, padding: '2px 10px' }}>
                {statusMeta.label}
              </Tag>
              {version.availability_status === 'PendingCode' ? (
                <Tag color="gold" style={{ fontSize: 12, padding: '2px 10px' }}>
                  <span className="pulse-dot" style={{ marginRight: 6 }} />待激活
                </Tag>
              ) : null}
            </Space>
            {version.description ? (
              <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, maxWidth: 800 }}>
                {version.description}
              </Paragraph>
            ) : (
              <div className="page-hero-subtitle">#{version.id} · 端口总数 {portCountTotal}</div>
            )}
          </div>

          <Space wrap size={8}>
            <Button icon={<ReloadOutlined />} onClick={loadAll} loading={loading}>刷新</Button>
            {canWrite && !isDeprecated ? (
              <Button type="primary" icon={<BranchesOutlined />} onClick={openCloneModal}>
                基于此版本迭代
              </Button>
            ) : null}
            {canWrite && !isDeprecated ? (
              <Popconfirm
                title="确认弃用该版本？"
                description="弃用后，终端用户将无法再选择此版本进行解析；已绑定的历史任务不受影响。"
                okText="确认弃用"
                okButtonProps={{ danger: true }}
                cancelText="取消"
                onConfirm={handleDeprecate}
              >
                <Button danger icon={<StopOutlined />}>弃用</Button>
              </Popconfirm>
            ) : null}
          </Space>
        </div>

        <div className="kv-grid" style={{ marginTop: 16 }}>
          <div className="kv-row">
            <div className="kv-label">版本 ID</div>
            <div className="kv-value mono">#{version.id}</div>
          </div>
          <div className="kv-row">
            <div className="kv-label">端口总数</div>
            <div className="kv-value">{portCountTotal}</div>
          </div>
          <div className="kv-row">
            <div className="kv-label">来源文件</div>
            <div className="kv-value">{version.source_file || '—'}</div>
          </div>
          <div className="kv-row">
            <div className="kv-label">创建时间</div>
            <div className="kv-value">
              <Tooltip title={formatTime(version.created_at)}>
                {formatRelative(version.created_at) || formatTime(version.created_at)}
              </Tooltip>
            </div>
          </div>
          <div className="kv-row">
            <div className="kv-label">激活时间</div>
            <div className="kv-value">
              {version.activated_at ? (
                <Tooltip title={formatTime(version.activated_at)}>
                  <Space size={6} wrap>
                    <span>{formatRelative(version.activated_at)}</span>
                    {version.activated_by ? (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        by {version.activated_by}{version.forced_activation ? ' (强制)' : ''}
                      </Text>
                    ) : null}
                  </Space>
                </Tooltip>
              ) : <Text type="secondary">—</Text>}
            </div>
          </div>
        </div>
      </div>

      {unknownPorts.length > 0 ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`${unknownPorts.length} 个端口没有映射到任何协议族`}
          description={(
            <Text code style={{ wordBreak: 'break-all' }}>
              {unknownPorts.join(', ')}
            </Text>
          )}
        />
      ) : null}

      {version.availability_status !== 'PendingCode' ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="这是已发布协议版本的只读视图。如需修改请通过「基于此版本迭代」或从 ICD Excel 创建草稿。"
        />
      ) : null}

      {version.availability_status === 'PendingCode' ? (
        <Card
          title={(
            <Space>
              <ThunderboltFilled style={{ color: '#e3b959' }} />
              <span>激活闸门 · 就绪度体检</span>
              <Tag color="gold" style={{ marginLeft: 4 }}>
                <span className="pulse-dot" style={{ marginRight: 6 }} />待激活
              </Tag>
            </Space>
          )}
          style={{ marginBottom: 16 }}
        >
          <ActivationPanel
            version={version}
            canWrite={canWrite}
            isAdmin={isAdmin}
            onActivated={loadAll}
          />
        </Card>
      ) : null}

      <Card>
        <Tabs
          activeKey={activeDir}
          onChange={setActiveDir}
          items={tabItems}
        />
      </Card>

      <Modal
        title={`基于版本创建草稿：${version.protocol_name || ''} ${version.version}`}
        open={cloneOpen}
        onCancel={() => setCloneOpen(false)}
        onOk={handleClone}
        okText="创建草稿"
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="将完整复制此版本的端口与字段到一个新草稿；后续编辑不会影响原版本。"
        />
        <Form form={cloneForm} layout="vertical">
          <Form.Item
            label="目标版本号"
            name="target_version"
            rules={[{ required: true, message: '请填写目标版本号' }]}
            extra="即最终发布后在版本列表中显示的版本号，如 v2.1.0。"
          >
            <Input placeholder="例如 v2.1.0" />
          </Form.Item>
          <Form.Item
            label="草稿标题"
            name="name"
            rules={[{ required: true, message: '请填写草稿标题' }]}
          >
            <Input />
          </Form.Item>
          <Form.Item label="备注" name="description">
            <Input.TextArea rows={3} placeholder="本次迭代概述，可选" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default VersionViewerPage
