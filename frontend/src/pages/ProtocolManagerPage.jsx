import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Layout,
  Tree,
  Card,
  Table,
  Button,
  Space,
  message,
  Modal,
  Form,
  Input,
  Select,
  Checkbox,
  Typography,
  Tag,
  Popconfirm,
  Empty,
} from 'antd'
import {
  PlusOutlined,
  SaveOutlined,
  HistoryOutlined,
  DeleteOutlined,
  FolderAddOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { protocolManagerApi } from '../services/api'
import LabelEditModal from '../components/LabelEditModal'
import BitMapDisplay from '../components/BitMapDisplay'

const { Sider, Content } = Layout
const { Title, Text } = Typography

function mapTreeNodes(list) {
  if (!list || !list.length) return []
  return list.map((n) => ({
    title: (
      <span>
        {n.name}
        {!n.is_device ? <Tag style={{ marginLeft: 6 }}>目录</Tag> : <Tag color="blue">设备</Tag>}
      </span>
    ),
    key: n.device_id,
    dbId: n.id,
    isDevice: !!n.is_device,
    raw: n,
    children: n.children?.length ? mapTreeNodes(n.children) : undefined,
  }))
}

function findNodeByKey(nodes, key) {
  for (const node of nodes || []) {
    if (node.key === key) return node
    const c = findNodeByKey(node.children, key)
    if (c) return c
  }
  return null
}

export default function ProtocolManagerPage() {
  const [treeLoading, setTreeLoading] = useState(false)
  const [treeData, setTreeData] = useState([])
  const [expandedKeys, setExpandedKeys] = useState([])
  const [selectedKeys, setSelectedKeys] = useState([])

  const [selectedNode, setSelectedNode] = useState(null)
  const [protocolVersions, setProtocolVersions] = useState([])
  const [selectedPvId, setSelectedPvId] = useState(null)
  const [labels, setLabels] = useState([])
  const [labelsLoading, setLabelsLoading] = useState(false)
  const [bumpOnSave, setBumpOnSave] = useState(false)

  const [sysModal, setSysModal] = useState(false)
  const [devModal, setDevModal] = useState(false)
  const [sysForm] = Form.useForm()
  const [devForm] = Form.useForm()

  const [labelModal, setLabelModal] = useState({ open: false, initial: null })
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyRows, setHistoryRows] = useState([])
  const [snapshotOpen, setSnapshotOpen] = useState(false)
  const [snapshotRows, setSnapshotRows] = useState([])
  const [previewLabel, setPreviewLabel] = useState(null)

  const loadTree = useCallback(async () => {
    setTreeLoading(true)
    try {
      const res = await protocolManagerApi.getDeviceTree()
      const items = res.data?.items || []
      const mapped = mapTreeNodes(items)
      setTreeData(mapped)
      const allKeys = []
      const collect = (nodes) => {
        nodes.forEach((n) => {
          allKeys.push(n.key)
          if (n.children?.length) collect(n.children)
        })
      }
      collect(mapped)
      setExpandedKeys(allKeys)
    } catch {
      message.error('加载设备树失败')
    } finally {
      setTreeLoading(false)
    }
  }, [])

  useEffect(() => {
    loadTree()
  }, [loadTree])

  const loadProtocolVersionsAndLabels = useCallback(
    async (deviceId, rawDevice) => {
      setLabelsLoading(true)
      try {
        const vres = await protocolManagerApi.listProtocolVersions(deviceId)
        const vers = vres.data || []
        setProtocolVersions(vers)
        let pvId = null
        if (rawDevice?.current_version_name) {
          const m = vers.find((v) => v.version_name === rawDevice.current_version_name)
          if (m) pvId = m.id
        }
        if (pvId == null && vers.length) pvId = vers[0].id
        setSelectedPvId(pvId)
        const lres = await protocolManagerApi.getLabels(deviceId, pvId ?? undefined)
        setLabels(lres.data?.items || [])
      } catch (e) {
        message.error(e.response?.data?.detail || '加载协议版本或 Labels 失败')
        setProtocolVersions([])
        setLabels([])
      } finally {
        setLabelsLoading(false)
      }
    },
    []
  )

  const onTreeSelect = (keys) => {
    setSelectedKeys(keys)
    if (!keys.length) {
      setSelectedNode(null)
      setProtocolVersions([])
      setLabels([])
      return
    }
    const node = findNodeByKey(treeData, keys[0])
    if (!node) {
      setSelectedNode(null)
      return
    }
    setSelectedNode(node)
    if (node.isDevice) {
      loadProtocolVersionsAndLabels(node.key, node.raw)
    } else {
      setProtocolVersions([])
      setLabels([])
      setSelectedPvId(null)
    }
  }

  const refreshLabels = async () => {
    if (!selectedNode?.isDevice) return
    setLabelsLoading(true)
    try {
      const lres = await protocolManagerApi.getLabels(selectedNode.key, selectedPvId ?? undefined)
      setLabels(lres.data?.items || [])
    } catch {
      message.error('刷新 Labels 失败')
    } finally {
      setLabelsLoading(false)
    }
  }

  const handleSaveLabels = async () => {
    if (!selectedNode?.isDevice) return
    try {
      const payload = {
        labels: labels.map(({ id, ...rest }) => rest),
        protocol_version_id: selectedPvId,
        bump_version: bumpOnSave,
        change_summary: bumpOnSave ? '保存并递增版本' : '保存 Labels',
      }
      const res = await protocolManagerApi.saveLabels(selectedNode.key, payload)
      message.success(`已保存 ${res.data?.count ?? 0} 条${res.data?.new_version ? `，新版本 ${res.data.new_version}` : ''}`)
      setBumpOnSave(false)
      let nextRaw = selectedNode.raw
      if (res.data?.new_version) {
        nextRaw = {
          ...selectedNode.raw,
          current_version_name: res.data.new_version,
          device_version: res.data.new_version,
        }
        setSelectedNode((prev) => (prev ? { ...prev, raw: nextRaw } : prev))
      }
      await loadTree()
      await loadProtocolVersionsAndLabels(selectedNode.key, nextRaw)
    } catch (e) {
      message.error(e.response?.data?.detail || '保存失败')
    }
  }

  const handleSetActiveVersion = async (versionName) => {
    if (!selectedNode?.isDevice) return
    try {
      await protocolManagerApi.setActiveVersion(selectedNode.key, versionName)
      message.success('已切换当前工作版本')
      const raw = { ...selectedNode.raw, current_version_name: versionName }
      setSelectedNode({ ...selectedNode, raw })
      await loadProtocolVersionsAndLabels(selectedNode.key, raw)
      await loadTree()
    } catch (e) {
      message.error(e.response?.data?.detail || '切换失败')
    }
  }

  const openAddSystem = () => {
    sysForm.resetFields()
    setSysModal(true)
  }

  const submitSystem = async () => {
    try {
      const v = await sysForm.validateFields()
      await protocolManagerApi.createSystem({
        name: v.name,
        parent_id: v.parent_id ?? null,
        description: v.description || null,
      })
      message.success('已创建目录')
      setSysModal(false)
      loadTree()
    } catch (e) {
      if (e?.errorFields) return
      message.error(e.response?.data?.detail || '创建失败')
    }
  }

  const openAddDevice = () => {
    const folder = selectedNode && !selectedNode.isDevice ? selectedNode : null
    devForm.resetFields()
    if (folder) devForm.setFieldsValue({ parent_id: folder.dbId })
    setDevModal(true)
  }

  const submitDevice = async () => {
    try {
      const v = await devForm.validateFields()
      await protocolManagerApi.createDevice({
        name: v.name,
        parent_id: v.parent_id,
        device_id: v.device_id || undefined,
        description: v.description || undefined,
      })
      message.success('已创建设备')
      setDevModal(false)
      loadTree()
    } catch (e) {
      if (e?.errorFields) return
      message.error(e.response?.data?.detail || '创建失败')
    }
  }

  const deleteSelectedDevice = async () => {
    if (!selectedNode) return
    try {
      await protocolManagerApi.deleteDevice(selectedNode.key)
      message.success('已删除')
      setSelectedKeys([])
      setSelectedNode(null)
      setLabels([])
      setProtocolVersions([])
      loadTree()
    } catch (e) {
      message.error(e.response?.data?.detail || '删除失败')
    }
  }

  const mergeLabel = (payload) => {
    const editing = labelModal.initial
    if (editing && editing.id != null) {
      setLabels((prev) => prev.map((r) => (r.id === editing.id ? { ...r, ...payload } : r)))
    } else {
      setLabels((prev) => [...prev, { ...payload, id: `tmp_${Date.now()}` }])
    }
    setLabelModal({ open: false, initial: null })
  }

  const removeLabel = async (row) => {
    if (String(row.id).startsWith('tmp_')) {
      setLabels((prev) => prev.filter((r) => r.id !== row.id))
      return
    }
    try {
      await protocolManagerApi.deleteLabel(selectedNode.key, row.id)
      message.success('已删除')
      refreshLabels()
    } catch (e) {
      message.error(e.response?.data?.detail || '删除失败')
    }
  }

  const openHistory = async () => {
    if (!selectedNode?.isDevice) return
    try {
      const res = await protocolManagerApi.listHistory(selectedNode.key, 80)
      setHistoryRows(res.data || [])
      setHistoryOpen(true)
    } catch {
      message.error('加载历史失败')
    }
  }

  const viewSnapshot = async (version) => {
    if (!selectedNode?.isDevice) return
    try {
      const res = await protocolManagerApi.getSnapshotLabels(selectedNode.key, version)
      setSnapshotRows(res.data?.items || [])
      setSnapshotOpen(true)
    } catch {
      message.error('加载快照失败')
    }
  }

  const restoreSnapshot = async (version) => {
    if (!selectedNode?.isDevice) return
    try {
      await protocolManagerApi.restoreVersion(selectedNode.key, version)
      message.success('已恢复')
      setHistoryOpen(false)
      await loadProtocolVersionsAndLabels(selectedNode.key, selectedNode.raw)
      await loadTree()
    } catch (e) {
      message.error(e.response?.data?.detail || '恢复失败')
    }
  }

  const parentOptions = useMemo(() => {
    const out = []
    const walk = (nodes, depth = 0) => {
      nodes.forEach((n) => {
        if (!n.isDevice) {
          out.push({
            value: n.dbId,
            label: `${'　'.repeat(depth)}${n.raw?.name || n.key}`,
          })
          if (n.children?.length) walk(n.children, depth + 1)
        }
      })
    }
    walk(treeData)
    return out
  }, [treeData])

  const columns = [
    { title: '八进制', dataIndex: 'label_oct', width: 90 },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: '方向', dataIndex: 'direction', width: 100, ellipsis: true },
    { title: '类型', dataIndex: 'data_type', width: 90 },
    {
      title: '操作',
      key: 'op',
      width: 160,
      render: (_, row) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            onClick={() => {
              setPreviewLabel(row)
              setLabelModal({ open: true, initial: row })
            }}
          >
            编辑
          </Button>
          <Popconfirm title="删除此 Label？" onConfirm={() => removeLabel(row)}>
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 16, minHeight: '100%' }}>
      <Title level={4} style={{ color: '#c9d1d9', marginTop: 0 }}>
        协议管理
      </Title>
      <Text type="secondary">管理员维护设备树与 Label；与 TSN 网络配置（ICD）相互独立。</Text>

      <Layout style={{ marginTop: 16, background: 'transparent', minHeight: 520 }}>
        <Sider
          width={320}
          style={{
            background: '#161b22',
            border: '1px solid #30363d',
            borderRadius: 8,
            padding: 12,
            overflow: 'auto',
          }}
        >
          <Space wrap style={{ marginBottom: 8 }}>
            <Button size="small" icon={<ReloadOutlined />} onClick={loadTree} loading={treeLoading}>
              刷新
            </Button>
            <Button size="small" type="primary" icon={<FolderAddOutlined />} onClick={openAddSystem}>
              新建目录
            </Button>
            <Button size="small" icon={<PlusOutlined />} onClick={openAddDevice}>
              新建设备
            </Button>
          </Space>
          <Tree
            showLine
            treeData={treeData}
            expandedKeys={expandedKeys}
            onExpand={setExpandedKeys}
            selectedKeys={selectedKeys}
            onSelect={onTreeSelect}
          />
        </Sider>
        <Content style={{ marginLeft: 16, minWidth: 0 }}>
          <Card
            bordered={false}
            style={{
              background: '#161b22',
              border: '1px solid #30363d',
              minHeight: 480,
            }}
            styles={{ body: { padding: 16 } }}
          >
            {!selectedNode?.isDevice && (
              <Empty
                description={selectedNode ? '请选择叶子设备以编辑 Labels' : '在左侧选择设备或目录'}
                style={{ marginTop: 80 }}
              />
            )}
            {selectedNode?.isDevice && (
              <>
                <Space wrap align="center" style={{ marginBottom: 12 }}>
                  <Text strong style={{ color: '#c9d1d9', fontSize: 16 }}>
                    {selectedNode.raw?.name}
                  </Text>
                  <Text type="secondary" code>
                    {selectedNode.key}
                  </Text>
                  <Select
                    style={{ minWidth: 200 }}
                    placeholder="协议版本"
                    value={selectedPvId}
                    options={protocolVersions.map((v) => ({
                      value: v.id,
                      label: `${v.version_name} (${v.version})`,
                    }))}
                    onChange={async (v) => {
                      setSelectedPvId(v)
                      setLabelsLoading(true)
                      try {
                        const lres = await protocolManagerApi.getLabels(selectedNode.key, v)
                        setLabels(lres.data?.items || [])
                      } catch {
                        message.error('加载 Labels 失败')
                      } finally {
                        setLabelsLoading(false)
                      }
                    }}
                  />
                  <Button
                    size="small"
                    onClick={() => {
                      const ver = protocolVersions.find((x) => x.id === selectedPvId)
                      if (ver) handleSetActiveVersion(ver.version_name)
                    }}
                  >
                    设为当前工作版本
                  </Button>
                  <Button size="small" icon={<HistoryOutlined />} onClick={openHistory}>
                    版本历史
                  </Button>
                  <Popconfirm title="删除该设备及其子数据？" onConfirm={deleteSelectedDevice}>
                    <Button size="small" danger icon={<DeleteOutlined />}>
                      删除节点
                    </Button>
                  </Popconfirm>
                </Space>

                <Space wrap style={{ marginBottom: 12 }}>
                  <Button
                    type="primary"
                    icon={<PlusOutlined />}
                    onClick={() => setLabelModal({ open: true, initial: null })}
                  >
                    添加 Label
                  </Button>
                  <Button icon={<SaveOutlined />} onClick={handleSaveLabels}>
                    保存全部
                  </Button>
                  <Checkbox checked={bumpOnSave} onChange={(e) => setBumpOnSave(e.target.checked)}>
                    保存时递增新版本
                  </Checkbox>
                </Space>

                {previewLabel && (
                  <div style={{ marginBottom: 12, padding: 12, background: '#0d1117', borderRadius: 8 }}>
                    <Text type="secondary">选中预览位图：</Text>
                    <Text code>{previewLabel.label_oct}</Text>
                    <BitMapDisplay label={previewLabel} />
                  </div>
                )}

                <Table
                  rowKey={(r) => r.id}
                  loading={labelsLoading}
                  size="small"
                  columns={columns}
                  dataSource={labels}
                  pagination={{ pageSize: 12, showSizeChanger: true }}
                  scroll={{ x: 720 }}
                  onRow={(record) => ({
                    onClick: () => setPreviewLabel(record),
                  })}
                />
              </>
            )}
          </Card>
        </Content>
      </Layout>

      <Modal title="新建目录" open={sysModal} onOk={submitSystem} onCancel={() => setSysModal(false)} destroyOnClose>
        <Form form={sysForm} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="如 ATA32-起落架系统" />
          </Form.Item>
          <Form.Item name="parent_id" label="父目录（可选）">
            <Select allowClear options={parentOptions} placeholder="根目录" showSearch optionFilterProp="label" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="新建设备" open={devModal} onOk={submitDevice} onCancel={() => setDevModal(false)} destroyOnClose>
        <Form form={devForm} layout="vertical">
          <Form.Item name="parent_id" label="父目录" rules={[{ required: true, message: '请选择父目录' }]}>
            <Select options={parentOptions} placeholder="选择目录" showSearch optionFilterProp="label" />
          </Form.Item>
          <Form.Item name="name" label="设备名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="device_id" label="稳定 ID（可选）">
            <Input placeholder="留空则自动生成" />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <LabelEditModal
        open={labelModal.open}
        initial={labelModal.initial}
        onCancel={() => setLabelModal({ open: false, initial: null })}
        onOk={mergeLabel}
      />

      <Modal
        title="版本历史"
        open={historyOpen}
        onCancel={() => setHistoryOpen(false)}
        footer={null}
        width={800}
      >
        <Table
          size="small"
          rowKey={(r) => `${r.version}-${r.updated_at}`}
          dataSource={historyRows}
          columns={[
            { title: '版本标记', dataIndex: 'version', width: 120 },
            { title: '时间', dataIndex: 'updated_at', width: 180 },
            { title: '说明', dataIndex: 'change_summary', ellipsis: true },
            { title: '条数', dataIndex: 'label_count', width: 60 },
            {
              title: '操作',
              key: 'op',
              width: 180,
              render: (_, row) => (
                <Space>
                  <Button type="link" size="small" onClick={() => viewSnapshot(row.version)}>
                    查看快照
                  </Button>
                  <Popconfirm title="用此快照覆盖当前工作版本内容？" onConfirm={() => restoreSnapshot(row.version)}>
                    <Button type="link" size="small" danger>
                      恢复
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Modal>

      <Modal
        title="历史快照（只读）"
        open={snapshotOpen}
        onCancel={() => setSnapshotOpen(false)}
        footer={null}
        width={900}
      >
        <Table
          size="small"
          rowKey={(_, i) => String(i)}
          dataSource={snapshotRows}
          columns={[
            { title: '八进制', dataIndex: 'label_oct', width: 90 },
            { title: '名称', dataIndex: 'name', ellipsis: true },
            { title: '方向', dataIndex: 'direction', width: 100 },
            { title: '类型', dataIndex: 'data_type', width: 90 },
          ]}
        />
      </Modal>
    </div>
  )
}
