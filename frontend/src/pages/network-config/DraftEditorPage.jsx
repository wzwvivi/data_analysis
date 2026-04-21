import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
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
  CheckCircleOutlined,
  DownloadOutlined,
  PlusOutlined,
  ReloadOutlined,
  DeleteOutlined,
  SendOutlined,
  SafetyOutlined,
  WarningOutlined,
  CloseCircleOutlined,
  DiffOutlined,
  SearchOutlined,
  DownOutlined,
  UpOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import { networkConfigApi } from '../../services/api'
import {
  DIRECTION_TABS,
  ICD_COLUMN_SETS,
  buildFilters,
  matchPortKeyword,
} from './icdColumns'

const { Text, Title, Paragraph } = Typography

const DATA_TYPE_OPTIONS = [
  'uint8', 'uint16', 'uint32', 'uint64',
  'int8', 'int16', 'int32', 'int64',
  'float32', 'float64', 'bytes', 'string',
].map((t) => ({ value: t, label: t }))

// 端口角色（ICD 维度，用于事件分析模块按角色筛端口）
// - fcc_event 作为聚合角色保留兼容，实际建议用细粒度 fcc_status/channel/fault
// - irs_input 供自动飞行分析解析 IRS 竖向速度/加速度
const PORT_ROLE_OPTIONS = [
  { value: 'tsn_anomaly', label: 'TSN 异常检查' },
  { value: 'fms_event',   label: '飞管事件分析' },
  { value: 'fcc_status',  label: '飞控事件分析 · 状态帧' },
  { value: 'fcc_channel', label: '飞控事件分析 · 通道选择' },
  { value: 'fcc_fault',   label: '飞控事件分析 · 故障码' },
  { value: 'fcc_event',   label: '飞控事件分析（聚合）' },
  { value: 'auto_flight', label: '自动飞行分析' },
  { value: 'irs_input',   label: '自动飞行分析 · IRS 输入' },
  { value: 'other',       label: '其它 / 未分类' },
]
const PORT_ROLE_LABELS = Object.fromEntries(PORT_ROLE_OPTIONS.map((o) => [o.value, o.label]))

const BYTE_ORDER_OPTIONS = [
  { value: 'big', label: 'big' },
  { value: 'little', label: 'little' },
]

const STATUS_META = {
  draft: { color: 'default', label: '草稿（可编辑）' },
  pending: { color: 'processing', label: '审批中' },
  rejected: { color: 'error', label: '已驳回' },
  approved: { color: 'warning', label: '已通过（待发布）' },
  published: { color: 'success', label: '已发布' },
}

/** 可编辑单元格（行内编辑） */
function EditableCell({ editing, dataIndex, inputType, children, record, options, onSave, ...restProps }) {
  const isNumber = inputType === 'number'
  const isSelect = inputType === 'select'

  if (!editing) return <td {...restProps}>{children}</td>

  const handleSave = async (val) => {
    await onSave(record, dataIndex, val)
  }

  let node
  if (isNumber) {
    node = (
      <InputNumber
        defaultValue={record[dataIndex]}
        style={{ width: '100%' }}
        onBlur={(e) => handleSave(e.target.value === '' ? null : Number(e.target.value))}
      />
    )
  } else if (isSelect) {
    node = (
      <Select
        defaultValue={record[dataIndex]}
        options={options || []}
        style={{ width: '100%' }}
        onChange={(v) => handleSave(v)}
        allowClear
      />
    )
  } else {
    node = (
      <Input
        defaultValue={record[dataIndex]}
        onBlur={(e) => handleSave(e.target.value)}
      />
    )
  }
  return <td {...restProps}>{node}</td>
}

function FieldSubTable({ draftId, port, readOnly, onAfterChange, errorKeys }) {
  const [editingKey, setEditingKey] = useState(null)
  const [addOpen, setAddOpen] = useState(false)
  const [addForm] = Form.useForm()

  const handleCellSave = async (record, dataIndex, value) => {
    try {
      const body = { [dataIndex]: value }
      if (['field_offset', 'field_length'].includes(dataIndex)) {
        body[dataIndex] = value == null ? null : Number(value)
      }
      if (dataIndex === 'scale_factor') {
        body[dataIndex] = value == null ? null : Number(value)
      }
      await networkConfigApi.updateField(draftId, port.id, record.id, body)
      message.success('已保存', 0.8)
      onAfterChange()
    } catch (err) {
      message.error(err?.response?.data?.detail || '保存失败')
    } finally {
      setEditingKey(null)
    }
  }

  const handleDelete = async (record) => {
    try {
      await networkConfigApi.deleteField(draftId, port.id, record.id)
      message.success('已删除')
      onAfterChange()
    } catch (err) {
      message.error(err?.response?.data?.detail || '删除失败')
    }
  }

  const handleAdd = async () => {
    try {
      const values = await addForm.validateFields()
      await networkConfigApi.addField(draftId, port.id, values)
      message.success('已新增字段')
      setAddOpen(false)
      addForm.resetFields()
      onAfterChange()
    } catch (err) {
      if (err?.errorFields) return
      message.error(err?.response?.data?.detail || '新增失败')
    }
  }

  const fieldRows = port.fields || []
  const buildFieldFilters = (key) => {
    const set = new Set()
    for (const r of fieldRows) {
      const v = r?.[key]
      if (v !== null && v !== undefined && String(v) !== '') set.add(String(v))
    }
    return Array.from(set)
      .sort((a, b) => a.localeCompare(b, 'zh-Hans', { numeric: true }))
      .map((v) => ({ text: v, value: v }))
  }

  const fieldColumns = useMemo(() => {
    // ICD 字段级原表头：消息内数据集 / 消息内偏移 / 长度
    // 其它列（数据类型/字节序/系数/单位/说明）为平台解析扩展
    const base = [
      {
        title: '消息内数据集',
        dataIndex: 'field_name',
        editable: true,
        width: 220,
        filters: buildFieldFilters('field_name'),
        filterSearch: true,
        onFilter: (value, record) => (record.field_name || '') === value,
      },
      {
        title: '消息内偏移',
        dataIndex: 'field_offset',
        editable: true,
        inputType: 'number',
        width: 110,
        sorter: (a, b) => (a.field_offset ?? 0) - (b.field_offset ?? 0),
        defaultSortOrder: 'ascend',
      },
      {
        title: '长度',
        dataIndex: 'field_length',
        editable: true,
        inputType: 'number',
        width: 90,
        sorter: (a, b) => (a.field_length ?? 0) - (b.field_length ?? 0),
      },
      {
        title: <Tooltip title="平台解析扩展列，非 ICD 原表头">数据类型 <span style={{ color: '#a1a1aa' }}>*</span></Tooltip>,
        dataIndex: 'data_type',
        editable: true,
        inputType: 'select',
        options: DATA_TYPE_OPTIONS,
        width: 110,
        filters: buildFieldFilters('data_type'),
        onFilter: (value, record) => (record.data_type || '') === value,
      },
      {
        title: <Tooltip title="平台解析扩展列，非 ICD 原表头">字节序 <span style={{ color: '#a1a1aa' }}>*</span></Tooltip>,
        dataIndex: 'byte_order',
        editable: true,
        inputType: 'select',
        options: BYTE_ORDER_OPTIONS,
        width: 90,
        filters: buildFieldFilters('byte_order'),
        onFilter: (value, record) => (record.byte_order || '') === value,
      },
      {
        title: <Tooltip title="平台解析扩展列，非 ICD 原表头">系数 <span style={{ color: '#a1a1aa' }}>*</span></Tooltip>,
        dataIndex: 'scale_factor',
        editable: true,
        inputType: 'number',
        width: 80,
      },
      {
        title: <Tooltip title="平台解析扩展列，非 ICD 原表头">单位 <span style={{ color: '#a1a1aa' }}>*</span></Tooltip>,
        dataIndex: 'unit',
        editable: true,
        width: 80,
        filters: buildFieldFilters('unit'),
        filterSearch: true,
        onFilter: (value, record) => (record.unit || '') === value,
      },
      {
        title: <Tooltip title="平台解析扩展列，非 ICD 原表头">说明 <span style={{ color: '#a1a1aa' }}>*</span></Tooltip>,
        dataIndex: 'description',
        editable: true,
        ellipsis: true,
      },
      !readOnly && {
        title: '操作',
        width: 60,
        render: (_, record) => (
          <Popconfirm title="删除此字段？" onConfirm={() => handleDelete(record)}>
            <Button size="small" type="link" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        ),
      },
    ].filter(Boolean)
    return base.map((col) => ({
      ...col,
      onCell: col.editable ? (record) => ({
        record,
        editing: !readOnly && editingKey === `${record.id}|${col.dataIndex}`,
        dataIndex: col.dataIndex,
        inputType: col.inputType || 'text',
        options: col.options,
        onSave: handleCellSave,
        onClick: () => {
          if (!readOnly) setEditingKey(`${record.id}|${col.dataIndex}`)
        },
      }) : undefined,
    }))
  }, [editingKey, readOnly, fieldRows])

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
        <Tag color="default">共 {fieldRows.length} 个字段</Tag>
        {!readOnly && (
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
            新增字段
          </Button>
        )}
        <Text type="secondary" style={{ fontSize: 12 }}>点击单元格激活编辑，失焦保存。</Text>
      </Space>
      <Table
        rowKey="id"
        size="small"
        dataSource={fieldRows}
        columns={fieldColumns}
        pagination={false}
        components={{ body: { cell: EditableCell } }}
        rowClassName={(r) => errorKeys?.has(`${port.port_number}|${r.field_name}`) ? 'draft-error-row' : ''}
      />
      <Modal
        title="新增字段"
        open={addOpen}
        onCancel={() => setAddOpen(false)}
        onOk={handleAdd}
        okText="保存"
        cancelText="取消"
      >
        <Form form={addForm} layout="vertical">
          <Form.Item name="field_name" label="字段名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="field_offset" label="偏移 (Byte)" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} min={0} />
          </Form.Item>
          <Form.Item name="field_length" label="长度 (Byte)" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} min={1} />
          </Form.Item>
          <Form.Item name="data_type" label="数据类型" initialValue="bytes">
            <Select options={DATA_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="byte_order" label="字节序" initialValue="big">
            <Select options={BYTE_ORDER_OPTIONS} />
          </Form.Item>
          <Form.Item name="scale_factor" label="系数" initialValue={1.0}>
            <InputNumber style={{ width: '100%' }} step={0.01} />
          </Form.Item>
          <Form.Item name="unit" label="单位"><Input /></Form.Item>
          <Form.Item name="description" label="说明"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

function DraftEditorPage() {
  const { id: draftId } = useParams()
  const navigate = useNavigate()

  const [loading, setLoading] = useState(false)
  const [draft, setDraft] = useState(null)
  const [activeDir, setActiveDir] = useState('uplink')
  const [familyOptions, setFamilyOptions] = useState([])
  const [editingCellKey, setEditingCellKey] = useState(null)

  const [checkResult, setCheckResult] = useState(null)
  const [checkLoading, setCheckLoading] = useState(false)
  const [diffResult, setDiffResult] = useState(null)
  const [sidePanelOpen, setSidePanelOpen] = useState(false)
  const [sidePanelTab, setSidePanelTab] = useState('check')

  const [addPortOpen, setAddPortOpen] = useState(false)
  const [addPortForm] = Form.useForm()
  const [submitOpen, setSubmitOpen] = useState(false)
  const [submitForm] = Form.useForm()

  // 全局搜索（按端口号 / 消息名称 / 设备名 / 组播 IP 模糊匹配）
  const [portKeyword, setPortKeyword] = useState('')
  const [expandedRowKeys, setExpandedRowKeys] = useState([])

  const loadDraft = useCallback(async () => {
    setLoading(true)
    try {
      const res = await networkConfigApi.getDraft(draftId)
      setDraft(res.data)
    } catch (err) {
      message.error(err?.response?.data?.detail || '加载草稿失败')
    } finally {
      setLoading(false)
    }
  }, [draftId])

  const loadFamilies = useCallback(async () => {
    try {
      const res = await networkConfigApi.listParserFamilies()
      const items = res.data?.items || []
      setFamilyOptions(items.map((it) => ({ value: it.family, label: it.family })))
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    loadDraft()
    loadFamilies()
  }, [loadDraft, loadFamilies])

  const readOnly = draft?.status !== 'draft'
  const portsByDir = useMemo(() => {
    const map = { uplink: [], downlink: [], network: [] }
    for (const p of draft?.ports || []) {
      const dir = (p.data_direction || 'network').toLowerCase()
      ;(map[dir] || map.network).push(p)
    }
    return map
  }, [draft])

  const errorKeys = useMemo(() => {
    const fk = new Set()
    for (const issue of checkResult?.errors || []) {
      if (issue.port_number && issue.field_name) {
        fk.add(`${issue.port_number}|${issue.field_name}`)
      }
    }
    return fk
  }, [checkResult])

  const errorPortNumbers = useMemo(() => {
    const s = new Set()
    for (const issue of checkResult?.errors || []) {
      if (issue.port_number) s.add(issue.port_number)
    }
    return s
  }, [checkResult])

  const handlePortCellSave = async (record, dataIndex, value) => {
    try {
      let body = { [dataIndex]: value }
      if (dataIndex === 'port_number') body[dataIndex] = Number(value)
      if (dataIndex === 'period_ms') body[dataIndex] = value == null || value === '' ? null : Number(value)
      await networkConfigApi.updatePort(draftId, record.id, body)
      message.success('已保存', 0.8)
      loadDraft()
    } catch (err) {
      message.error(err?.response?.data?.detail || '保存失败')
    } finally {
      setEditingCellKey(null)
    }
  }

  const handleDeletePort = async (record) => {
    try {
      await networkConfigApi.deletePort(draftId, record.id)
      message.success('已删除')
      loadDraft()
    } catch (err) {
      message.error(err?.response?.data?.detail || '删除失败')
    }
  }

  const handleAddPort = async () => {
    try {
      const values = await addPortForm.validateFields()
      await networkConfigApi.addPort(draftId, { ...values, data_direction: activeDir })
      message.success('已新增端口')
      setAddPortOpen(false)
      addPortForm.resetFields()
      loadDraft()
    } catch (err) {
      if (err?.errorFields) return
      message.error(err?.response?.data?.detail || '新增失败')
    }
  }

  const runCheck = async () => {
    setCheckLoading(true)
    try {
      const res = await networkConfigApi.checkDraft(draftId)
      setCheckResult(res.data)
      setSidePanelTab('check')
      setSidePanelOpen(true)
      const { summary } = res.data
      if (summary.error_count > 0) {
        message.warning(`静态检查：${summary.error_count} 个 error，${summary.warning_count} 个 warning`)
      } else {
        message.success(`静态检查通过，${summary.warning_count} 个 warning`)
      }
    } catch (err) {
      message.error(err?.response?.data?.detail || '静态检查失败')
    } finally {
      setCheckLoading(false)
    }
  }

  const runDiff = async () => {
    try {
      const res = await networkConfigApi.getDraftDiff(draftId)
      setDiffResult(res.data)
      setSidePanelTab('diff')
      setSidePanelOpen(true)
    } catch (err) {
      message.error(err?.response?.data?.detail || '加载 diff 失败')
    }
  }

  const exportExcel = async () => {
    try {
      const res = await networkConfigApi.exportDraftExcel(draftId)
      const blob = new Blob([res.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const match = /filename\*=UTF-8''([^;]+)/.exec(res.headers?.['content-disposition'] || '')
      a.download = match ? decodeURIComponent(match[1]) : `draft_${draftId}.xlsx`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      message.error(err?.response?.data?.detail || '导出失败')
    }
  }

  const submitDraft = async () => {
    try {
      const values = await submitForm.validateFields()
      const res = await networkConfigApi.submitDraft(draftId, values)
      message.success('已提交审批')
      setSubmitOpen(false)
      submitForm.resetFields()
      navigate(`/network-config/change-requests/${res.data.id}`)
    } catch (err) {
      if (err?.errorFields) return
      message.error(err?.response?.data?.detail || '提交失败')
    }
  }

  // 列定义严格对齐 ICD 6.0.x 原表头（ICD_COLUMN_SETS / DIRECTION_TABS / buildFilters 已抽到 ./icdColumns 与只读视图共享）

  const makePortColumns = (rowsForDir, dirKey) => {
    const icdCols = ICD_COLUMN_SETS[dirKey] || ICD_COLUMN_SETS.uplink
    const base = icdCols.map((c) => {
      const col = {
        title: c.title,
        dataIndex: c.dataIndex,
        width: c.width,
        editable: true,
        inputType: c.inputType,
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
        col.render = (v) => (
          <Space>
            <Text strong>{v}</Text>
            {errorPortNumbers.has(v) && (
              <Tooltip title="此端口存在静态检查 error">
                <CloseCircleOutlined style={{ color: '#f5222d' }} />
              </Tooltip>
            )}
          </Space>
        )
      }
      return col
    })

    // 平台专属扩展（非 ICD 表头）：协议族 + 端口角色 + 字段详情 + 操作；放最右侧
    const extra = [
      {
        title: '协议族（平台扩展）',
        dataIndex: 'protocol_family',
        editable: true,
        inputType: 'select',
        options: familyOptions,
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
        editable: true,
        inputType: 'select',
        options: PORT_ROLE_OPTIONS,
        width: 140,
        filters: PORT_ROLE_OPTIONS.map((o) => ({ text: o.label, value: o.value })),
        onFilter: (value, record) => (record.port_role || '') === value,
        render: (v) => v
          ? <Tag color="geekblue">{PORT_ROLE_LABELS[v] || v}</Tag>
          : <Tag color="default">未指定</Tag>,
      },
      {
        title: '字段详情',
        dataIndex: 'field_count',
        width: 150,
        align: 'center',
        editable: false,
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
                setExpandedRowKeys((prev) =>
                  prev.includes(record.id)
                    ? prev.filter((k) => k !== record.id)
                    : [...prev, record.id]
                )
              }}
            >
              {isOpen ? '收起' : `展开 ${count ?? 0} 字段`}
            </Button>
          )
        },
      },
      !readOnly && {
        title: '操作',
        width: 70,
        fixed: 'right',
        render: (_, record) => (
          <Popconfirm title="删除此端口及其所有字段？" onConfirm={() => handleDeletePort(record)}>
            <Button size="small" type="link" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        ),
      },
    ].filter(Boolean)

    const all = [...base, ...extra]
    return all.map((col) => ({
      ...col,
      onCell: col.editable ? (record) => ({
        record,
        editing: !readOnly && editingCellKey === `${record.id}|${col.dataIndex}`,
        dataIndex: col.dataIndex,
        inputType: col.inputType || 'text',
        options: col.options,
        onSave: handlePortCellSave,
        onClick: () => {
          if (!readOnly) setEditingCellKey(`${record.id}|${col.dataIndex}`)
        },
      }) : undefined,
    }))
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
            {!readOnly && (
              <Button icon={<PlusOutlined />} size="small" onClick={() => setAddPortOpen(true)}>
                新增端口（{dir.label}）
              </Button>
            )}
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
                if (expandedRowKeys.length === filtered.length) {
                  setExpandedRowKeys([])
                } else {
                  setExpandedRowKeys(filtered.map((r) => r.id))
                }
              }}
            >
              {expandedRowKeys.length === filtered.length && filtered.length > 0 ? '全部收起' : '全部展开字段'}
            </Button>
            <Text type="secondary" style={{ fontSize: 12 }}>
              列头漏斗图标可筛选；点击单元格即可编辑，失焦保存。
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
            components={{ body: { cell: EditableCell } }}
            scroll={{ x: 'max-content' }}
            expandable={{
              expandedRowKeys,
              onExpandedRowsChange: (keys) => setExpandedRowKeys(keys),
              showExpandColumn: false,
              expandedRowRender: (record) => (
                <FieldSubTable
                  draftId={draftId}
                  port={record}
                  readOnly={readOnly}
                  onAfterChange={loadDraft}
                  errorKeys={errorKeys}
                />
              ),
              rowExpandable: () => true,
            }}
            rowClassName={(r) => errorPortNumbers.has(r.port_number) ? 'draft-error-row' : ''}
          />
        </>
      ),
    }
  })

  if (!draft && loading) {
    return <div style={{ padding: 100, textAlign: 'center', color: '#a1a1aa' }}>加载中…</div>
  }
  if (!draft) {
    return <Empty description="未找到该草稿" />
  }

  const statusMeta = STATUS_META[draft.status] || { color: 'default', label: draft.status }

  return (
    <div>
      <style>{`
        .draft-error-row > td { background-color: rgba(245, 34, 45, 0.08) !important; }
      `}</style>
      <Card style={{ marginBottom: 16 }}>
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Space wrap size="middle">
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/network-config')}>
              返回
            </Button>
            <Title level={4} style={{ margin: 0 }}>
              {draft.name}
            </Title>
            <Tag color={statusMeta.color}>{statusMeta.label}</Tag>
            <Text type="secondary">目标版本 v{draft.target_version}</Text>
            <Text type="secondary">创建人 {draft.created_by || '-'}</Text>
          </Space>
          <Descriptions size="small" column={4}>
            <Descriptions.Item label="来源">
              {draft.source_type === 'clone' ? `克隆自版本 #${draft.base_version_id}` : `Excel 导入（新架次）`}
            </Descriptions.Item>
            <Descriptions.Item label="端口总数">{draft.port_count}</Descriptions.Item>
            <Descriptions.Item label="协议 ID">{draft.protocol_id}</Descriptions.Item>
            <Descriptions.Item label="最后更新">{draft.updated_at ? String(draft.updated_at) : '-'}</Descriptions.Item>
          </Descriptions>
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={loadDraft}>刷新</Button>
            <Button icon={<SafetyOutlined />} onClick={runCheck} loading={checkLoading}>静态检查</Button>
            <Button icon={<DiffOutlined />} onClick={runDiff}>查看 Diff</Button>
            <Button icon={<DownloadOutlined />} onClick={exportExcel}>导出 Excel</Button>
            {!readOnly && (
              <Button type="primary" icon={<SendOutlined />} onClick={() => setSubmitOpen(true)}>
                提交审批
              </Button>
            )}
          </Space>
          {readOnly && (
            <Alert
              type="info"
              showIcon
              message={`该草稿当前状态为「${statusMeta.label}」，只读。`}
            />
          )}
        </Space>
      </Card>

      <Card>
        <Tabs
          activeKey={activeDir}
          onChange={setActiveDir}
          items={tabItems}
        />
      </Card>

      <Modal
        title="新增端口"
        open={addPortOpen}
        onOk={handleAddPort}
        onCancel={() => setAddPortOpen(false)}
        okText="保存"
        cancelText="取消"
      >
        <Form form={addPortForm} layout="vertical">
          <Form.Item name="port_number" label="UDP端口" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} min={1} max={65535} />
          </Form.Item>
          <Form.Item name="message_name" label="消息名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="source_device" label="消息源设备名称 / 待转换TSN源端"><Input /></Form.Item>
          <Form.Item name="target_device" label="DataSet目的端设备名称 / 消息目的设备"><Input /></Form.Item>
          <Form.Item name="multicast_ip" label="组播组IP"><Input /></Form.Item>
          <Form.Item name="period_ms" label="消息周期(ms)">
            <InputNumber style={{ width: '100%' }} min={0} />
          </Form.Item>
          <Form.Item name="description" label="备注"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="protocol_family" label="协议族（平台扩展）">
            <Select options={familyOptions} allowClear showSearch />
          </Form.Item>
          <Form.Item name="port_role" label="端口角色（事件分析模块按角色筛端口）">
            <Select options={PORT_ROLE_OPTIONS} allowClear showSearch />
          </Form.Item>
          <Divider plain style={{ fontSize: 12 }}>ICD 扩展（可选）</Divider>
          <Form.Item name="message_id" label="消息编号"><Input /></Form.Item>
          <Form.Item name="source_interface_id" label="消息源端接口编号（上行/网络）"><Input /></Form.Item>
          <Form.Item name="port_id_label" label="PortID（上行/网络）"><Input /></Form.Item>
          <Form.Item name="diu_id" label="DIU编号"><Input /></Form.Item>
          <Form.Item name="diu_id_set" label="DIU编号集合（下行）"><Input /></Form.Item>
          <Form.Item name="diu_recv_mode" label="DIU消息接收形式（下行）"><Input /></Form.Item>
          <Form.Item name="tsn_source_ip" label="TSN消息源端IP（下行）"><Input /></Form.Item>
          <Form.Item name="diu_ip" label="承接转换的DIU IP（下行）"><Input /></Form.Item>
          <Form.Item name="dataset_path" label="DataSet传递路径（下行）"><Input /></Form.Item>
          <Form.Item name="data_real_path" label="数据实际路径（下行）"><Input /></Form.Item>
          <Form.Item name="final_recv_device" label="最终接收端设备（下行）"><Input /></Form.Item>
        </Form>
      </Modal>

      <Modal
        title="提交审批"
        open={submitOpen}
        onOk={submitDraft}
        onCancel={() => setSubmitOpen(false)}
        okText="提交"
        cancelText="取消"
      >
        <Paragraph type="secondary">
          提交后仅需 <Text strong>管理员审批</Text>；审批通过后版本进入 PendingCode，
          等待管理员激活。期间草稿将被锁定不可编辑，驳回后可重新编辑。
        </Paragraph>
        <Form form={submitForm} layout="vertical" initialValues={{ notify_teams: [] }}>
          <Form.Item name="note" label="提交说明（可选）">
            <Input.TextArea rows={4} placeholder="本次修改概要 / 原因 / 影响面" />
          </Form.Item>
          <Form.Item
            name="notify_teams"
            label="激活后通知团队（可选，可多选）"
            tooltip="版本被管理员激活时，相应团队会收到站内通知；提交/审批过程不打扰"
          >
            <Checkbox.Group
              options={[
                { label: '飞管团队', value: 'fms' },
                { label: '飞控团队', value: 'fcc' },
                { label: 'TSN / 网络团队', value: 'tsn' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={sidePanelTab === 'check' ? '静态检查' : '与基础版本 Diff'}
        width={560}
        open={sidePanelOpen}
        onClose={() => setSidePanelOpen(false)}
      >
        <Tabs
          activeKey={sidePanelTab}
          onChange={setSidePanelTab}
          items={[
            {
              key: 'check',
              label: '静态检查',
              children: <CheckPanel result={checkResult} />,
            },
            {
              key: 'diff',
              label: 'Diff',
              children: <DiffPanel result={diffResult} />,
            },
          ]}
        />
      </Drawer>
    </div>
  )
}

function CheckPanel({ result }) {
  if (!result) return <Empty description="尚未运行静态检查" />
  const { summary, errors = [], warnings = [] } = result
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Alert
        type={summary.can_submit ? 'success' : 'error'}
        showIcon
        icon={summary.can_submit ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
        message={
          summary.can_submit
            ? `通过（${summary.warning_count} 个 warning）`
            : `未通过：${summary.error_count} 个 error / ${summary.warning_count} 个 warning`
        }
        description={`共 ${summary.port_count} 端口，${summary.field_count} 字段`}
      />
      {errors.length > 0 && (
        <Card size="small" title={`错误 (${errors.length})`}>
          {errors.map((e, idx) => (
            <div key={idx} style={{ marginBottom: 8 }}>
              <Tag color="red">{e.code}</Tag>
              <Text>{e.message}</Text>
              {e.port_number != null && <Text type="secondary"> · 端口 {e.port_number}</Text>}
              {e.field_name && <Text type="secondary"> · 字段 {e.field_name}</Text>}
            </div>
          ))}
        </Card>
      )}
      {warnings.length > 0 && (
        <Card size="small" title={`警告 (${warnings.length})`}>
          {warnings.map((w, idx) => (
            <div key={idx} style={{ marginBottom: 8 }}>
              <Tag color="orange" icon={<WarningOutlined />}>{w.code}</Tag>
              <Text>{w.message}</Text>
              {w.port_number != null && <Text type="secondary"> · 端口 {w.port_number}</Text>}
              {w.field_name && <Text type="secondary"> · 字段 {w.field_name}</Text>}
            </div>
          ))}
        </Card>
      )}
    </Space>
  )
}

function DiffPanel({ result }) {
  if (!result) return <Empty description="尚未运行 diff" />
  const {
    ports_added = [],
    ports_removed = [],
    ports_property_changed = [],
    fields_added = [],
    fields_removed = [],
    fields_changed = [],
  } = result
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small" title={`端口新增 (${ports_added.length})`}>
        {ports_added.length === 0 ? <Text type="secondary">无</Text> : (
          <Space size={[4, 4]} wrap>
            {ports_added.map((p) => <Tag color="green" key={p.port_number}>{p.port_number} / {p.message_name}</Tag>)}
          </Space>
        )}
      </Card>
      <Card size="small" title={`端口删除 (${ports_removed.length})`}>
        {ports_removed.length === 0 ? <Text type="secondary">无</Text> : (
          <Space size={[4, 4]} wrap>
            {ports_removed.map((p) => <Tag color="red" key={p.port_number}>{p.port_number} / {p.message_name}</Tag>)}
          </Space>
        )}
      </Card>
      <Card size="small" title={`端口属性变更 (${ports_property_changed.length})`}>
        {ports_property_changed.length === 0 ? <Text type="secondary">无</Text> : ports_property_changed.map((c) => (
          <div key={c.port_number} style={{ marginBottom: 6 }}>
            <Tag>{c.port_number}</Tag>
            {Object.entries(c.changes || {}).map(([k, v]) => (
              <Text key={k} type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                {k}: <Text delete>{String(v.old ?? '')}</Text> → <Text code>{String(v.new ?? '')}</Text>
              </Text>
            ))}
          </div>
        ))}
      </Card>
      <Card size="small" title={`字段新增 (${fields_added.length}) / 删除 (${fields_removed.length}) / 变更 (${fields_changed.length})`}>
        <Paragraph type="secondary" style={{ marginBottom: 4 }}>
          新增：{fields_added.map((f) => `${f.port_number}·${f.field_name}`).join(', ') || '无'}
        </Paragraph>
        <Paragraph type="secondary" style={{ marginBottom: 4 }}>
          删除：{fields_removed.map((f) => `${f.port_number}·${f.field_name}`).join(', ') || '无'}
        </Paragraph>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          变更：{fields_changed.length === 0 ? '无' : fields_changed.map((c) => (
            `${c.port_number}·${c.field_name}`
          )).join(', ')}
        </Paragraph>
      </Card>
    </Space>
  )
}

export default DraftEditorPage
