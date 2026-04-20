import React, { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Card,
  Button,
  Space,
  Tag,
  Steps,
  Descriptions,
  Modal,
  message,
  Typography,
  Input,
  Alert,
} from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  RollbackOutlined,
  CloudUploadOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { deviceProtocolApi } from '../../services/api'
import { useAuth } from '../../context/AuthContext'

const { Text, Paragraph } = Typography

const STATUS_COLOR = {
  pending: 'processing',
  approved: 'blue',
  published: 'green',
  rejected: 'red',
}


function ChangeRequestPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [cr, setCr] = useState(null)
  const [loading, setLoading] = useState(false)

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

  if (!cr) return <Card loading={loading} />

  const chain = cr.chain_roles || []
  const currentStep = cr.current_step
  const currentRole = chain[currentStep]
  const myRole = (user?.role || '').trim()
  const canSignOff = cr.overall_status === 'pending' && (myRole === 'admin' || myRole === currentRole)
  const canPublish = cr.overall_status === 'approved' && myRole === 'admin'

  const onDecide = (decision) => {
    Modal.confirm({
      title: decision === 'approve' ? '确认通过会签？' : (decision === 'reject' ? '确认驳回？' : '确认要求修改？'),
      content: (
        <Input.TextArea id="cr-note" placeholder={decision === 'approve' ? '可填通过意见（可选）' : '请填写驳回理由'} rows={3} />
      ),
      onOk: async () => {
        const note = document.getElementById('cr-note')?.value || ''
        if (decision !== 'approve' && !note.trim()) {
          message.warning('请填写理由')
          throw new Error('need-note')
        }
        try {
          await deviceProtocolApi.signOffChangeRequest(id, { decision, note })
          message.success('已会签')
          load()
        } catch (e) {
          message.error(e?.response?.data?.detail || '操作失败')
        }
      },
    })
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
      description: entry?.approver
        ? `${entry.approver} · ${entry.decision}${entry.decided_at ? ` · ${dayjs(entry.decided_at).format('MM-DD HH:mm')}` : ''}`
        : '',
      status,
    }
  })

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
                <Button type="primary" icon={<CheckCircleOutlined />} onClick={() => onDecide('approve')}>
                  通过会签
                </Button>
                <Button danger icon={<CloseCircleOutlined />} onClick={() => onDecide('reject')}>驳回</Button>
                <Button onClick={() => onDecide('request_changes')}>要求修改</Button>
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
            <Space>
              <Text strong>{draft.name}</Text>
              <Tag>{draft.protocol_family}</Tag>
              <Text type="secondary">target {draft.target_version}</Text>
              <Tag>{draft.status}</Tag>
              <Button size="small" onClick={() => navigate(`/device-protocol/drafts/${draft.id}`)}>打开草稿</Button>
            </Space>
          </Descriptions.Item>
          {cr.final_note && (
            <Descriptions.Item label="终审/驳回说明" span={3}>{cr.final_note}</Descriptions.Item>
          )}
        </Descriptions>

        <Card type="inner" size="small" title="审批链" style={{ marginTop: 16 }}>
          <Steps current={Math.min(currentStep, chain.length)} items={stepItems} />
        </Card>
      </Card>

      <Card title="Diff 摘要" size="small">
        {cr.diff_summary?.summary ? (
          <Descriptions size="small" bordered column={4}>
            <Descriptions.Item label="新增">{cr.diff_summary.summary.added || 0}</Descriptions.Item>
            <Descriptions.Item label="删除">{cr.diff_summary.summary.removed || 0}</Descriptions.Item>
            <Descriptions.Item label="变更">{cr.diff_summary.summary.changed || 0}</Descriptions.Item>
            <Descriptions.Item label="元信息">{cr.diff_summary.summary.meta_changed || 0}</Descriptions.Item>
          </Descriptions>
        ) : (
          <Alert type="info" message="无 Diff（可能是全量新建）" showIcon />
        )}
        {cr.diff_summary && (
          <details style={{ marginTop: 12 }}>
            <summary style={{ cursor: 'pointer', color: '#a1a1aa' }}>查看原始 Diff JSON</summary>
            <pre style={{ color: '#d4d4d8', fontSize: 11 }}>{JSON.stringify(cr.diff_summary, null, 2)}</pre>
          </details>
        )}
      </Card>
    </Space>
  )
}

export default ChangeRequestPage
