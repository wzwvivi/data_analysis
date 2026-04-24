import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd'
import {
  ApartmentOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { configurationApi } from '../services/api'
import dayjs from 'dayjs'
import AppPageHeader from '../components/AppPageHeader'

const { Text } = Typography

// ══════════════════════════ 设备库 ══════════════════════════
function DeviceLibraryPanel() {
  const [rows, setRows] = useState([])
  const [teams, setTeams] = useState([])
  const [loading, setLoading] = useState(false)
  const [teamFilter, setTeamFilter] = useState(null)
  const [keyword, setKeyword] = useState('')
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = {}
      if (teamFilter) params.team = teamFilter
      if (keyword.trim()) params.q = keyword.trim()
      const [rRes, tRes] = await Promise.all([
        configurationApi.listDevices(params),
        configurationApi.listDeviceTeams(),
      ])
      setRows(rRes.data || [])
      setTeams(tRes.data || [])
    } catch (e) {
      message.error(e?.response?.data?.detail || '加载设备失败')
    } finally {
      setLoading(false)
    }
  }, [teamFilter, keyword])

  useEffect(() => {
    load()
  }, [load])

  const openCreate = () => {
    setEditing({})
    form.resetFields()
    form.setFieldsValue({ team: teamFilter || '', has_software: true })
  }

  const openEdit = (row) => {
    setEditing(row)
    form.setFieldsValue(row)
  }

  const submit = async () => {
    try {
      const v = await form.validateFields()
      if (editing?.id) {
        await configurationApi.updateDevice(editing.id, v)
        message.success('设备已更新')
      } else {
        await configurationApi.createDevice(v)
        message.success('设备已创建')
      }
      setEditing(null)
      load()
    } catch (e) {
      if (e?.errorFields) return
      message.error(e?.response?.data?.detail || '保存失败')
    }
  }

  const remove = async (row) => {
    try {
      await configurationApi.deleteDevice(row.id)
      message.success('已删除')
      load()
    } catch (e) {
      message.error(e?.response?.data?.detail || '删除失败')
    }
  }

  const renderBool = (v) => {
    if (v === true) return <Tag color="green">是</Tag>
    if (v === false) return <Tag>否</Tag>
    return <Tag color="default">—</Tag>
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '团队', dataIndex: 'team', width: 130 },
    { title: 'EATA 章节', dataIndex: 'eata_chapter', width: 200, ellipsis: true },
    { title: '设备名称', dataIndex: 'device_cn_name', width: 180 },
    { title: 'DM 号', dataIndex: 'device_dm_number', width: 160 },
    { title: '软件名称', dataIndex: 'software_cn_name', width: 220, ellipsis: true },
    { title: '等级', dataIndex: 'software_level', width: 70 },
    { title: '自研', dataIndex: 'is_proprietary', width: 80, render: renderBool },
    { title: '新研', dataIndex: 'is_new_dev', width: 80, render: renderBool },
    { title: '外场可加载', dataIndex: 'is_field_loadable', width: 110, render: renderBool },
    { title: '供应商', dataIndex: 'supplier', width: 160, ellipsis: true },
    {
      title: '操作',
      key: 'op',
      width: 160,
      fixed: 'right',
      render: (_, r) => (
        <Space>
          <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(r)}>
            编辑
          </Button>
          <Popconfirm title="确定删除该设备？（关联的软件构型条目会同步删除）" onConfirm={() => remove(r)}>
            <Button size="small" type="link" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          allowClear
          placeholder="按团队筛选"
          style={{ width: 200 }}
          value={teamFilter}
          onChange={setTeamFilter}
          options={teams.map((t) => ({ value: t, label: t }))}
        />
        <Input.Search
          placeholder="关键字：设备/软件/DM号/EATA"
          allowClear
          style={{ width: 320 }}
          onSearch={(v) => setKeyword(v || '')}
        />
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建设备</Button>
      </Space>
      <Table
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={rows}
        loading={loading}
        pagination={{ pageSize: 20, showSizeChanger: true }}
        scroll={{ x: 1600 }}
      />

      <Modal
        title={editing?.id ? '编辑设备' : '新建设备'}
        open={!!editing}
        onCancel={() => setEditing(null)}
        onOk={submit}
        width={720}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
            <Form.Item name="team" label="团队" rules={[{ required: true }]}>
              <Input placeholder="如 电推进团队" />
            </Form.Item>
            <Form.Item name="eata_chapter" label="EATA 章节">
              <Input placeholder="如 EATA86 电推进系统" />
            </Form.Item>
            <Form.Item name="device_cn_name" label="设备名称" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="device_dm_number" label="DM 号">
              <Input />
            </Form.Item>
            <Form.Item name="software_cn_name" label="软件名称" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="software_level" label="软件等级">
              <Select allowClear options={['A', 'B', 'C', 'NA'].map((v) => ({ value: v, label: v }))} />
            </Form.Item>
            <Form.Item name="supplier" label="供应商">
              <Input />
            </Form.Item>
            <Form.Item name="is_cds_resident" label="显控驻留" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="is_field_loadable" label="外场可加载" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="is_proprietary" label="自研软件" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="is_new_dev" label="新研软件" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="has_software" label="有软件" valuePropName="checked">
              <Switch />
            </Form.Item>
          </div>
          <Form.Item name="remarks" label="备注">
            <Input.TextArea rows={2} maxLength={500} showCount />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ══════════════════════════ 飞机构型 ══════════════════════════
function AircraftConfigPanel() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [tsnOptions, setTsnOptions] = useState([])
  const [devOptions, setDevOptions] = useState([])
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()
  const [detail, setDetail] = useState(null)

  const loadOptions = useCallback(async () => {
    try {
      const [tsnRes, devRes] = await Promise.all([
        configurationApi.listTsnProtocolVersionOptions(),
        configurationApi.listDeviceProtocolVersionOptions(),
      ])
      setTsnOptions(tsnRes.data || [])
      setDevOptions(devRes.data || [])
    } catch {
      // ignore
    }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await configurationApi.listAircraftConfigs()
      setRows(r.data || [])
    } catch (e) {
      message.error(e?.response?.data?.detail || '加载飞机构型失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    loadOptions()
  }, [load, loadOptions])

  const openCreate = () => {
    setEditing({})
    form.resetFields()
  }

  const openEdit = (row) => {
    setEditing(row)
    form.setFieldsValue({
      name: row.name,
      version: row.version,
      description: row.description,
      tsn_protocol_version_id: row.tsn_protocol_version_id,
      device_protocol_version_ids: row.device_protocol_version_ids || [],
    })
  }

  const submit = async () => {
    try {
      const v = await form.validateFields()
      if (editing?.id) {
        await configurationApi.updateAircraftConfig(editing.id, v)
        message.success('飞机构型已更新')
      } else {
        await configurationApi.createAircraftConfig(v)
        message.success('飞机构型已创建')
      }
      setEditing(null)
      load()
    } catch (e) {
      if (e?.errorFields) return
      message.error(e?.response?.data?.detail || '保存失败')
    }
  }

  const remove = async (row) => {
    try {
      await configurationApi.deleteAircraftConfig(row.id)
      message.success('已删除')
      load()
    } catch (e) {
      message.error(e?.response?.data?.detail || '删除失败')
    }
  }

  const devOptionItems = useMemo(
    () => devOptions.map((o) => ({ value: o.id, label: o.label })),
    [devOptions],
  )

  const columns = [
    { title: '名称', dataIndex: 'name', width: 240 },
    { title: '版本', dataIndex: 'version', width: 100, render: (v) => v || '—' },
    {
      title: 'TSN 协议版本',
      key: 'tsn',
      width: 260,
      render: (_, r) => r.tsn_protocol_label || <Tag color="default">未绑定</Tag>,
    },
    {
      title: '设备协议版本数',
      key: 'dp_count',
      width: 140,
      render: (_, r) => (
        <Tag color={r.device_protocol_version_ids?.length ? 'blue' : 'default'}>
          {r.device_protocol_version_ids?.length || 0} 个
        </Tag>
      ),
    },
    { title: '描述', dataIndex: 'description', ellipsis: true, render: (v) => v || '—' },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 160,
      render: (t) => (t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '—'),
    },
    {
      title: '操作',
      key: 'op',
      width: 220,
      fixed: 'right',
      render: (_, r) => (
        <Space>
          <Button size="small" type="link" onClick={() => setDetail(r)}>详情</Button>
          <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
          <Popconfirm title="删除该飞机构型？关联架次的绑定会被清空" onConfirm={() => remove(r)}>
            <Button size="small" type="link" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="一个飞机构型（如 0号机 VA）= 一个 TSN/ICD 协议版本 + 一组设备协议版本。架次绑定该构型后，所有协议配置即冻结。"
      />
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建飞机构型</Button>
      </Space>
      <Table
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={rows}
        loading={loading}
        pagination={{ pageSize: 15 }}
        scroll={{ x: 1200 }}
      />

      <Modal
        title={editing?.id ? '编辑飞机构型' : '新建飞机构型'}
        open={!!editing}
        onCancel={() => setEditing(null)}
        onOk={submit}
        destroyOnClose
        width={720}
      >
        <Form form={form} layout="vertical">
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '0 16px' }}>
            <Form.Item name="name" label="构型名称" rules={[{ required: true }]}>
              <Input placeholder="例如 0号机 VA" />
            </Form.Item>
            <Form.Item name="version" label="版本号">
              <Input placeholder="例如 VA" />
            </Form.Item>
          </div>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={500} showCount />
          </Form.Item>
          <Form.Item
            name="tsn_protocol_version_id"
            label="TSN 协议版本（ICD）"
            rules={[{ required: true, message: '请选择 TSN 协议版本' }]}
          >
            <Select
              placeholder="选择 TSN 网络协议版本"
              showSearch
              optionFilterProp="label"
              options={tsnOptions.map((o) => ({
                value: o.id,
                label: o.label + (o.availability_status ? ` · ${o.availability_status}` : ''),
              }))}
            />
          </Form.Item>
          <Form.Item
            name="device_protocol_version_ids"
            label="设备协议版本（ARINC429 / CAN / RS422，多选）"
          >
            <Select
              mode="multiple"
              placeholder="选择该构型启用的设备协议版本"
              showSearch
              optionFilterProp="label"
              options={devOptionItems}
              maxTagCount="responsive"
            />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={detail ? `飞机构型详情：${detail.name}` : ''}
        open={!!detail}
        width={560}
        onClose={() => setDetail(null)}
      >
        {detail && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="名称">{detail.name}</Descriptions.Item>
              <Descriptions.Item label="版本">{detail.version || '—'}</Descriptions.Item>
              <Descriptions.Item label="TSN 协议版本">
                {detail.tsn_protocol_label || <Tag>未绑定</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="描述">{detail.description || '—'}</Descriptions.Item>
              <Descriptions.Item label="创建人">{detail.created_by || '—'}</Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {detail.created_at ? dayjs(detail.created_at).format('YYYY-MM-DD HH:mm') : '—'}
              </Descriptions.Item>
            </Descriptions>
            <div>
              <Text strong>设备协议版本（{detail.device_protocol_summary?.length || 0}）</Text>
              <Table
                style={{ marginTop: 8 }}
                size="small"
                rowKey="id"
                pagination={false}
                dataSource={detail.device_protocol_summary || []}
                columns={[
                  { title: '族', dataIndex: 'protocol_family', width: 80, render: (v) => <Tag>{(v || '').toUpperCase()}</Tag> },
                  { title: 'ATA', dataIndex: 'ata_code', width: 90 },
                  { title: '设备', dataIndex: 'device_name', ellipsis: true },
                  { title: '版本', dataIndex: 'version_name', width: 110 },
                ]}
              />
            </div>
          </Space>
        )}
      </Drawer>
    </div>
  )
}

// ══════════════════════════ 软件构型 ══════════════════════════
function SoftwareConfigPanel() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importMode, setImportMode] = useState('merge')
  const [importResult, setImportResult] = useState(null)
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()
  const [activeCfg, setActiveCfg] = useState(null)
  const [entries, setEntries] = useState([])
  const [entriesLoading, setEntriesLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await configurationApi.listSoftwareConfigs()
      setRows(r.data || [])
    } catch (e) {
      message.error(e?.response?.data?.detail || '加载软件构型失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const loadEntries = useCallback(async (cfg) => {
    setActiveCfg(cfg)
    setEntriesLoading(true)
    try {
      const r = await configurationApi.listSoftwareEntries(cfg.id)
      setEntries(r.data || [])
    } catch (e) {
      message.error(e?.response?.data?.detail || '加载条目失败')
    } finally {
      setEntriesLoading(false)
    }
  }, [])

  const importExcel = async (file) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('mode', importMode)
    setImporting(true)
    setImportResult(null)
    try {
      const r = await configurationApi.importSoftwareExcel(fd)
      const s = r.data?.summary || {}
      setImportResult(s)
      message.success(
        `导入完成：构型 +${s.configs_created}/更新 ${s.configs_updated}；设备 +${s.devices_created}/更新 ${s.devices_updated}；条目 ${s.entries_written}`,
      )
      load()
    } catch (e) {
      message.error(e?.response?.data?.detail || 'Excel 导入失败')
    } finally {
      setImporting(false)
    }
    return false
  }

  const openCreate = () => {
    setEditing({})
    form.resetFields()
  }

  const openEdit = (row) => {
    setEditing(row)
    form.setFieldsValue({
      name: row.name,
      snapshot_date: row.snapshot_date || '',
      description: row.description,
    })
  }

  const submit = async () => {
    try {
      const v = await form.validateFields()
      const dateStr = (v.snapshot_date || '').trim()
      if (dateStr && !/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
        message.error('试验日期格式需为 YYYY-MM-DD')
        return
      }
      const payload = {
        name: v.name?.trim(),
        snapshot_date: dateStr || null,
        description: v.description || null,
      }
      if (editing?.id) {
        await configurationApi.updateSoftwareConfig(editing.id, payload)
        message.success('软件构型已更新')
      } else {
        await configurationApi.createSoftwareConfig(payload)
        message.success('软件构型已创建')
      }
      setEditing(null)
      load()
    } catch (e) {
      if (e?.errorFields) return
      message.error(e?.response?.data?.detail || '保存失败')
    }
  }

  const remove = async (row) => {
    try {
      await configurationApi.deleteSoftwareConfig(row.id)
      message.success('已删除')
      if (activeCfg?.id === row.id) {
        setActiveCfg(null)
        setEntries([])
      }
      load()
    } catch (e) {
      message.error(e?.response?.data?.detail || '删除失败')
    }
  }

  const saveEntry = async (deviceId, patch) => {
    const current = entries.find((e) => e.device_id === deviceId)
    const items = [
      {
        device_id: deviceId,
        software_version_code: patch.software_version_code ?? current?.software_version_code ?? null,
        change_note: patch.change_note ?? current?.change_note ?? null,
      },
    ]
    try {
      await configurationApi.upsertSoftwareEntries(activeCfg.id, items, false)
      await loadEntries(activeCfg)
    } catch (e) {
      message.error(e?.response?.data?.detail || '保存失败')
    }
  }

  const cfgColumns = [
    { title: '构型名称', dataIndex: 'name', ellipsis: true },
    { title: '试验日期', dataIndex: 'snapshot_date', width: 120, render: (v) => v || '—' },
    {
      title: '来源',
      dataIndex: 'source',
      width: 100,
      render: (v) => <Tag color={v === 'excel' ? 'geekblue' : 'default'}>{v}</Tag>,
    },
    { title: '条目数', dataIndex: 'entry_count', width: 90 },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 160,
      render: (t) => (t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '—'),
    },
    {
      title: '操作',
      key: 'op',
      width: 240,
      fixed: 'right',
      render: (_, r) => (
        <Space>
          <Button size="small" type="link" onClick={() => loadEntries(r)}>
            条目（{r.entry_count}）
          </Button>
          <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(r)}>
            编辑
          </Button>
          <Popconfirm title="删除该软件构型？关联架次的绑定会被清空" onConfirm={() => remove(r)}>
            <Button size="small" type="link" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const entryColumns = [
    { title: '团队', dataIndex: ['device', 'team'], width: 130 },
    { title: '设备', dataIndex: ['device', 'device_cn_name'], width: 180, ellipsis: true },
    { title: '软件名', dataIndex: ['device', 'software_cn_name'], width: 220, ellipsis: true },
    { title: 'DM 号', dataIndex: ['device', 'device_dm_number'], width: 150 },
    {
      title: '软件版本号',
      dataIndex: 'software_version_code',
      width: 280,
      render: (v, r) => (
        <Input.TextArea
          autoSize={{ minRows: 1, maxRows: 3 }}
          defaultValue={v || ''}
          onBlur={(e) => {
            const nv = e.target.value || null
            if ((nv || null) !== (v || null)) saveEntry(r.device_id, { software_version_code: nv })
          }}
        />
      ),
    },
    {
      title: '更改说明',
      dataIndex: 'change_note',
      render: (v, r) => (
        <Input.TextArea
          autoSize={{ minRows: 1, maxRows: 4 }}
          defaultValue={v || ''}
          onBlur={(e) => {
            const nv = e.target.value || null
            if ((nv || null) !== (v || null)) saveEntry(r.device_id, { change_note: nv })
          }}
        />
      ),
    },
  ]

  return (
    <div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="上传《软件编号（...）.xlsx》即可一键生成/合并多份软件构型。每个构型对应 Excel 中的一列（如 '机上试验2026.04.09'），条目为设备 × 软件版本号。"
      />
      <Card
        type="inner"
        title={<span><CloudUploadOutlined /> Excel 一键导入</span>}
        style={{ marginBottom: 16 }}
      >
        <Space wrap>
          <span style={{ color: '#a1a1aa' }}>模式</span>
          <Select
            value={importMode}
            onChange={setImportMode}
            style={{ width: 180 }}
            options={[
              { value: 'merge', label: 'merge（合并，推荐）' },
              { value: 'replace', label: 'replace（同名构型先清空再写）' },
            ]}
          />
          <Upload beforeUpload={importExcel} showUploadList={false} accept=".xlsx,.xlsm">
            <Button type="primary" icon={<UploadOutlined />} loading={importing}>
              选择 Excel 文件（.xlsx）
            </Button>
          </Upload>
        </Space>
        {importResult && (
          <Alert
            type="success"
            showIcon
            style={{ marginTop: 12 }}
            message={`导入摘要：新增构型 ${importResult.configs_created} / 更新 ${importResult.configs_updated}；新增设备 ${importResult.devices_created} / 更新 ${importResult.devices_updated}；写入条目 ${importResult.entries_written}；跳过空行 ${importResult.skipped_rows}`}
            description={
              importResult.warnings?.length ? (
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {importResult.warnings.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
              ) : null
            }
          />
        )}
      </Card>

      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建空白软件构型</Button>
      </Space>
      <Table
        rowKey="id"
        size="small"
        columns={cfgColumns}
        dataSource={rows}
        loading={loading}
        pagination={{ pageSize: 15 }}
        scroll={{ x: 1000 }}
      />

      <Drawer
        title={activeCfg ? `软件构型条目：${activeCfg.name}` : ''}
        width="86%"
        open={!!activeCfg}
        onClose={() => { setActiveCfg(null); setEntries([]) }}
        destroyOnClose
      >
        {activeCfg && (
          <>
            <Descriptions size="small" column={3} style={{ marginBottom: 12 }}>
              <Descriptions.Item label="来源">{activeCfg.source}</Descriptions.Item>
              <Descriptions.Item label="试验日期">{activeCfg.snapshot_date || '—'}</Descriptions.Item>
              <Descriptions.Item label="条目数">{activeCfg.entry_count}</Descriptions.Item>
              <Descriptions.Item label="创建人">{activeCfg.created_by || '—'}</Descriptions.Item>
              <Descriptions.Item label="更新时间" span={2}>
                {activeCfg.updated_at ? dayjs(activeCfg.updated_at).format('YYYY-MM-DD HH:mm') : '—'}
              </Descriptions.Item>
            </Descriptions>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message="在表格中直接编辑软件版本号或更改说明，失焦时自动保存。只能修改此构型下已存在的设备条目；新增条目请通过 Excel 再次导入或在代码侧扩展。"
            />
            <Table
              rowKey={(r) => `${r.software_config_id}-${r.device_id}`}
              size="small"
              columns={entryColumns}
              dataSource={entries}
              loading={entriesLoading}
              pagination={{ pageSize: 25, showSizeChanger: true }}
              scroll={{ x: 1100, y: 480 }}
            />
          </>
        )}
      </Drawer>

      <Modal
        title={editing?.id ? '编辑软件构型' : '新建软件构型'}
        open={!!editing}
        onCancel={() => setEditing(null)}
        onOk={submit}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="构型名称" rules={[{ required: true }]}>
            <Input placeholder="例如 首飞构型定义A版 / 机上试验2026.04.09" maxLength={300} />
          </Form.Item>
          <Form.Item name="snapshot_date" label="试验日期（可选）" extra="留空时系统会尝试从名称里解析 yyyy.mm.dd">
            {/* 避免依赖 DatePicker dayjs 语言包，用字符串即可 */}
            <Input placeholder="YYYY-MM-DD" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={500} showCount />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ══════════════════════════ 主页面 ══════════════════════════
export default function ConfigurationManagerPage() {
  return (
    <div className="app-page-shell fade-in">
      <div className="app-page-shell-inner">
        <AppPageHeader
          icon={<SettingOutlined />}
          eyebrow="平台运维"
          title="构型管理"
          subtitle="维护软件构型快照、飞机构型（关联 TSN / 设备协议版本）与设备库；试验架次会引用这里的构型信息。"
          tags={[{ text: '仅管理员' }]}
        />
        <div className="app-page-body">
          <Card>
            <Tabs
              defaultActiveKey="software"
              items={[
                {
                  key: 'software',
                  label: (
                    <span><CloudUploadOutlined /> 软件构型</span>
                  ),
                  children: <SoftwareConfigPanel />,
                },
                {
                  key: 'aircraft',
                  label: (
                    <span><SafetyCertificateOutlined /> 飞机构型</span>
                  ),
                  children: <AircraftConfigPanel />,
                },
                {
                  key: 'devices',
                  label: (
                    <span><ApartmentOutlined /> 设备库</span>
                  ),
                  children: <DeviceLibraryPanel />,
                },
              ]}
            />
          </Card>
        </div>
      </div>
    </div>
  )
}
