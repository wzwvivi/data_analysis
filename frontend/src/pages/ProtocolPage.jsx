import React, { useState, useEffect } from 'react'
import {
  Card, Table, Button, Space, message, Tag, Collapse, Empty
} from 'antd'
import {
  ReloadOutlined, ApiOutlined
} from '@ant-design/icons'
import { protocolApi } from '../services/api'
import dayjs from 'dayjs'

function ProtocolPage() {
  const [protocols, setProtocols] = useState([])
  const [loading, setLoading] = useState(false)
  const [expandedProtocol, setExpandedProtocol] = useState(null)
  const [ports, setPorts] = useState([])
  const [portsLoading, setPortsLoading] = useState(false)

  useEffect(() => {
    loadProtocols()
  }, [])

  const loadProtocols = async () => {
    setLoading(true)
    try {
      const res = await protocolApi.list()
      setProtocols(res.data.items || [])
    } catch (err) {
      message.error('加载网络配置列表失败')
    } finally {
      setLoading(false)
    }
  }

  const loadPorts = async (versionId) => {
    setPortsLoading(true)
    try {
      const res = await protocolApi.getPorts(versionId)
      setPorts(res.data.items || [])
    } catch (err) {
      message.error('加载端口列表失败')
    } finally {
      setPortsLoading(false)
    }
  }

  const portColumns = [
    {
      title: '端口号',
      dataIndex: 'port_number',
      width: 100,
      render: (port) => <span className="mono" style={{ color: '#d4a843' }}>{port}</span>,
    },
    {
      title: '消息名称',
      dataIndex: 'message_name',
      ellipsis: true,
    },
    {
      title: '源设备',
      dataIndex: 'source_device',
      ellipsis: true,
    },
    {
      title: '方向',
      dataIndex: 'data_direction',
      width: 100,
      render: (dir) => {
        const colorMap = {
          uplink: 'green',
          downlink: 'blue',
          network: 'purple',
        }
        return dir ? <Tag color={colorMap[dir] || 'default'}>{dir}</Tag> : '-'
      },
    },
    {
      title: '组播IP',
      dataIndex: 'multicast_ip',
      width: 140,
      render: (ip) => ip ? <span className="mono">{ip}</span> : '-',
    },
    {
      title: '周期(ms)',
      dataIndex: 'period_ms',
      width: 100,
      render: (period) => period ? <span className="mono">{period}</span> : '-',
    },
    {
      title: '字段数',
      dataIndex: 'field_count',
      width: 80,
      render: (count) => <Tag>{count}</Tag>,
    },
  ]

  return (
    <div className="fade-in">
      <Card
        title={
          <Space>
            <ApiOutlined style={{ color: '#d4a843' }} />
            <span>TSN网络配置管理</span>
          </Space>
        }
        extra={
          <Space>
            <Button
              icon={<ReloadOutlined />}
              onClick={loadProtocols}
              loading={loading}
            >
              刷新
            </Button>
          </Space>
        }
      >
        {protocols.length === 0 ? (
          <Empty
            description="暂无内置 TSN ICD v6.0.1 网络配置"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        ) : (
          <Collapse
            accordion
            onChange={(key) => {
              if (key) {
                const [protocolId, versionId] = key.split('-')
                loadPorts(versionId)
              }
              setExpandedProtocol(key)
            }}
            activeKey={expandedProtocol}
          >
            {protocols.map(protocol => (
              protocol.versions.map(version => (
                <Collapse.Panel
                  key={`${protocol.id}-${version.id}`}
                  header={
                    <Space>
                      <span style={{ fontWeight: 600 }}>{protocol.name}</span>
                      <Tag color="blue">{version.version}</Tag>
                      <Tag color="green">{version.port_count} 个端口</Tag>
                      {version.source_file && (
                        <span style={{ color: '#a1a1aa', fontSize: 12 }}>
                          来源: {version.source_file}
                        </span>
                      )}
                      <span style={{ color: '#a1a1aa', fontSize: 12 }}>
                        {dayjs(version.created_at).format('YYYY-MM-DD HH:mm')}
                      </span>
                    </Space>
                  }
                >
                  <Table
                    columns={portColumns}
                    dataSource={ports}
                    rowKey="id"
                    loading={portsLoading}
                    size="small"
                    pagination={{
                      pageSize: 20,
                      showSizeChanger: true,
                      showTotal: (total) => `共 ${total} 个端口`,
                    }}
                  />
                </Collapse.Panel>
              ))
            ))}
          </Collapse>
        )}
      </Card>
    </div>
  )
}

export default ProtocolPage
