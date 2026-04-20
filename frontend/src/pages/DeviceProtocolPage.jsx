import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Layout,
  Tree,
  Card,
  Tabs,
  Button,
  Table,
  Tag,
  Input,
  Select,
  Space,
  Empty,
  Spin,
  Descriptions,
  Modal,
  Form,
  message,
  Alert,
  Typography,
  Segmented,
  Divider,
  AutoComplete,
  Tooltip,
} from 'antd'
import {
  ApartmentOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  EditOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { deviceProtocolApi } from '../services/api'
import { useAuth } from '../context/AuthContext'
import Arinc429SpecEditor from './device-protocol/Arinc429SpecEditor'

const { Sider, Content } = Layout
const { Text } = Typography

const FAMILY_COLORS = {
  arinc429: 'purple',
  can: 'blue',
  rs422: 'geekblue',
}

const FAMILY_LABEL = {
  arinc429: 'ARINC 429',
  can: 'CAN',
  rs422: 'RS422',
}

const FAMILY_TAG = {
  arinc429: '429',
  can: 'CAN',
  rs422: '422',
}


function filterTreeByKeyword(nodes, keyword) {
  if (!keyword) return nodes
  const kw = keyword.toLowerCase()
  const visit = (arr) =>
    (arr || [])
      .map((n) => {
        const selfHit =
          (n.title || '').toString().toLowerCase().includes(kw) ||
          (n.device_id || '').toLowerCase().includes(kw) ||
          (n.ata_code || '').toLowerCase().includes(kw) ||
          (n.family || '').toLowerCase().includes(kw)
        const children = visit(n.children || [])
        if (selfHit || children.length) {
          return { ...n, children }
        }
        return null
      })
      .filter(Boolean)
  return visit(nodes)
}


function DeviceProtocolPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const canWrite = ['admin', 'device_team'].includes((user?.role || '').trim())

  const [collapsed, setCollapsed] = useState(false)
  const [families, setFamilies] = useState([])
  const [familyFilter, setFamilyFilter] = useState(null)
  const [groupBy, setGroupBy] = useState('ata')
  const [tree, setTree] = useState([])
  const [treeLoading, setTreeLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [selectedKey, setSelectedKey] = useState(null)
  const [selectedMeta, setSelectedMeta] = useState(null)

  const [ataSystems, setAtaSystems] = useState([])

  const [specDetail, setSpecDetail] = useState(null)
  const [specLoading, setSpecLoading] = useState(false)

  const [drafts, setDrafts] = useState([])
  const [changeRequests, setChangeRequests] = useState([])
  const [draftsLoading, setDraftsLoading] = useState(false)
  const [crsLoading, setCrsLoading] = useState(false)

  const [tab, setTab] = useState('overview')

  const [createVisible, setCreateVisible] = useState(false)
  const [createLoading, setCreateLoading] = useState(false)
  const [createForm] = Form.useForm()
  const [identityPreview, setIdentityPreview] = useState(null)

  const loadFamilies = useCallback(async () => {
    try {
      const { data } = await deviceProtocolApi.listFamilies()
      setFamilies(data?.items || [])
    } catch {
      /* ignore */
    }
  }, [])

  const loadAtaSystems = useCallback(async () => {
    try {
      const { data } = await deviceProtocolApi.listAtaSystems()
      setAtaSystems(data?.items || [])
    } catch {
      /* ignore */
    }
  }, [])

  const loadTree = useCallback(async (fam, grp) => {
    setTreeLoading(true)
    try {
      const { data } = await deviceProtocolApi.getTree({ family: fam || null, groupBy: grp || 'ata' })
      setTree(data?.items || [])
    } catch (e) {
      message.error(e?.response?.data?.detail || '加载设备树失败')
    } finally {
      setTreeLoading(false)
    }
  }, [])

  const loadDrafts = useCallback(async (fam = null, specId = null) => {
    setDraftsLoading(true)
    try {
      const params = {}
      if (fam) params.family = fam
      if (specId) params.spec_id = specId
      const { data } = await deviceProtocolApi.listDrafts(params)
      setDrafts(data?.items || [])
    } catch (e) {
      message.error(e?.response?.data?.detail || '加载草稿列表失败')
    } finally {
      setDraftsLoading(false)
    }
  }, [])

  const loadCRs = useCallback(async (fam = null) => {
    setCrsLoading(true)
    try {
      const params = {}
      if (fam) params.family = fam
      const { data } = await deviceProtocolApi.listChangeRequests(params)
      setChangeRequests(data?.items || [])
    } catch (e) {
      message.error(e?.response?.data?.detail || '加载审批列表失败')
    } finally {
      setCrsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadFamilies()
    loadAtaSystems()
    loadTree(null, groupBy)
    loadDrafts(null)
    loadCRs(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const filteredTree = useMemo(
    () => filterTreeByKeyword(tree, keyword),
    [tree, keyword],
  )

  const antdTreeData = useMemo(() => {
    const mapNode = (n) => {
      const isDevice = n.type === 'device'
      const isFamilyNode = n.type === 'family'
      return {
        key: n.key,
        title: (
          <Space size={6}>
            {isFamilyNode ? (
              <Tag color={FAMILY_COLORS[n.family] || 'default'} style={{ margin: 0 }}>
                {FAMILY_LABEL[n.family] || (n.family || '').toUpperCase()}
              </Tag>
            ) : null}
            {isDevice && groupBy === 'ata' ? (
              <Tag color={FAMILY_COLORS[n.family] || 'default'} style={{ margin: 0 }}>
                {FAMILY_TAG[n.family] || (n.family || '').toUpperCase()}
              </Tag>
            ) : null}
            <span>{n.title}</span>
          </Space>
        ),
        selectable: true,
        __meta: n,
        children: (n.children || []).map(mapNode),
      }
    }
    return filteredTree.map(mapNode)
  }, [filteredTree, groupBy])

  const expandedKeysAll = useMemo(() => {
    const keys = []
    const walk = (arr) => {
      (arr || []).forEach((n) => {
        if (n.children && n.children.length) {
          keys.push(n.key)
          walk(n.children)
        }
      })
    }
    walk(antdTreeData)
    return keys
  }, [antdTreeData])

  const onSelectTree = (keys, info) => {
    const meta = info?.node?.__meta
    if (!meta) return
    setSelectedKey(keys[0] || null)
    setSelectedMeta(meta)
    if (meta.type === 'device') {
      setTab('overview')
      loadSpec(meta.spec_id)
      loadDrafts(meta.family, meta.spec_id)
    } else {
      setSpecDetail(null)
      loadDrafts(meta.family || null)
    }
  }

  const loadSpec = async (specId) => {
    setSpecLoading(true)
    try {
      const { data } = await deviceProtocolApi.getSpec(specId)
      setSpecDetail(data)
    } catch (e) {
      message.error(e?.response?.data?.detail || '加载设备详情失败')
      setSpecDetail(null)
    } finally {
      setSpecLoading(false)
    }
  }

  const reloadAll = () => {
    loadAtaSystems()
    loadTree(familyFilter, groupBy)
    if (selectedMeta?.type === 'device') loadSpec(selectedMeta.spec_id)
    loadDrafts(familyFilter, selectedMeta?.type === 'device' ? selectedMeta.spec_id : null)
    loadCRs(familyFilter)
  }

  // ── 修改协议（一键入口） ──
  const handleEditSpec = async (spec) => {
    if (!spec?.id) return
    try {
      const { data } = await deviceProtocolApi.editSpec(spec.id)
      message.success(`已进入草稿 #${data.id}，可直接编辑 Label`)
      navigate(`/device-protocol/drafts/${data.id}`)
    } catch (e) {
      message.error(e?.response?.data?.detail || '创建/进入草稿失败')
    }
  }

  // ── 新建设备 ──
  const openCreateModal = () => {
    createForm.resetFields()
    setIdentityPreview(null)
    createForm.setFieldsValue({
      protocol_family: 'arinc429',
      ata_code: selectedMeta?.ata_code || undefined,
    })
    setCreateVisible(true)
    setTimeout(() => refreshIdentity(), 0)
  }

  const refreshIdentity = async () => {
    try {
      const values = createForm.getFieldsValue()
      const ata = (values.ata_code || '').trim()
      const fam = values.protocol_family || 'arinc429'
      const name = (values.device_name || '').trim()
      if (!ata || !name) {
        setIdentityPreview(null)
        return
      }
      let deviceNumber = values.device_number
      if (!deviceNumber) {
        try {
          const { data: nn } = await deviceProtocolApi.getNextDeviceNumber(ata)
          if (nn?.system_prefix) {
            deviceNumber = `${nn.system_prefix}-${nn.next_seq}`
            createForm.setFieldsValue({ device_number: deviceNumber })
          }
        } catch {
          /* ignore */
        }
      }
      const { data: preview } = await deviceProtocolApi.previewDeviceIdentity({
        ata_code: ata,
        device_number: deviceNumber || null,
        device_name: name,
        protocol_family: fam,
      })
      setIdentityPreview(preview)
    } catch {
      setIdentityPreview(null)
    }
  }

  const handleCreate = async () => {
    try {
      const values = await createForm.validateFields()
      setCreateLoading(true)
      await refreshIdentity()
      const identity = identityPreview || {}
      const fam = values.protocol_family
      const ata = (values.ata_code || '').trim()
      const deviceName = (values.device_name || '').trim()

      const { data } = await deviceProtocolApi.createDraftScratch({
        protocol_family: fam,
        ata_code: ata,
        device_id: identity.device_id,
        device_name: identity.full_device_name || deviceName,
        parent_path: values.parent_path
          ? values.parent_path.split('/').map((s) => s.trim()).filter(Boolean)
          : (ata ? [ata.toUpperCase()] : []),
        description: values.description,
      })
      message.success('新建设备草稿创建成功，发布时将自动登记为 V1.0')
      setCreateVisible(false)
      navigate(`/device-protocol/drafts/${data.id}`)
    } catch (e) {
      if (e?.errorFields) return
      message.error(e?.response?.data?.detail || '创建失败')
    } finally {
      setCreateLoading(false)
    }
  }

  // ── Tables ──
  const versionColumns = [
    { title: '版本', dataIndex: 'version_name', key: 'version_name', render: (t) => <Tag color="purple">{t}</Tag> },
    {
      title: '状态',
      dataIndex: 'availability_status',
      key: 'availability_status',
      render: (s) => {
        const map = { Available: 'green', PendingCode: 'gold', Deprecated: 'default' }
        return <Tag color={map[s] || 'default'}>{s}</Tag>
      },
    },
    {
      title: 'Git 导出',
      dataIndex: 'git_export_status',
      key: 'git_export_status',
      render: (s, rec) => {
        const map = { exported: 'green', pending: 'default', skipped: 'default', failed: 'red' }
        return (
          <Space size={4} direction="vertical">
            <Tag color={map[s] || 'default'}>{s}</Tag>
            {rec.git_commit_hash ? (
              <Text code style={{ fontSize: 11 }}>{String(rec.git_commit_hash).slice(0, 10)}</Text>
            ) : null}
          </Space>
        )
      },
    },
    { title: '发布人', dataIndex: 'created_by', key: 'created_by' },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (t) => (t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '-'),
    },
    {
      title: '操作',
      key: 'op',
      render: (_, rec) => (
        <Button size="small" onClick={() => navigate(`/device-protocol/versions/${rec.id}`)}>
          查看
        </Button>
      ),
    },
  ]

  const draftColumns = [
    { title: '草稿', dataIndex: 'name', key: 'name' },
    {
      title: '协议族',
      dataIndex: 'protocol_family',
      key: 'protocol_family',
      render: (f) => <Tag color={FAMILY_COLORS[f]}>{FAMILY_LABEL[f] || f}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s) => {
        const map = {
          draft: 'default', pending: 'processing', rejected: 'red',
          approved: 'blue', published: 'green',
        }
        return <Tag color={map[s] || 'default'}>{s}</Tag>
      },
    },
    { title: '创建人', dataIndex: 'created_by', key: 'created_by' },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      render: (t) => (t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '-'),
    },
    {
      title: '操作',
      key: 'op',
      render: (_, rec) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => navigate(`/device-protocol/drafts/${rec.id}`)}>
            打开
          </Button>
        </Space>
      ),
    },
  ]

  const crColumns = [
    { title: 'CR#', dataIndex: 'id', key: 'id', width: 72 },
    {
      title: '草稿',
      key: 'draft',
      render: (_, rec) => (
        <Space direction="vertical" size={2}>
          <Text>{rec.device_draft?.name}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {FAMILY_LABEL[rec.device_draft?.protocol_family] || rec.device_draft?.protocol_family}
          </Text>
        </Space>
      ),
    },
    { title: '提交人', dataIndex: 'submitted_by', key: 'submitted_by' },
    {
      title: '当前步骤',
      key: 'current_step',
      render: (_, rec) => {
        const role = rec.chain_roles?.[rec.current_step]
        return role ? <Tag>{role}</Tag> : <Tag>完成</Tag>
      },
    },
    {
      title: '状态',
      dataIndex: 'overall_status',
      key: 'overall_status',
      render: (s) => {
        const map = { pending: 'processing', approved: 'blue', rejected: 'red', published: 'green' }
        return <Tag color={map[s] || 'default'}>{s}</Tag>
      },
    },
    {
      title: '提交时间',
      dataIndex: 'submitted_at',
      key: 'submitted_at',
      render: (t) => (t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '-'),
    },
    {
      title: '操作',
      key: 'op',
      render: (_, rec) => (
        <Button size="small" onClick={() => navigate(`/device-protocol/change-requests/${rec.id}`)}>
          查看
        </Button>
      ),
    },
  ]

  // ── Right pane ──
  const renderDeviceContent = () => {
    if (!selectedMeta || selectedMeta.type !== 'device') {
      return (
        <Card>
          <Empty
            description={
              selectedMeta
                ? '请在左树选择具体设备查看详情'
                : '左侧选择设备查看详情；或点击左侧「新建设备」开始添加'
            }
          />
        </Card>
      )
    }
    if (specLoading) {
      return <Card><Spin /></Card>
    }
    if (!specDetail) return <Card><Empty /></Card>
    const spec = specDetail.spec
    const summary = specDetail.summary || {}
    const labels = specDetail.labels_view || []
    const versions = specDetail.versions || []
    const hasActiveDraft = drafts.some((d) => ['draft', 'pending'].includes(d.status) && d.spec_id === spec.id)

    return (
      <Tabs
        activeKey={tab}
        onChange={setTab}
        tabBarExtraContent={canWrite ? (
          <Tooltip title={hasActiveDraft ? '该设备已有进行中的草稿/审批，进入后继续编辑' : '创建一条基于最新版本的草稿，发布时自动升版'}>
            <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => handleEditSpec(spec)}>
              {hasActiveDraft ? '继续编辑草稿' : '修改协议'}
            </Button>
          </Tooltip>
        ) : null}
        items={[
          {
            key: 'overview',
            label: '概览',
            children: (
              <Card>
                <Descriptions
                  column={2}
                  bordered
                  size="small"
                  title={
                    <Space>
                      <Tag color={FAMILY_COLORS[spec.protocol_family]}>
                        {FAMILY_LABEL[spec.protocol_family] || spec.protocol_family}
                      </Tag>
                      <span>{spec.device_name}</span>
                      <Text type="secondary" code>{spec.device_id}</Text>
                    </Space>
                  }
                >
                  <Descriptions.Item label="ATA">{(spec.ata_code || '').toUpperCase() || '-'}</Descriptions.Item>
                  <Descriptions.Item label="状态">
                    <Tag color={spec.status === 'active' ? 'green' : 'default'}>{spec.status}</Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="最新版本">
                    {versions[0] ? (
                      <Space>
                        <Tag color="purple">{versions[0].version_name}</Tag>
                        <Tag color="gold">{versions[0].availability_status}</Tag>
                      </Space>
                    ) : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="创建人">{spec.created_by || '-'}</Descriptions.Item>
                  <Descriptions.Item label="描述" span={2}>{spec.description || '-'}</Descriptions.Item>
                  {spec.protocol_family === 'arinc429' && (
                    <>
                      <Descriptions.Item label="Label 数">{summary.label_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="BNR / Discrete / Special">
                        {summary.bnr_field_count || 0} / {summary.discrete_bit_count || 0} / {summary.special_field_count || 0}
                      </Descriptions.Item>
                    </>
                  )}
                  {spec.protocol_family === 'can' && (
                    <>
                      <Descriptions.Item label="报文数">{summary.message_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="信号数">{summary.signal_count || 0}</Descriptions.Item>
                    </>
                  )}
                  {spec.protocol_family === 'rs422' && (
                    <>
                      <Descriptions.Item label="帧类型数">{summary.frame_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="字段数">{summary.field_count || 0}</Descriptions.Item>
                    </>
                  )}
                </Descriptions>
              </Card>
            ),
          },
          {
            key: 'versions',
            label: `版本 (${versions.length})`,
            children: (
              <Card>
                <Table size="small" rowKey="id" columns={versionColumns} dataSource={versions} pagination={false} />
              </Card>
            ),
          },
          {
            key: 'labels',
            label: spec.protocol_family === 'arinc429' ? `Labels (${labels.length})` : `数据项 (${labels.length})`,
            children: (
              spec.protocol_family === 'arinc429' ? (
                specDetail.latest_spec_json ? (
                  <>
                    <Alert
                      type={canWrite ? 'info' : 'warning'}
                      showIcon
                      style={{ marginBottom: 12 }}
                      message={
                        canWrite
                          ? `当前显示最新发布版本${specDetail.latest_version_name ? ` ${specDetail.latest_version_name}` : ''}（只读）。修改请点击右上角「${hasActiveDraft ? '继续编辑草稿' : '修改协议'}」进入草稿。`
                          : `当前账号为只读，点击 Label 卡片可查看位图/字段定义细节，无法修改`
                      }
                    />
                    <Arinc429SpecEditor
                      value={specDetail.latest_spec_json}
                      readOnly
                    />
                  </>
                ) : (
                  <Card><Empty description="当前最新版本暂无 labels" /></Card>
                )
              ) : (
                <Card>
                  {labels.length === 0 ? (
                    <Empty description="当前最新版本暂无 labels" />
                  ) : (
                    <Table
                      size="small"
                      rowKey="key"
                      dataSource={labels}
                      pagination={{ pageSize: 20, showSizeChanger: false }}
                      columns={buildLabelColumns(spec.protocol_family)}
                    />
                  )}
                </Card>
              )
            ),
          },
          {
            key: 'drafts',
            label: '草稿 / 审批',
            children: (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Card title={`草稿（${drafts.length}）`} size="small">
                  <Table size="small" rowKey="id" loading={draftsLoading} columns={draftColumns} dataSource={drafts} pagination={{ pageSize: 10 }} />
                </Card>
                <Card title="审批流" size="small">
                  <Table
                    size="small"
                    rowKey="id"
                    loading={crsLoading}
                    columns={crColumns}
                    dataSource={changeRequests.filter((cr) =>
                      cr.device_draft?.spec_id === spec.id ||
                      (cr.device_draft?.pending_spec_meta || {}).device_id === spec.device_id,
                    )}
                    pagination={{ pageSize: 10 }}
                  />
                </Card>
              </Space>
            ),
          },
        ]}
      />
    )
  }

  return (
    <Layout style={{ background: 'transparent', minHeight: 'calc(100vh - 112px)' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        trigger={null}
        width={320}
        collapsedWidth={48}
        theme="light"
        style={{
          background: 'rgba(24, 24, 27, 0.6)',
          borderRadius: 10,
          marginRight: 16,
          border: '1px solid rgba(70, 70, 82, 0.3)',
          overflow: 'hidden',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', padding: '10px 12px', borderBottom: '1px solid rgba(63,63,70,0.4)' }}>
          <Button
            type="text"
            size="small"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed(!collapsed)}
            style={{ color: '#d4d4d8' }}
          />
          {!collapsed && (
            <Text style={{ color: '#e4e4e7', marginLeft: 8, fontWeight: 600 }}>
              <ApartmentOutlined /> 设备树
            </Text>
          )}
        </div>
        {!collapsed && (
          <div style={{ padding: '8px 10px' }}>
            <Space direction="vertical" size={6} style={{ width: '100%' }}>
              <Segmented
                size="small"
                value={groupBy}
                onChange={(v) => {
                  setGroupBy(v)
                  loadTree(familyFilter, v)
                }}
                block
                options={[
                  { value: 'ata', label: '按 ATA 看' },
                  { value: 'family', label: '按协议族' },
                ]}
              />
              <Select
                placeholder="协议族（全部）"
                allowClear
                size="small"
                style={{ width: '100%' }}
                value={familyFilter}
                onChange={(v) => {
                  setFamilyFilter(v || null)
                  loadTree(v || null, groupBy)
                  loadDrafts(v || null, null)
                  loadCRs(v || null)
                }}
                options={families.map((f) => ({
                  label: FAMILY_LABEL[f.family] || f.family.toUpperCase(),
                  value: f.family,
                }))}
              />
              <Input
                size="small"
                placeholder="搜索 设备名 / ATA / 协议族"
                prefix={<SearchOutlined />}
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                allowClear
              />
              <div style={{ display: 'flex', gap: 6 }}>
                <Button size="small" icon={<ReloadOutlined />} onClick={reloadAll} style={{ flex: 1 }}>
                  刷新
                </Button>
                {canWrite && (
                  <Button size="small" type="primary" icon={<PlusOutlined />} onClick={openCreateModal} style={{ flex: 1 }}>
                    新建设备
                  </Button>
                )}
              </div>
            </Space>
          </div>
        )}
        {!collapsed && (
          <div style={{ padding: '4px 6px', height: 'calc(100% - 200px)', overflow: 'auto' }}>
            {treeLoading ? <div style={{ padding: 24, textAlign: 'center' }}><Spin /></div> : (
              antdTreeData.length === 0 ? (
                <Empty description="暂无设备" />
              ) : (
                <Tree
                  showLine
                  blockNode
                  treeData={antdTreeData}
                  selectedKeys={selectedKey ? [selectedKey] : []}
                  onSelect={onSelectTree}
                  expandedKeys={expandedKeysAll}
                  autoExpandParent
                />
              )
            )}
          </div>
        )}
      </Sider>
      <Content>
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          {!canWrite && (
            <Alert type="info" showIcon message="当前账号无写权限：仅设备团队 / 管理员可新建设备、修改协议" />
          )}
          {renderDeviceContent()}
        </Space>
      </Content>

      <Modal
        title="新建设备（自动生成编号和设备 ID，发布时自动登记为 V1.0）"
        open={createVisible}
        onCancel={() => setCreateVisible(false)}
        onOk={handleCreate}
        confirmLoading={createLoading}
        okText="创建草稿"
        cancelText="取消"
        width={620}
      >
        <Form
          form={createForm}
          layout="vertical"
          onValuesChange={(changed) => {
            if ('ata_code' in changed || 'protocol_family' in changed || 'device_name' in changed) {
              // 切换系统或协议 → 清空手工编号，让系统重新算
              if ('ata_code' in changed || 'protocol_family' in changed) {
                createForm.setFieldsValue({ device_number: undefined })
              }
              refreshIdentity()
            }
          }}
        >
          <Form.Item name="ata_code" label="ATA 系统" rules={[{ required: true, message: '请选择或新建 ATA 系统' }]}>
            <AutoComplete
              options={ataSystems
                .filter((s) => s.ata_code)
                .map((s) => ({ value: s.ata_code, label: `${(s.ata_code || '').toUpperCase()}（${s.device_count} 台设备）` }))}
              placeholder="如 ata32（可新建，直接输入即可）"
              filterOption={(inp, opt) => (opt?.value || '').toLowerCase().includes((inp || '').toLowerCase())}
            />
          </Form.Item>
          <Form.Item name="protocol_family" label="协议类型" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'arinc429', label: 'ARINC 429' },
                { value: 'rs422', label: 'RS422' },
                { value: 'can', label: 'CAN' },
              ]}
            />
          </Form.Item>
          <Form.Item name="device_name" label="设备名" rules={[{ required: true, message: '请输入设备名（如 转弯控制单元）' }]}>
            <Input placeholder="如 转弯控制单元" />
          </Form.Item>
          <Form.Item name="device_number" label="设备编号（留空自动生成，格式 系统前缀-序号，如 32-4）">
            <Input placeholder="留空自动计算" onBlur={refreshIdentity} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Divider style={{ margin: '8px 0' }} />
          <Alert
            type={identityPreview?.device_id ? 'success' : 'info'}
            showIcon
            message={
              identityPreview?.device_id
                ? (
                  <Space direction="vertical" size={2}>
                    <span>
                      完整设备名：<Text strong>{identityPreview.full_device_name}</Text>
                    </span>
                    <span>
                      设备 ID：<Text code>{identityPreview.device_id}</Text>
                    </span>
                  </Space>
                )
                : '填写 ATA 系统 + 设备名 后，将自动算出设备 ID 与完整名称'
            }
          />
        </Form>
      </Modal>
    </Layout>
  )
}


function buildLabelColumns(family) {
  if (family === 'arinc429') {
    return [
      { title: 'Label(oct)', dataIndex: 'label_oct', width: 90, render: (t) => <Tag color="purple">{t}</Tag> },
      { title: 'Dec', dataIndex: 'label_dec', width: 70 },
      { title: '名称', dataIndex: 'name' },
      { title: '方向', dataIndex: 'direction', width: 110 },
      { title: '数据类型', dataIndex: 'data_type', width: 110 },
      { title: '单位', dataIndex: 'unit', width: 90 },
      {
        title: 'BNR / Discrete / Special',
        key: 'ratios',
        width: 180,
        render: (_, r) => `${r.bnr_count || 0} / ${r.discrete_count || 0} / ${r.special_count || 0}`,
      },
    ]
  }
  if (family === 'can') {
    return [
      { title: 'Frame ID', dataIndex: 'frame_id_hex', width: 120, render: (t) => <Tag color="blue">{t}</Tag> },
      { title: '名称', dataIndex: 'name' },
      { title: 'DLC', dataIndex: 'dlc', width: 70 },
      { title: '信号数', dataIndex: 'signal_count', width: 90 },
    ]
  }
  return [
    { title: '帧', dataIndex: 'name' },
    { title: '长度', dataIndex: 'length', width: 90 },
    { title: '字段数', dataIndex: 'field_count', width: 90 },
  ]
}


export default DeviceProtocolPage
