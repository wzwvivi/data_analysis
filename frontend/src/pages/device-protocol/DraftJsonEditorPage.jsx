import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Card,
  Button,
  Input,
  Space,
  Tag,
  message,
  Descriptions,
  Modal,
  Alert,
  Tabs,
  Typography,
  Table,
  Empty,
  Form,
} from 'antd'
import {
  SaveOutlined,
  CheckCircleOutlined,
  DiffOutlined,
  SendOutlined,
  DeleteOutlined,
  ReloadOutlined,
  RollbackOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { deviceProtocolApi } from '../../services/api'
import { useAuth } from '../../context/AuthContext'
import Arinc429SpecEditor from './Arinc429SpecEditor'

const { Text } = Typography

const FAMILY_LABEL = { arinc429: 'ARINC 429', can: 'CAN', rs422: 'RS422' }


function DraftJsonEditorPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const canWrite = ['admin', 'device_team'].includes((user?.role || '').trim())

  const [draft, setDraft] = useState(null)
  const [jsonText, setJsonText] = useState('{}')
  const [jsonError, setJsonError] = useState('')
  const [dirty, setDirty] = useState(false)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  /** 当前编辑的 spec_json（优先由可视化编辑器维护，与 JSON text 同步） */
  const [specDraft, setSpecDraft] = useState({})
  const [useJson, setUseJson] = useState(false)
  /** 'list' = Label 卡片列表；'detail' = 单个 Label 详情。仅 arinc429 可视化编辑用到 */
  const [editorView, setEditorView] = useState('list')

  const [checkResult, setCheckResult] = useState(null)
  const [diffResult, setDiffResult] = useState(null)

  const [metaForm] = Form.useForm()

  const loadDraft = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await deviceProtocolApi.getDraft(id)
      setDraft(data)
      const initial = data.spec_json || {}
      setSpecDraft(initial)
      setJsonText(JSON.stringify(initial, null, 2))
      setJsonError('')
      setDirty(false)
      metaForm.setFieldsValue({
        name: data.name,
        description: data.description,
      })
    } catch (e) {
      message.error(e?.response?.data?.detail || '加载草稿失败')
    } finally {
      setLoading(false)
    }
  }, [id, metaForm])

  useEffect(() => { loadDraft() }, [loadDraft])

  const parsedJson = useMemo(() => {
    try {
      const obj = JSON.parse(jsonText)
      return { ok: true, obj }
    } catch (e) {
      return { ok: false, error: e.message }
    }
  }, [jsonText])

  useEffect(() => {
    setJsonError(parsedJson.ok ? '' : parsedJson.error)
  }, [parsedJson])

  const isEditable = draft?.status === 'draft' && canWrite

  const onTextChange = (val) => {
    setJsonText(val)
    setDirty(true)
    try {
      const obj = JSON.parse(val)
      setSpecDraft(obj)
    } catch {
      /* keep specDraft until valid */
    }
  }

  const onSpecDraftChange = (next) => {
    setSpecDraft(next)
    setJsonText(JSON.stringify(next, null, 2))
    setDirty(true)
  }

  const onSave = async () => {
    if (useJson && !parsedJson.ok) {
      message.error('JSON 格式有误，无法保存')
      return
    }
    const metaValues = await metaForm.validateFields().catch(() => null)
    if (!metaValues) return
    setSaving(true)
    try {
      await deviceProtocolApi.updateDraft(id, {
        spec_json: useJson ? parsedJson.obj : specDraft,
        name: metaValues.name,
        description: metaValues.description,
      })
      message.success('已保存')
      setDirty(false)
      loadDraft()
    } catch (e) {
      message.error(e?.response?.data?.detail || '保存失败')
      throw e
    } finally {
      setSaving(false)
    }
  }

  /**
   * 可视化编辑器内「保存 Label 并返回」的回调：
   * 只持久化 spec_json，不强制要求用户先填草稿名（已有 name 直接复用）。
   * 保存成功后交回给 Arinc429SpecEditor 退出详情视图。
   */
  const onSaveLabelFromEditor = async () => {
    setSaving(true)
    try {
      await deviceProtocolApi.updateDraft(id, {
        spec_json: specDraft,
      })
      message.success('Label 已保存')
      setDirty(false)
      // 后台返回的最新 spec 可能有轻微归一化，后台拉一次保持同步
      loadDraft()
    } catch (e) {
      message.error(e?.response?.data?.detail || '保存失败')
      throw e
    } finally {
      setSaving(false)
    }
  }

  const onCheck = async () => {
    try {
      const { data } = await deviceProtocolApi.checkDraft(id)
      setCheckResult(data)
      if (data?.validation?.summary?.is_ok) {
        message.success('静态检查通过')
      } else {
        message.warning(`存在 ${data.validation.summary.error_count} 个错误`)
      }
    } catch (e) {
      message.error(e?.response?.data?.detail || '检查失败')
    }
  }

  const onDiff = async () => {
    try {
      const { data } = await deviceProtocolApi.getDraftDiff(id)
      setDiffResult(data)
    } catch (e) {
      message.error(e?.response?.data?.detail || 'Diff 失败')
    }
  }

  const onSubmit = async () => {
    if (dirty) {
      message.warning('请先保存当前修改')
      return
    }
    Modal.confirm({
      title: '确认提交审批？',
      content: '提交后草稿锁定为 pending，等设备团队 / 网络团队 / TSN 开发团队 / 管理员逐级会签',
      onOk: async () => {
        try {
          await deviceProtocolApi.submitDraft(id)
          message.success('已提交审批')
          loadDraft()
        } catch (e) {
          message.error(e?.response?.data?.detail || '提交失败')
        }
      },
    })
  }

  const onDelete = () => {
    Modal.confirm({
      title: '确认删除草稿？',
      content: '仅 draft 态可删除；已提交 / 已发布不可删',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deviceProtocolApi.deleteDraft(id)
          message.success('已删除')
          navigate('/device-protocol')
        } catch (e) {
          message.error(e?.response?.data?.detail || '删除失败')
        }
      },
    })
  }

  if (loading && !draft) {
    return <Card loading />
  }
  if (!draft) return <Empty />

  // 是否处于"单个 Label 详情"编辑视图（仅 arinc429 可视化编辑才会置为 true）
  const inLabelDetail = draft.protocol_family === 'arinc429' && !useJson && editorView === 'detail'

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {!inLabelDetail && (
      <Card
        title={
          <Space>
            <Button icon={<RollbackOutlined />} onClick={() => navigate('/device-protocol')}>
              返回设备协议
            </Button>
            <Tag color="purple">{FAMILY_LABEL[draft.protocol_family] || draft.protocol_family}</Tag>
            <Text strong>{draft.name}</Text>
            <Tag color={
              { draft: 'default', pending: 'processing', approved: 'blue', published: 'green', rejected: 'red' }[draft.status]
            }>{draft.status}</Tag>
          </Space>
        }
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={loadDraft}>刷新</Button>
            {isEditable && (
              <>
                <Button icon={<CheckCircleOutlined />} onClick={onCheck}>静态检查</Button>
                <Button icon={<DiffOutlined />} onClick={onDiff}>查看 Diff</Button>
                <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={onSave} disabled={!parsedJson.ok}>
                  保存
                </Button>
                <Button icon={<SendOutlined />} onClick={onSubmit} disabled={dirty || !parsedJson.ok}>
                  提交审批
                </Button>
                <Button danger icon={<DeleteOutlined />} onClick={onDelete}>删除</Button>
              </>
            )}
          </Space>
        }
      >
        <Descriptions column={3} size="small" bordered>
          <Descriptions.Item label="协议族">{FAMILY_LABEL[draft.protocol_family] || draft.protocol_family}</Descriptions.Item>
          <Descriptions.Item label="来源">{draft.source_type}</Descriptions.Item>
          <Descriptions.Item label="基础版本">{draft.base_version_id ? `#${draft.base_version_id}` : '—'}</Descriptions.Item>
          <Descriptions.Item label="SpecID">{draft.spec_id || '—（新建设备）'}</Descriptions.Item>
          <Descriptions.Item label="创建人">{draft.created_by}</Descriptions.Item>
          <Descriptions.Item label="更新时间">{draft.updated_at ? dayjs(draft.updated_at).format('YYYY-MM-DD HH:mm') : '-'}</Descriptions.Item>
          <Descriptions.Item label="发布时版本号" span={3}>
            <Space>
              {draft.target_version ? (
                <Tag color="purple">{draft.target_version}</Tag>
              ) : (
                <Tag color="gold">审批通过后自动升级（如 V1.0 → V2.0）</Tag>
              )}
              <Text type="secondary" style={{ fontSize: 12 }}>
                一次草稿 = 一个设备 = 一次审批；版本号由系统在发布时自动计算
              </Text>
            </Space>
          </Descriptions.Item>
        </Descriptions>

        <Form form={metaForm} layout="vertical" style={{ marginTop: 16 }} disabled={!isEditable}>
          <Space size={16} wrap style={{ width: '100%' }}>
            <Form.Item name="name" label="草稿名" rules={[{ required: true }]} style={{ minWidth: 260 }}>
              <Input onChange={() => setDirty(true)} />
            </Form.Item>
            <Form.Item name="description" label="本次变更说明" style={{ flex: 1, minWidth: 320 }}>
              <Input onChange={() => setDirty(true)} placeholder="例：新增 Label 076 GNSS_Altitude" />
            </Form.Item>
          </Space>
        </Form>
      </Card>
      )}

      <Tabs
        activeKey={inLabelDetail ? 'editor' : undefined}
        renderTabBar={inLabelDetail ? () => null : undefined}
        items={[
          {
            key: 'editor',
            label: draft.protocol_family === 'arinc429'
              ? 'ARINC 429 可视化编辑'
              : `${FAMILY_LABEL[draft.protocol_family] || draft.protocol_family} · JSON 编辑`,
            children: draft.protocol_family === 'arinc429' && !useJson ? (
              // 这里始终是同一棵 React 树，不根据 inLabelDetail 切换，避免 Arinc429SpecEditor
              // 被卸载导致其内部 selectedOct/labelSnapshot 等状态丢失。
              <Card
                size="small"
                bordered={!inLabelDetail}
                title={inLabelDetail ? null : (
                  <Space>
                    <span>Label 编辑器</span>
                    {dirty && <Tag color="gold">未保存</Tag>}
                    {!dirty && <Tag color="green">已同步</Tag>}
                  </Space>
                )}
                extra={inLabelDetail ? null : (
                  <Button size="small" onClick={() => setUseJson(true)}>
                    切到 JSON 原始编辑
                  </Button>
                )}
                headStyle={inLabelDetail ? { display: 'none' } : undefined}
                bodyStyle={inLabelDetail ? { padding: 0, background: 'transparent' } : undefined}
                style={inLabelDetail ? { background: 'transparent', boxShadow: 'none' } : undefined}
              >
                {!inLabelDetail && !isEditable && (
                  <Alert type="info" showIcon style={{ marginBottom: 12 }} message="草稿非 draft 态或无写权限，此处只读" />
                )}
                <Arinc429SpecEditor
                  value={specDraft}
                  onChange={onSpecDraftChange}
                  readOnly={!isEditable}
                  onViewModeChange={setEditorView}
                  onSaveLabel={onSaveLabelFromEditor}
                  saveLabelLoading={saving}
                />
              </Card>
            ) : (
              <Card
                title="spec_json"
                size="small"
                extra={(
                  <Space>
                    {!parsedJson.ok && <Tag color="red">JSON 解析错误</Tag>}
                    {parsedJson.ok && dirty && <Tag color="gold">未保存</Tag>}
                    {parsedJson.ok && !dirty && <Tag color="green">已同步</Tag>}
                    {draft.protocol_family === 'arinc429' && (
                      <Button size="small" onClick={() => setUseJson(false)}>
                        回到可视化编辑
                      </Button>
                    )}
                  </Space>
                )}
              >
                {!isEditable && <Alert type="info" showIcon style={{ marginBottom: 12 }} message="草稿非 draft 态或无写权限，此处只读" />}
                <Input.TextArea
                  value={jsonText}
                  onChange={(e) => onTextChange(e.target.value)}
                  disabled={!isEditable}
                  rows={28}
                  style={{
                    fontFamily: 'Menlo, Monaco, Consolas, "Courier New", monospace',
                    fontSize: 12,
                    background: 'rgba(18,18,23,0.95)',
                    color: '#e4e4e7',
                  }}
                />
                {jsonError && <Alert style={{ marginTop: 8 }} type="error" showIcon message={`JSON: ${jsonError}`} />}
              </Card>
            ),
          },
          {
            key: 'check',
            label: `静态检查${checkResult ? ` (${checkResult.validation?.summary?.error_count || 0} 错 / ${checkResult.validation?.summary?.warning_count || 0} 警)` : ''}`,
            children: (
              <Card size="small">
                {!checkResult ? (
                  <Empty description="点击右上角'静态检查'运行" />
                ) : (
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    <Alert
                      type={checkResult.validation?.summary?.is_ok ? 'success' : 'error'}
                      showIcon
                      message={
                        checkResult.validation?.summary?.is_ok
                          ? '静态检查通过'
                          : `${checkResult.validation.summary.error_count} 错误, ${checkResult.validation.summary.warning_count} 警告`
                      }
                    />
                    {(checkResult.validation?.errors || []).length > 0 && (
                      <Card type="inner" size="small" title="错误">
                        {checkResult.validation.errors.map((e, i) => (
                          <div key={i} style={{ color: '#f87171', fontSize: 12 }}>· {e}</div>
                        ))}
                      </Card>
                    )}
                    {(checkResult.validation?.warnings || []).length > 0 && (
                      <Card type="inner" size="small" title="警告">
                        {checkResult.validation.warnings.map((e, i) => (
                          <div key={i} style={{ color: '#fbbf24', fontSize: 12 }}>· {e}</div>
                        ))}
                      </Card>
                    )}
                    <Card type="inner" size="small" title="摘要">
                      <pre style={{ color: '#d4d4d8', fontSize: 12 }}>{JSON.stringify(checkResult.summary || {}, null, 2)}</pre>
                    </Card>
                  </Space>
                )}
              </Card>
            ),
          },
          {
            key: 'diff',
            label: 'Diff',
            children: (
              <Card size="small">
                {!diffResult ? (
                  <Empty description="点击右上角'查看 Diff'" />
                ) : (
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    <Descriptions bordered size="small" column={4}>
                      <Descriptions.Item label="新增">{diffResult.summary?.added || 0}</Descriptions.Item>
                      <Descriptions.Item label="删除">{diffResult.summary?.removed || 0}</Descriptions.Item>
                      <Descriptions.Item label="变更">{diffResult.summary?.changed || 0}</Descriptions.Item>
                      <Descriptions.Item label="元信息">{diffResult.summary?.meta_changed || 0}</Descriptions.Item>
                    </Descriptions>
                    {(diffResult.items_added || []).length > 0 && (
                      <Card type="inner" size="small" title={`新增 (${diffResult.items_added.length})`}>
                        <Table
                          size="small" rowKey="key" pagination={{ pageSize: 10 }}
                          dataSource={diffResult.items_added}
                          columns={[{ title: 'Key', dataIndex: 'key' }, { title: '名称', dataIndex: 'name' }]}
                        />
                      </Card>
                    )}
                    {(diffResult.items_removed || []).length > 0 && (
                      <Card type="inner" size="small" title={`删除 (${diffResult.items_removed.length})`}>
                        <Table
                          size="small" rowKey="key" pagination={{ pageSize: 10 }}
                          dataSource={diffResult.items_removed}
                          columns={[{ title: 'Key', dataIndex: 'key' }, { title: '名称', dataIndex: 'name' }]}
                        />
                      </Card>
                    )}
                    {(diffResult.items_changed || []).length > 0 && (
                      <Card type="inner" size="small" title={`变更 (${diffResult.items_changed.length})`}>
                        <Table
                          size="small" rowKey="key" pagination={{ pageSize: 10 }}
                          dataSource={diffResult.items_changed}
                          columns={[
                            { title: 'Key', dataIndex: 'key' },
                            { title: '名称', dataIndex: 'name' },
                            {
                              title: '字段变化',
                              dataIndex: 'changes',
                              render: (c) => Object.keys(c || {}).join(', '),
                            },
                          ]}
                          expandable={{
                            expandedRowRender: (rec) => (
                              <pre style={{ color: '#d4d4d8', fontSize: 11 }}>{JSON.stringify(rec.changes, null, 2)}</pre>
                            ),
                          }}
                        />
                      </Card>
                    )}
                  </Space>
                )}
              </Card>
            ),
          },
        ]}
      />
    </Space>
  )
}

export default DraftJsonEditorPage
