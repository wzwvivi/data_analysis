import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Input,
  Modal,
  Space,
  Steps,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  CheckOutlined,
  CloseOutlined,
  EditOutlined,
  ReloadOutlined,
  SendOutlined,
  RocketOutlined,
} from '@ant-design/icons'
import { networkConfigApi } from '../../services/api'
import { useAuth } from '../../context/AuthContext'

const { Text, Paragraph, Title } = Typography

const ROLE_LABEL = {
  network_team: 'TSN/网络团队',
  device_team: '设备团队',
  // 历史审批记录兼容：旧 dev_tsn 节点统一显示为 TSN/网络团队
  dev_tsn: 'TSN/网络团队',
  admin: '管理员',
}

const DECISION_LABEL = {
  pending: '待处理',
  approve: '已通过',
  reject: '已驳回',
  request_changes: '要求修改',
}

const DECISION_COLOR = {
  pending: 'default',
  approve: 'success',
  reject: 'error',
  request_changes: 'warning',
}

const STATUS_META = {
  pending: { color: 'processing', label: '审批中' },
  rejected: { color: 'error', label: '已驳回' },
  approved: { color: 'warning', label: '已通过待发布' },
  published: { color: 'success', label: '已发布' },
}

function ChangeRequestPage() {
  const { id: crId } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()

  const [loading, setLoading] = useState(false)
  const [cr, setCr] = useState(null)
  const [signOffOpen, setSignOffOpen] = useState(false)
  const [signOffDecision, setSignOffDecision] = useState('approve')
  const [signOffForm] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await networkConfigApi.getChangeRequest(crId)
      setCr(res.data)
    } catch (err) {
      message.error(err?.response?.data?.detail || '加载审批单失败')
    } finally {
      setLoading(false)
    }
  }, [crId])

  useEffect(() => { load() }, [load])

  const userRole = (user?.role || '').trim()
  const isAdmin = userRole === 'admin'

  const stepOfMe = useMemo(() => {
    if (!cr) return null
    if (cr.overall_status !== 'pending') return null
    const chain = cr.chain || []
    const step = chain.find((s) => s.step_index === cr.current_step)
    if (!step) return null
    if (step.role === userRole || isAdmin) return step
    return null
  }, [cr, userRole, isAdmin])

  const canPublish = cr?.overall_status === 'approved' && isAdmin

  const openSignOff = (decision) => {
    setSignOffDecision(decision)
    signOffForm.resetFields()
    setSignOffOpen(true)
  }

  const handleSignOff = async () => {
    try {
      const values = await signOffForm.validateFields()
      await networkConfigApi.signOffChangeRequest(crId, {
        decision: signOffDecision,
        note: values.note,
      })
      message.success('提交成功')
      setSignOffOpen(false)
      load()
    } catch (err) {
      if (err?.errorFields) return
      message.error(err?.response?.data?.detail || '操作失败')
    }
  }

  const handlePublish = async () => {
    Modal.confirm({
      title: '发布新版本？',
      content: '发布后将在 ProtocolVersion 中登记为 PendingCode，终端用户不可见；需后端代码就绪后由管理员激活（MR3）。',
      okText: '确认发布',
      onOk: async () => {
        try {
          const res = await networkConfigApi.publishChangeRequest(crId)
          message.success(`已发布为版本 #${res.data.protocol_version_id}（PendingCode）`)
          load()
        } catch (err) {
          message.error(err?.response?.data?.detail || '发布失败')
        }
      },
    })
  }

  if (!cr) {
    return loading ? (
      <div style={{ padding: 100, textAlign: 'center', color: '#a1a1aa' }}>加载中…</div>
    ) : <Empty description="审批单不存在" />
  }

  const statusMeta = STATUS_META[cr.overall_status] || { color: 'default', label: cr.overall_status }
  const diff = cr.diff_summary || {}

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Space wrap>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/network-config')}>返回</Button>
            <Title level={4} style={{ margin: 0 }}>审批单 #{cr.id}</Title>
            <Tag color={statusMeta.color}>{statusMeta.label}</Tag>
          </Space>
          <Descriptions size="small" column={3}>
            <Descriptions.Item label="草稿">
              {cr.draft?.name} (v{cr.draft?.target_version})
              {cr.draft_id && (
                <Button
                  size="small"
                  type="link"
                  icon={<EditOutlined />}
                  onClick={() => navigate(`/network-config/drafts/${cr.draft_id}`)}
                >
                  查看草稿
                </Button>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="提交人">{cr.submitted_by || '-'}</Descriptions.Item>
            <Descriptions.Item label="提交时间">{cr.submitted_at ? String(cr.submitted_at) : '-'}</Descriptions.Item>
          </Descriptions>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
            {stepOfMe && (
              <>
                <Button type="primary" icon={<CheckOutlined />} onClick={() => openSignOff('approve')}>
                  同意（我代表 {ROLE_LABEL[stepOfMe.role] || stepOfMe.role}）
                </Button>
                <Button icon={<EditOutlined />} onClick={() => openSignOff('request_changes')}>
                  要求修改
                </Button>
                <Button danger icon={<CloseOutlined />} onClick={() => openSignOff('reject')}>
                  驳回
                </Button>
              </>
            )}
            {canPublish && (
              <Button type="primary" icon={<RocketOutlined />} onClick={handlePublish}>
                发布为 PendingCode
              </Button>
            )}
          </Space>
          {cr.final_note && (
            <Alert type="info" showIcon message={`终审/驳回备注：${cr.final_note}`} />
          )}
        </Space>
      </Card>

      <Card title="审批链" style={{ marginBottom: 16 }}>
        <Steps
          current={cr.current_step}
          status={cr.overall_status === 'rejected' ? 'error' : (cr.overall_status === 'published' ? 'finish' : 'process')}
          items={(cr.chain || []).map((s) => ({
            title: ROLE_LABEL[s.role] || s.role,
            description: (
              <Space direction="vertical" size={0}>
                <Tag color={DECISION_COLOR[s.decision]}>{DECISION_LABEL[s.decision] || s.decision}</Tag>
                {s.approver && <Text type="secondary" style={{ fontSize: 12 }}>{s.approver}</Text>}
                {s.note && <Text type="secondary" style={{ fontSize: 12 }}>{s.note}</Text>}
              </Space>
            ),
          }))}
        />
      </Card>

      <Card title="Diff 摘要">
        <Tabs items={[
          {
            key: 'ports',
            label: `端口变更 (新增 ${diff.ports_added?.length || 0} / 删除 ${diff.ports_removed?.length || 0} / 改 ${diff.ports_property_changed?.length || 0})`,
            children: (
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <Card size="small" title={`新增 (${diff.ports_added?.length || 0})`}>
                  {(diff.ports_added || []).map((p) => (
                    <Tag color="green" key={p.port_number}>{p.port_number} / {p.message_name}</Tag>
                  ))}
                  {(!diff.ports_added || diff.ports_added.length === 0) && <Text type="secondary">无</Text>}
                </Card>
                <Card size="small" title={`删除 (${diff.ports_removed?.length || 0})`}>
                  {(diff.ports_removed || []).map((p) => (
                    <Tag color="red" key={p.port_number}>{p.port_number} / {p.message_name}</Tag>
                  ))}
                  {(!diff.ports_removed || diff.ports_removed.length === 0) && <Text type="secondary">无</Text>}
                </Card>
                <Card size="small" title={`属性变更 (${diff.ports_property_changed?.length || 0})`}>
                  {(diff.ports_property_changed || []).map((c) => (
                    <div key={c.port_number} style={{ marginBottom: 6 }}>
                      <Tag>{c.port_number}</Tag>
                      {Object.entries(c.changes || {}).map(([k, v]) => (
                        <Text key={k} style={{ marginLeft: 8, fontSize: 12 }}>
                          <Text type="secondary">{k}:</Text>{' '}
                          <Text delete>{String(v.old ?? '')}</Text>{' → '}
                          <Text code>{String(v.new ?? '')}</Text>
                        </Text>
                      ))}
                    </div>
                  ))}
                  {(!diff.ports_property_changed || diff.ports_property_changed.length === 0) && <Text type="secondary">无</Text>}
                </Card>
              </Space>
            ),
          },
          {
            key: 'fields',
            label: `字段变更 (新增 ${diff.fields_added?.length || 0} / 删除 ${diff.fields_removed?.length || 0} / 改 ${diff.fields_changed?.length || 0})`,
            children: (
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <Card size="small" title={`新增 (${diff.fields_added?.length || 0})`}>
                  <Paragraph type="secondary">
                    {(diff.fields_added || []).map((f) => `${f.port_number}·${f.field_name}`).join(', ') || '无'}
                  </Paragraph>
                </Card>
                <Card size="small" title={`删除 (${diff.fields_removed?.length || 0})`}>
                  <Paragraph type="secondary">
                    {(diff.fields_removed || []).map((f) => `${f.port_number}·${f.field_name}`).join(', ') || '无'}
                  </Paragraph>
                </Card>
                <Card size="small" title={`字段属性变更 (${diff.fields_changed?.length || 0})`}>
                  {(diff.fields_changed || []).map((c, idx) => (
                    <div key={`${c.port_number}-${c.field_name}-${idx}`} style={{ marginBottom: 6 }}>
                      <Tag>{c.port_number}·{c.field_name}</Tag>
                      {Object.entries(c.changes || {}).map(([k, v]) => (
                        <Text key={k} style={{ marginLeft: 8, fontSize: 12 }}>
                          <Text type="secondary">{k}:</Text>{' '}
                          <Text delete>{String(v.old ?? '')}</Text>{' → '}
                          <Text code>{String(v.new ?? '')}</Text>
                        </Text>
                      ))}
                    </div>
                  ))}
                  {(!diff.fields_changed || diff.fields_changed.length === 0) && <Text type="secondary">无</Text>}
                </Card>
              </Space>
            ),
          },
        ]} />
      </Card>

      <Modal
        title={`会签：${signOffDecision === 'approve' ? '同意' : (signOffDecision === 'reject' ? '驳回' : '要求修改')}`}
        open={signOffOpen}
        onCancel={() => setSignOffOpen(false)}
        onOk={handleSignOff}
        okButtonProps={{
          danger: signOffDecision !== 'approve',
          type: signOffDecision === 'approve' ? 'primary' : 'default',
        }}
      >
        <Form form={signOffForm} layout="vertical">
          <Form.Item
            name="note"
            label="会签说明"
            rules={signOffDecision !== 'approve' ? [{ required: true, message: '驳回 / 要求修改需要填写原因' }] : []}
          >
            <Input.TextArea rows={4} placeholder="审批意见、原因或后续行动" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default ChangeRequestPage
