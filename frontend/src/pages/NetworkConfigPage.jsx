import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd'
import {
  ReloadOutlined,
  EyeOutlined,
  SafetyCertificateOutlined,
  ClockCircleOutlined,
  StopOutlined,
  InfoCircleOutlined,
  UploadOutlined,
  EditOutlined,
  FileExcelOutlined,
  DeleteOutlined,
  BranchesOutlined,
  AppstoreOutlined,
  RocketOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { networkConfigApi, protocolApi } from '../services/api'
import { useAuth } from '../context/AuthContext'

const { Text, Paragraph, Title } = Typography

const STATUS_META = {
  Available: {
    color: 'success',
    label: '可用',
    icon: <SafetyCertificateOutlined />,
    description: '已激活，终端用户可在上传解析 / 事件分析时选择此版本。',
  },
  PendingCode: {
    color: 'processing',
    label: '待代码就绪',
    icon: <ClockCircleOutlined />,
    description: '已发布但后端未声明支持 / 未通过自检，对用户不可见。',
  },
  Deprecated: {
    color: 'default',
    label: '已弃用',
    icon: <StopOutlined />,
    description: '不再出现在选版本下拉；已绑定的历史解析任务仍可查看。',
  },
}

const STATUS_TABS = ['Available', 'PendingCode', 'Deprecated']

function formatTime(value) {
  if (!value) return '-'
  try {
    return dayjs(value).format('YYYY-MM-DD HH:mm:ss')
  } catch {
    return String(value)
  }
}

const DRAFT_STATUS_META = {
  draft: { color: 'default', label: '草稿' },
  pending: { color: 'processing', label: '审批中' },
  rejected: { color: 'error', label: '已驳回' },
  approved: { color: 'warning', label: '待发布' },
  published: { color: 'success', label: '已发布' },
}

function NetworkConfigPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const canWrite = user && ['admin', 'network_team'].includes((user.role || '').trim())

  const [loading, setLoading] = useState(false)
  const [grouped, setGrouped] = useState({ Available: [], PendingCode: [], Deprecated: [] })
  const [total, setTotal] = useState(0)

  // 顶层两大 Tab：browse / update
  const [topTab, setTopTab] = useState('browse')
  // 浏览子 Tab：Available / PendingCode / Deprecated
  const [browseTab, setBrowseTab] = useState('Available')

  const [parserFamilies, setParserFamilies] = useState([])

  // MR2：Draft + CR 列表
  const [myDrafts, setMyDrafts] = useState([])
  const [pendingCRs, setPendingCRs] = useState([])

  // Modal：基于版本 clone
  const [cloneOpen, setCloneOpen] = useState(false)
  const [cloneBase, setCloneBase] = useState(null)
  const [cloneForm] = Form.useForm()

  // Modal：Excel 导入
  const [excelOpen, setExcelOpen] = useState(false)
  const [excelForm] = Form.useForm()
  const [excelFile, setExcelFile] = useState(null)
  const [protocols, setProtocols] = useState([])

  // Modal：选源版本（基于已有版本入口触发）
  const [pickBaseOpen, setPickBaseOpen] = useState(false)

  const loadVersions = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const res = await networkConfigApi.listVersions()
      setGrouped(res.data?.grouped || { Available: [], PendingCode: [], Deprecated: [] })
      setTotal(res.data?.total || 0)
    } catch (err) {
      if (!silent) {
        message.error(err?.response?.data?.detail || '加载版本列表失败')
      }
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  const loadParserFamilies = useCallback(async () => {
    try {
      const res = await networkConfigApi.listParserFamilies()
      setParserFamilies(res.data?.items || [])
    } catch {
      // 家族列表加载失败不阻塞主列表
    }
  }, [])

  const loadDraftsAndCRs = useCallback(async () => {
    if (!canWrite) return
    try {
      const [mine, pending] = await Promise.all([
        networkConfigApi.listDrafts('mine'),
        networkConfigApi.listChangeRequests('pending_for_me'),
      ])
      setMyDrafts(mine.data?.items || [])
      setPendingCRs(pending.data?.items || [])
    } catch {
      // 忽略；主列表不阻塞
    }
  }, [canWrite])

  const loadProtocols = useCallback(async () => {
    try {
      const res = await protocolApi.list()
      const items = Array.isArray(res.data) ? res.data : (res.data?.items || [])
      setProtocols(items)
    } catch {
      setProtocols([])
    }
  }, [])

  useEffect(() => {
    loadVersions()
    loadParserFamilies()
    loadDraftsAndCRs()
  }, [loadVersions, loadParserFamilies, loadDraftsAndCRs])

  const refreshAll = () => {
    loadVersions()
    loadParserFamilies()
    loadDraftsAndCRs()
  }

  const openCloneModal = useCallback((version) => {
    setCloneBase(version)
    cloneForm.resetFields()
    cloneForm.setFieldsValue({
      target_version: `${version.version}-draft`,
      name: `${version.protocol_name || ''} ${version.version} 迭代草稿`,
    })
    setPickBaseOpen(false)
    setCloneOpen(true)
  }, [cloneForm])

  const openExcelModal = useCallback(() => {
    setExcelFile(null)
    excelForm.resetFields()
    loadProtocols()
    setExcelOpen(true)
  }, [excelForm, loadProtocols])

  const handleCloneSubmit = async () => {
    try {
      const values = await cloneForm.validateFields()
      const res = await networkConfigApi.createDraftFromVersion({
        base_version_id: cloneBase.id,
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

  const handleExcelSubmit = async () => {
    try {
      const values = await excelForm.validateFields()
      if (!excelFile) {
        message.error('请上传 ICD Excel 文件')
        return
      }
      const fd = new FormData()
      fd.append('protocol_id', values.protocol_id)
      fd.append('target_version', values.target_version)
      fd.append('name', values.name)
      if (values.description) fd.append('description', values.description)
      fd.append('file', excelFile)
      const res = await networkConfigApi.createDraftFromExcel(fd)
      message.success(`已导入：${res.data.import_stats?.ports_created ?? 0} 端口 / ${res.data.import_stats?.fields_created ?? 0} 字段`)
      setExcelOpen(false)
      navigate(`/network-config/drafts/${res.data.id}`)
    } catch (err) {
      if (err?.errorFields) return
      message.error(err?.response?.data?.detail || '导入失败')
    }
  }

  const handleDeleteDraft = async (draftId) => {
    try {
      await networkConfigApi.deleteDraft(draftId)
      message.success('草稿已删除')
      loadDraftsAndCRs()
    } catch (err) {
      message.error(err?.response?.data?.detail || '删除草稿失败')
    }
  }

  const handleDeprecateVersion = async (version) => {
    try {
      await networkConfigApi.deprecateVersion(version.id)
      message.success(`版本 ${version.version} 已置为 Deprecated`)
      loadVersions()
    } catch (err) {
      message.error(err?.response?.data?.detail || '弃用失败')
    }
  }

  const openVersionPage = useCallback((version) => {
    navigate(`/network-config/versions/${version.id}`)
  }, [navigate])

  const versionColumnsFor = useCallback((statusKey) => {
    const cols = [
      {
        title: '协议',
        dataIndex: 'protocol_name',
        key: 'protocol_name',
        width: 140,
        render: (v) => v || <Text type="secondary">-</Text>,
      },
      {
        title: '版本',
        dataIndex: 'version',
        key: 'version',
        width: 160,
        render: (v) => <Text strong>{v}</Text>,
      },
      {
        title: '端口数',
        dataIndex: 'port_count',
        key: 'port_count',
        width: 90,
        align: 'right',
      },
      {
        title: '来源文件',
        dataIndex: 'source_file',
        key: 'source_file',
        render: (v) => v || <Text type="secondary">-</Text>,
        ellipsis: true,
      },
      {
        title: '创建时间',
        dataIndex: 'created_at',
        key: 'created_at',
        width: 180,
        render: formatTime,
      },
      {
        title: '激活',
        dataIndex: 'activated_at',
        key: 'activated_at',
        width: 200,
        render: (value, record) => {
          if (!value) return <Text type="secondary">—</Text>
          return (
            <Space direction="vertical" size={2}>
              <Text>{formatTime(value)}</Text>
              {record.activated_by ? (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  by {record.activated_by}{record.forced_activation ? '（强制）' : ''}
                </Text>
              ) : null}
            </Space>
          )
        },
      },
      {
        title: '操作',
        key: 'actions',
        width: 220,
        render: (_, record) => (
          <Space size={4} wrap>
            <Button size="small" icon={<EyeOutlined />} onClick={() => openVersionPage(record)}>
              查看
            </Button>
            {canWrite && statusKey !== 'Deprecated' ? (
              <Popconfirm
                title="确认弃用该版本？"
                description="弃用后，终端用户将无法再选择此版本进行解析；已绑定的历史任务不受影响。"
                okText="确认弃用"
                okButtonProps={{ danger: true }}
                cancelText="取消"
                onConfirm={() => handleDeprecateVersion(record)}
              >
                <Button size="small" danger icon={<StopOutlined />}>
                  弃用
                </Button>
              </Popconfirm>
            ) : null}
          </Space>
        ),
      },
    ]
    return cols
  }, [openVersionPage, canWrite])

  const draftColumns = useMemo(() => [
    {
      title: '草稿名称',
      dataIndex: 'name',
      key: 'name',
      ellipsis: true,
      render: (v, record) => (
        <a onClick={() => navigate(`/network-config/drafts/${record.id}`)}>{v}</a>
      ),
    },
    {
      title: '目标版本',
      dataIndex: 'target_version',
      key: 'target_version',
      width: 160,
      render: (v) => <Text code>{v}</Text>,
    },
    {
      title: '来源',
      dataIndex: 'source_type',
      key: 'source_type',
      width: 110,
      render: (v) => v === 'excel'
        ? <Tag icon={<FileExcelOutlined />} color="green">Excel</Tag>
        : <Tag color="blue">基于版本</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v) => {
        const meta = DRAFT_STATUS_META[v] || { color: 'default', label: v }
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: '端口数',
      dataIndex: 'port_count',
      key: 'port_count',
      width: 80,
      align: 'right',
    },
    {
      title: '创建者',
      dataIndex: 'created_by',
      key: 'created_by',
      width: 120,
      render: (v) => v || <Text type="secondary">-</Text>,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 180,
      render: formatTime,
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      render: (_, record) => {
        const deletable = record.status === 'draft'
        return (
          <Space size={4}>
            <Button size="small" type="link" onClick={() => navigate(`/network-config/drafts/${record.id}`)}>
              编辑
            </Button>
            {deletable ? (
              <Popconfirm
                title="确认删除该草稿？"
                description="删除后无法恢复；已提交审批的草稿无法删除。"
                okText="删除"
                okButtonProps={{ danger: true }}
                cancelText="取消"
                onConfirm={() => handleDeleteDraft(record.id)}
              >
                <Button size="small" danger type="link" icon={<DeleteOutlined />}>
                  删除
                </Button>
              </Popconfirm>
            ) : null}
          </Space>
        )
      },
    },
  ], [navigate])

  const crColumns = useMemo(() => [
    {
      title: 'CR #',
      dataIndex: 'id',
      key: 'id',
      width: 80,
      render: (v) => (
        <a onClick={() => navigate(`/network-config/change-requests/${v}`)}>#{v}</a>
      ),
    },
    {
      title: '草稿',
      key: 'draft_name',
      ellipsis: true,
      render: (_, record) => record.draft?.name || <Text type="secondary">-</Text>,
    },
    {
      title: '目标版本',
      key: 'target_version',
      width: 160,
      render: (_, record) => record.draft?.target_version
        ? <Text code>{record.draft.target_version}</Text>
        : <Text type="secondary">-</Text>,
    },
    {
      title: '提交人',
      dataIndex: 'submitted_by',
      key: 'submitted_by',
      width: 120,
    },
    {
      title: '当前步骤',
      dataIndex: 'current_step',
      key: 'current_step',
      width: 100,
      render: (v) => <Tag color="processing">Step {v}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'overall_status',
      key: 'overall_status',
      width: 100,
      render: (v) => {
        const map = {
          pending: { color: 'processing', label: '审批中' },
          rejected: { color: 'error', label: '已驳回' },
          approved: { color: 'warning', label: '待发布' },
          published: { color: 'success', label: '已发布' },
        }
        const meta = map[v] || { color: 'default', label: v }
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: '提交时间',
      dataIndex: 'submitted_at',
      key: 'submitted_at',
      width: 180,
      render: formatTime,
    },
  ], [navigate])

  // ── 浏览 Tab ──
  const browseTabItems = useMemo(() => (
    STATUS_TABS.map((status) => {
      const meta = STATUS_META[status]
      const list = grouped?.[status] || []
      return {
        key: status,
        label: (
          <Space size={6}>
            {meta.icon}
            <span>{meta.label}</span>
            <Badge count={list.length} showZero overflowCount={999} style={{ backgroundColor: '#52525b' }} />
          </Space>
        ),
        children: (
          <>
            <Alert
              type="info"
              showIcon
              message={meta.description}
              style={{ marginBottom: 16 }}
            />
            {list.length === 0 ? (
              <Empty description={`暂无「${meta.label}」状态的协议版本`} />
            ) : (
              <Table
                rowKey="id"
                dataSource={list}
                columns={versionColumnsFor(status)}
                size="middle"
                pagination={{ pageSize: 20, showSizeChanger: false }}
              />
            )}
          </>
        ),
      }
    })
  ), [grouped, versionColumnsFor])

  // ── 选源版本 Modal 的表格列（精简） ──
  const pickBaseColumns = useMemo(() => [
    {
      title: '协议',
      dataIndex: 'protocol_name',
      key: 'protocol_name',
      width: 140,
      render: (v) => v || <Text type="secondary">-</Text>,
    },
    {
      title: '版本',
      dataIndex: 'version',
      key: 'version',
      width: 160,
      render: (v) => <Text strong>{v}</Text>,
    },
    {
      title: '端口数',
      dataIndex: 'port_count',
      key: 'port_count',
      width: 90,
      align: 'right',
    },
    {
      title: '状态',
      dataIndex: 'availability_status',
      key: 'availability_status',
      width: 110,
      render: (v) => {
        const meta = STATUS_META[v] || { color: 'default', label: v }
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: '激活时间',
      dataIndex: 'activated_at',
      key: 'activated_at',
      width: 180,
      render: formatTime,
    },
    {
      title: '操作',
      key: 'pick',
      width: 120,
      render: (_, record) => (
        <Button size="small" type="primary" icon={<BranchesOutlined />} onClick={() => openCloneModal(record)}>
          基于此版本
        </Button>
      ),
    },
  ], [openCloneModal])

  const allVersionsForPick = useMemo(() => {
    const avail = grouped?.Available || []
    const pending = grouped?.PendingCode || []
    return [...avail, ...pending]
  }, [grouped])

  const headerStats = useMemo(() => ({
    total,
    available: grouped?.Available?.length || 0,
    pending: grouped?.PendingCode?.length || 0,
    deprecated: grouped?.Deprecated?.length || 0,
  }), [grouped, total])

  // ── 更新新版本 Tab ──
  const updateTabContent = (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        icon={<RocketOutlined />}
        message="新版本发布流程"
        description="选择下面两种方式之一创建草稿 → 在草稿编辑器里调整端口与字段 → 静态自检 → 提交多团队会签 → 终审通过 → 后端代码就绪后进入「可用」。下方「我的工作」会追踪你正在处理的草稿与待你会签的变更请求。"
      />

      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Card
            hoverable={canWrite}
            style={{ height: '100%' }}
            onClick={canWrite ? () => setPickBaseOpen(true) : undefined}
            bodyStyle={{ padding: 24 }}
          >
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Space>
                <BranchesOutlined style={{ fontSize: 24, color: '#1677ff' }} />
                <Title level={4} style={{ margin: 0 }}>基于已有版本迭代</Title>
              </Space>
              <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                适用于小幅改动：在某个已发布的版本基础上修改端口/字段。完整复制源版本，不会影响原版本。
              </Paragraph>
              <Space>
                <Tag color="blue">推荐</Tag>
                <Text type="secondary">版本迭代 · 增删端口 · 字段调整</Text>
              </Space>
              <Button
                type="primary"
                icon={<BranchesOutlined />}
                disabled={!canWrite}
                onClick={(e) => { e.stopPropagation(); setPickBaseOpen(true) }}
                style={{ marginTop: 8 }}
              >
                选择源版本
              </Button>
            </Space>
          </Card>
        </Col>

        <Col xs={24} md={12}>
          <Card
            hoverable={canWrite}
            style={{ height: '100%' }}
            onClick={canWrite ? openExcelModal : undefined}
            bodyStyle={{ padding: 24 }}
          >
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Space>
                <FileExcelOutlined style={{ fontSize: 24, color: '#52c41a' }} />
                <Title level={4} style={{ margin: 0 }}>上传 ICD Excel</Title>
              </Space>
              <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                适用于引入全新架次的 TSN 版本：直接上传规范的 ICD Excel，端口与字段按表头解析入库为草稿。
              </Paragraph>
              <Space>
                <Tag color="green">新架次</Tag>
                <Text type="secondary">全量覆盖 · 按 ICD 6.0.x 模板</Text>
              </Space>
              <Button
                icon={<UploadOutlined />}
                disabled={!canWrite}
                onClick={(e) => { e.stopPropagation(); openExcelModal() }}
                style={{ marginTop: 8 }}
              >
                上传 ICD 文件
              </Button>
            </Space>
          </Card>
        </Col>
      </Row>

      {!canWrite ? (
        <Alert
          type="warning"
          showIcon
          message="仅网络团队 / 管理员可发起草稿"
        />
      ) : null}

      <Card
        title={(
          <Space>
            <EditOutlined />
            <span>我的工作</span>
          </Space>
        )}
        extra={(
          <Text type="secondary">
            我的草稿 {myDrafts.length} · 待我会签 {pendingCRs.length}
          </Text>
        )}
      >
        <Tabs
          items={[
            {
              key: 'my-drafts',
              label: (
                <Space size={6}>
                  <span>我的草稿</span>
                  <Badge count={myDrafts.length} showZero style={{ backgroundColor: '#52525b' }} />
                </Space>
              ),
              children: myDrafts.length === 0 ? (
                <Empty description="暂无草稿，点击上方任一卡片创建" />
              ) : (
                <Table
                  rowKey="id"
                  dataSource={myDrafts}
                  columns={draftColumns}
                  size="small"
                  pagination={{ pageSize: 10, showSizeChanger: false }}
                />
              ),
            },
            {
              key: 'pending-for-me',
              label: (
                <Space size={6}>
                  <span>待我会签</span>
                  <Badge count={pendingCRs.length} overflowCount={99} />
                </Space>
              ),
              children: pendingCRs.length === 0 ? (
                <Empty description="暂无需要我会签的变更请求" />
              ) : (
                <Table
                  rowKey="id"
                  dataSource={pendingCRs}
                  columns={crColumns}
                  size="small"
                  pagination={{ pageSize: 10, showSizeChanger: false }}
                />
              ),
            },
          ]}
        />
      </Card>
    </Space>
  )

  // ── 浏览 Tab 内容 ──
  const browseTabContent = (
    <Card bodyStyle={{ paddingTop: 8 }}>
      <Tabs
        activeKey={browseTab}
        onChange={setBrowseTab}
        items={browseTabItems}
        destroyInactiveTabPane={false}
      />
    </Card>
  )

  const updateBadge = pendingCRs.length || 0

  return (
    <div>
      <Card
        style={{ marginBottom: 16 }}
        bodyStyle={{ paddingBottom: 16 }}
        title={(
          <Space>
            <SafetyCertificateOutlined />
            <span>TSN 网络配置（协议版本管理）</span>
          </Space>
        )}
        extra={(
          <Space>
            <Button
              icon={<ReloadOutlined />}
              onClick={refreshAll}
              loading={loading}
            >
              刷新
            </Button>
          </Space>
        )}
      >
        <Space size={32} wrap>
          <Statistic title="版本总数" value={headerStats.total} />
          <Statistic title="可用" value={headerStats.available} valueStyle={{ color: '#10b981' }} />
          <Statistic title="待代码就绪" value={headerStats.pending} valueStyle={{ color: '#3b82f6' }} />
          <Statistic title="已弃用" value={headerStats.deprecated} valueStyle={{ color: '#a1a1aa' }} />
          <Statistic title="已注册协议族" value={parserFamilies.length} />
        </Space>
        <Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          <InfoCircleOutlined style={{ marginRight: 6 }} />
          在「查看已有的协议」浏览所有版本，支持弃用不再使用的版本；在「更新新的版本」发起新的版本草稿与审批。
        </Paragraph>
      </Card>

      <Card bodyStyle={{ paddingTop: 8 }}>
        <Tabs
          activeKey={topTab}
          onChange={setTopTab}
          size="large"
          items={[
            {
              key: 'browse',
              label: (
                <Space size={6}>
                  <AppstoreOutlined />
                  <span>查看已有的协议</span>
                </Space>
              ),
              children: browseTabContent,
            },
            {
              key: 'update',
              label: (
                <Space size={6}>
                  <RocketOutlined />
                  <span>更新新的版本</span>
                  {canWrite && updateBadge > 0 ? (
                    <Badge count={updateBadge} overflowCount={99} />
                  ) : null}
                </Space>
              ),
              children: updateTabContent,
            },
          ]}
        />
      </Card>

      <Modal
        title="选择要迭代的源版本"
        open={pickBaseOpen}
        onCancel={() => setPickBaseOpen(false)}
        footer={null}
        width={900}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="可选 Available / PendingCode 状态的版本作为源；已弃用版本不可作为迭代起点。"
        />
        {allVersionsForPick.length === 0 ? (
          <Empty description="当前没有可迭代的版本，请选择上传 ICD Excel 新建版本" />
        ) : (
          <Table
            rowKey="id"
            dataSource={allVersionsForPick}
            columns={pickBaseColumns}
            size="small"
            pagination={{ pageSize: 10, showSizeChanger: false }}
          />
        )}
      </Modal>

      <Modal
        title={cloneBase ? `基于版本创建草稿：${cloneBase.protocol_name || ''} ${cloneBase.version || ''}` : '基于版本创建草稿'}
        open={cloneOpen}
        onCancel={() => setCloneOpen(false)}
        onOk={handleCloneSubmit}
        okText="创建草稿"
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="将完整复制所选版本的端口与字段到一个新草稿；后续编辑不会影响原版本。"
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
            <Input placeholder="例如 X 项目 2026Q1 TSN 迭代" />
          </Form.Item>
          <Form.Item label="备注" name="description">
            <Input.TextArea rows={3} placeholder="本次迭代概述，可选" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="从 ICD Excel 创建草稿"
        open={excelOpen}
        onCancel={() => setExcelOpen(false)}
        onOk={handleExcelSubmit}
        okText="上传并创建"
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="适用于引入全新架次的 TSN 版本：请选择所属协议，并上传规范的 ICD Excel 文件。"
        />
        <Form form={excelForm} layout="vertical">
          <Form.Item
            label="所属协议"
            name="protocol_id"
            rules={[{ required: true, message: '请选择协议' }]}
          >
            <Select
              placeholder="选择协议"
              options={(protocols || []).map((p) => ({ label: `${p.name} #${p.id}`, value: p.id }))}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <Form.Item
            label="目标版本号"
            name="target_version"
            rules={[{ required: true, message: '请填写目标版本号' }]}
          >
            <Input placeholder="例如 v3.0.0" />
          </Form.Item>
          <Form.Item
            label="草稿标题"
            name="name"
            rules={[{ required: true, message: '请填写草稿标题' }]}
          >
            <Input placeholder="例如 新架次 TSN v3 初版" />
          </Form.Item>
          <Form.Item label="备注" name="description">
            <Input.TextArea rows={2} placeholder="本次版本说明，可选" />
          </Form.Item>
          <Form.Item
            label="ICD Excel 文件"
            required
            extra="支持 .xlsx 格式，需符合既有 ICD 模板；端口与字段会在上传后立即解析入库为草稿。"
          >
            <Upload
              beforeUpload={(file) => {
                setExcelFile(file)
                return false
              }}
              onRemove={() => setExcelFile(null)}
              maxCount={1}
              accept=".xlsx,.xls"
              fileList={excelFile ? [{ uid: '-1', name: excelFile.name, status: 'done' }] : []}
            >
              <Button icon={<UploadOutlined />}>选择 Excel 文件</Button>
            </Upload>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default NetworkConfigPage
