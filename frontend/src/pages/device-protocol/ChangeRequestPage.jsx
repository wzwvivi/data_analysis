import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Input,
  Modal,
  Space,
  Steps,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  CloudUploadOutlined,
  ReloadOutlined,
  RollbackOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { deviceProtocolApi } from '../../services/api'
import { useAuth } from '../../context/AuthContext'
import SpecDiffView from './components/SpecDiffView'

const { Text, Paragraph } = Typography

const STATUS_COLOR = {
  pending: 'processing',
  approved: 'blue',
  published: 'green',
  rejected: 'red',
}

const DECISION_COLOR = {
  pending: 'default',
  approve: 'green',
  reject: 'red',
  request_changes: 'orange',
}

const DECISION_LABEL = {
  pending: '待会签',
  approve: '同意',
  reject: '驳回',
  request_changes: '要求修改',
}

const FAMILY_LABEL = { arinc429: 'ARINC 429', can: 'CAN', rs422: 'RS422' }


function ChangeRequestPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [cr, setCr] = useState(null)
  const [loading, setLoading] = useState(false)

  const [signOffForm] = Form.useForm()
  const [signOffOpen, setSignOffOpen] = useState(false)
  const [signOffDecision, setSignOffDecision] = useState('approve')
  const [signOffLoading, setSignOffLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await deviceProtocolApi.getChangeRequest(id)
      setCr(data)
    } catch (e) {
      message.error(e?.response?.data?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { load() }, [load])

  const diff = useMemo(() => cr?.diff_summary || {}, [cr])

  if (!cr) return <Card loading={loading} />

  const chain = cr.chain_roles || []
  const currentStep = cr.current_step
  const currentRole = chain[currentStep]
  const myRole = (user?.role || '').trim()
  const canSignOff = cr.overall_status === 'pending' && (myRole === 'admin' || myRole === currentRole)
  const canPublish = cr.overall_status === 'approved' && myRole === 'admin'

  const openSignOff = (decision) => {
    setSignOffDecision(decision)
    signOffForm.resetFields()
    setSignOffOpen(true)
  }

  const handleSignOff = async () => {
    let values
    try {
      values = await signOffForm.validateFields()
    } catch {
      return
    }
    setSignOffLoading(true)
    try {
      await deviceProtocolApi.signOffChangeRequest(id, {
        decision: signOffDecision,
        note: (values.note || '').trim(),
      })
      message.success('已会签')
      setSignOffOpen(false)
      load()
    } catch (e) {
      message.error(e?.response?.data?.detail || '操作失败')
    } finally {
      setSignOffLoading(false)
    }
  }

  const onPublish = () => {
    Modal.confirm({
      title: '确认发布？',
      content: '发布后会物化为 PendingCode 版本，并触发 Git 导出（M1 为 Noop）。解析代码就绪后再由管理员激活。',
      onOk: async () => {
        try {
          const { data } = await deviceProtocolApi.publishChangeRequest(id)
          message.success(`已发布 version_id=${data.version_id}`)
          load()
        } catch (e) {
          message.error(e?.response?.data?.detail || '发布失败')
        }
      },
    })
  }

  const stepItems = chain.map((role, idx) => {
    const entry = cr.chain?.[idx]
    const decision = entry?.decision
    let status = 'wait'
    if (decision && decision !== 'pending') {
      status = decision === 'approve' ? 'finish' : 'error'
    } else if (idx === currentStep && cr.overall_status === 'pending') {
      status = 'process'
    }
    return {
      title: role,
      description: (
        <Space direction="vertical" size={0}>
          <Tag color={DECISION_COLOR[decision] || 'default'}>
            {DECISION_LABEL[decision] || decision || '待会签'}
          </Tag>
          {entry?.approver && <Text type="secondary" style={{ fontSize: 12 }}>{entry.approver}</Text>}
          {entry?.decided_at && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {dayjs(entry.decided_at).format('MM-DD HH:mm')}
            </Text>
          )}
          {entry?.note && <Text type="secondary" style={{ fontSize: 12 }}>{entry.note}</Text>}
        </Space>
      ),
      status,
    }
  })

  const timelineItems = [
    cr.submitted_at && {
      color: 'blue',
      children: (
        <div>
          <Text strong>提交审批</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {cr.submitted_by} · {dayjs(cr.submitted_at).format('YYYY-MM-DD HH:mm')}
          </Text>
          {cr.submit_note && (
            <div style={{ marginTop: 4, color: '#d4d4d8', fontSize: 12 }}>{cr.submit_note}</div>
          )}
        </div>
      ),
    },
    ...(cr.chain || [])
      .filter((s) => s.decision && s.decision !== 'pending')
      .map((s) => ({
        color: DECISION_COLOR[s.decision] === 'green' ? 'green' : DECISION_COLOR[s.decision] === 'red' ? 'red' : 'orange',
        children: (
          <div>
            <Text strong>{s.role}</Text>{' '}
            <Tag color={DECISION_COLOR[s.decision]}>{DECISION_LABEL[s.decision] || s.decision}</Tag>
            <br />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {s.approver || '-'}
              {s.decided_at ? ` · ${dayjs(s.decided_at).format('YYYY-MM-DD HH:mm')}` : ''}
            </Text>
            {s.note && <div style={{ marginTop: 4, color: '#d4d4d8', fontSize: 12 }}>{s.note}</div>}
          </div>
        ),
      })),
    cr.published_at && {
      color: 'green',
      children: (
        <div>
          <Text strong>发布</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {cr.published_by} · {dayjs(cr.published_at).format('YYYY-MM-DD HH:mm')}
          </Text>
          {cr.published_version_id && (
            <div style={{ marginTop: 4, fontSize: 12 }}>
              version_id = <Text code>{cr.published_version_id}</Text>
            </div>
          )}
        </div>
      ),
    },
  ].filter(Boolean)

  const draft = cr.device_draft || {}

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={
          <Space>
            <Button icon={<RollbackOutlined />} onClick={() => navigate('/device-protocol')}>返回</Button>
            <Text strong>设备协议审批 CR#{cr.id}</Text>
            <Tag color={STATUS_COLOR[cr.overall_status]}>{cr.overall_status}</Tag>
            <Tag>{cr.draft_kind}</Tag>
          </Space>
        }
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
            {canSignOff && (
              <>
                <Button type="primary" icon={<CheckCircleOutlined />} onClick={() => openSignOff('approve')}>
                  通过会签
                </Button>
                <Button danger icon={<CloseCircleOutlined />} onClick={() => openSignOff('reject')}>驳回</Button>
                <Button onClick={() => openSignOff('request_changes')}>要求修改</Button>
              </>
            )}
            {canPublish && (
              <Button type="primary" icon={<CloudUploadOutlined />} onClick={onPublish}>
                管理员发布
              </Button>
            )}
          </Space>
        }
      >
        <Descriptions size="small" column={3} bordered>
          <Descriptions.Item label="提交人">{cr.submitted_by}</Descriptions.Item>
          <Descriptions.Item label="提交时间">
            {cr.submitted_at ? dayjs(cr.submitted_at).format('YYYY-MM-DD HH:mm') : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="当前步骤">
            {currentRole ? <Tag color="processing">{currentRole}</Tag> : <Tag color="green">已走完</Tag>}
          </Descriptions.Item>
          <Descriptions.Item label="草稿" span={3}>
            <Space wrap>
              <Text strong>{draft.name}</Text>
              <Tag color="blue">{FAMILY_LABEL[draft.protocol_family] || draft.protocol_family}</Tag>
              {draft.target_version && <Text type="secondary">target {draft.target_version}</Text>}
              <Tag>{draft.status}</Tag>
              <Button size="small" onClick={() => navigate(`/device-protocol/drafts/${draft.id}`)}>打开草稿</Button>
            </Space>
          </Descriptions.Item>
          {cr.submit_note && (
            <Descriptions.Item label="提交说明" span={3}>
              <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{cr.submit_note}</Paragraph>
            </Descriptions.Item>
          )}
          {cr.final_note && (
            <Descriptions.Item label="终审/驳回说明" span={3}>
              <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{cr.final_note}</Paragraph>
            </Descriptions.Item>
          )}
        </Descriptions>

        <Card type="inner" size="small" title="审批链" style={{ marginTop: 16 }}>
          <Steps current={Math.min(currentStep, chain.length)} items={stepItems} />
        </Card>
      </Card>

      <Card title="Diff 详情" size="small">
        <SpecDiffView diff={diff} emptyHint="无 Diff（可能是全量新建）" />
      </Card>

      <Card title="审批历史" size="small">
        {timelineItems.length === 0 ? (
          <Empty description="暂无审批记录" />
        ) : (
          <Timeline items={timelineItems} />
        )}
      </Card>

      <Modal
        title={`会签：${DECISION_LABEL[signOffDecision] || signOffDecision}`}
        open={signOffOpen}
        onCancel={() => (signOffLoading ? null : setSignOffOpen(false))}
        onOk={handleSignOff}
        confirmLoading={signOffLoading}
        okButtonProps={{
          danger: signOffDecision !== 'approve',
          type: signOffDecision === 'approve' ? 'primary' : 'default',
        }}
        destroyOnClose
      >
        <Form form={signOffForm} layout="vertical" preserve={false}>
          <Form.Item
            name="note"
            label={signOffDecision === 'approve' ? '会签说明（可选）' : '理由（必填）'}
            rules={
              signOffDecision !== 'approve'
                ? [{ required: true, message: '驳回 / 要求修改需要填写原因' }]
                : []
            }
          >
            <Input.TextArea
              rows={4}
              maxLength={2000}
              showCount
              placeholder={
                signOffDecision === 'approve'
                  ? '可填通过意见，会留在审批历史'
                  : '请详细描述驳回原因或希望调整的内容'
              }
            />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}

export default ChangeRequestPage
