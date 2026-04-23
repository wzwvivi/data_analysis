import React, { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Card,
  Button,
  Space,
  Tag,
  Descriptions,
  Table,
  message,
  Typography,
  Empty,
  Tabs,
} from 'antd'
import { RollbackOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { deviceProtocolApi } from '../../services/api'
import { useAuth } from '../../context/AuthContext'
import DeviceActivationPanel from './DeviceActivationPanel'

const { Text } = Typography

const FAMILY_LABEL = { arinc429: 'ARINC 429', can: 'CAN', rs422: 'RS422' }


function VersionViewerPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [version, setVersion] = useState(null)
  const [loading, setLoading] = useState(false)
  const role = (user?.role || '').trim()
  const isAdmin = role === 'admin'
  const canWrite = isAdmin || role === 'device_team'

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await deviceProtocolApi.getVersion(id)
      setVersion(data)
    } catch (e) {
      message.error(e?.response?.data?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { load() }, [load])

  if (!version) return <Card loading={loading} />

  const labels = version.labels_view || []
  const summary = version.summary || {}

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={
          <Space>
            <Button icon={<RollbackOutlined />} onClick={() => navigate('/device-protocol')}>返回</Button>
            <Tag color="purple">{FAMILY_LABEL[version.protocol_family] || version.protocol_family}</Tag>
            <Text strong>{version.device_name}</Text>
            <Text type="secondary" code>{version.device_id}</Text>
            <Tag color="purple">{version.version_name}</Tag>
            <Tag color={{ Available: 'green', PendingCode: 'gold', Deprecated: 'default' }[version.availability_status]}>
              {version.availability_status}
            </Tag>
          </Space>
        }
        extra={<Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>}
      >
        <Descriptions column={3} size="small" bordered>
          <Descriptions.Item label="序号">{version.version_seq}</Descriptions.Item>
          <Descriptions.Item label="发布人">{version.created_by || '-'}</Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {version.created_at ? dayjs(version.created_at).format('YYYY-MM-DD HH:mm') : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="Git 状态">
            <Tag color={{ exported: 'green', skipped: 'default', pending: 'default', failed: 'red' }[version.git_export_status]}>
              {version.git_export_status}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Commit">
            {version.git_commit_hash ? <Text code>{String(version.git_commit_hash).slice(0, 12)}</Text> : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="导出时间">
            {version.git_exported_at ? dayjs(version.git_exported_at).format('YYYY-MM-DD HH:mm') : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="描述" span={3}>
            {version.description || '-'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {version.availability_status === 'PendingCode' ? (
        <DeviceActivationPanel
          version={version}
          canWrite={canWrite}
          isAdmin={isAdmin}
          onActivated={load}
        />
      ) : null}

      <Tabs
        items={[
          {
            key: 'labels',
            label: version.protocol_family === 'arinc429'
              ? `Labels (${labels.length})`
              : `数据项 (${labels.length})`,
            children: (
              <Card size="small">
                {labels.length === 0 ? (
                  <Empty />
                ) : (
                  <Table
                    size="small"
                    rowKey="key"
                    dataSource={labels}
                    pagination={{ pageSize: 30, showSizeChanger: false }}
                    columns={buildColumns(version.protocol_family)}
                  />
                )}
              </Card>
            ),
          },
          {
            key: 'spec',
            label: '原始 spec_json',
            children: (
              <Card size="small">
                <pre style={{ color: '#d4d4d8', fontSize: 12, maxHeight: 600, overflow: 'auto' }}>
                  {JSON.stringify(version.spec_json || {}, null, 2)}
                </pre>
              </Card>
            ),
          },
        ]}
      />
    </Space>
  )
}


function buildColumns(family) {
  if (family === 'arinc429') {
    return [
      { title: 'Label(oct)', dataIndex: 'label_oct', width: 100 },
      { title: 'Dec', dataIndex: 'label_dec', width: 70 },
      { title: '名称', dataIndex: 'name' },
      { title: '方向', dataIndex: 'direction', width: 70 },
      { title: '数据类型', dataIndex: 'data_type', width: 110 },
      { title: '单位', dataIndex: 'unit', width: 90 },
    ]
  }
  if (family === 'can') {
    return [
      { title: 'Frame ID', dataIndex: 'frame_id_hex', width: 120 },
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

export default VersionViewerPage
