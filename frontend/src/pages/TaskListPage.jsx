import React, { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, Table, Tag, Button, Space, message, Tooltip, Progress
} from 'antd'
import {
  EyeOutlined, LineChartOutlined, ReloadOutlined,
  CheckCircleOutlined, ClockCircleOutlined, LoadingOutlined, CloseCircleOutlined
} from '@ant-design/icons'
import { parseApi } from '../services/api'
import dayjs from 'dayjs'

function TaskListPage() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(false)
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 20,
    total: 0,
  })

  const loadTasks = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const res = await parseApi.listTasks(pagination.current, pagination.pageSize)
      setTasks(res.data.items || [])
      setPagination(prev => ({ ...prev, total: res.data.total }))
    } catch (err) {
      if (!silent) message.error('加载任务列表失败')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [pagination.current, pagination.pageSize])

  useEffect(() => {
    loadTasks(false)
  }, [loadTasks])

  useEffect(() => {
    const hasActive = tasks.some(t => t.status === 'pending' || t.status === 'processing')
    if (!hasActive) return undefined
    const id = setInterval(() => loadTasks(true), 3000)
    return () => clearInterval(id)
  }, [tasks, loadTasks])

  const renderStatus = (_, record) => {
    const status = record.status
    const statusMap = {
      pending: { color: 'default', icon: <ClockCircleOutlined />, text: '等待中' },
      processing: { color: 'processing', icon: <LoadingOutlined />, text: '解析中' },
      completed: { color: 'success', icon: <CheckCircleOutlined />, text: '已完成' },
      failed: { color: 'error', icon: <CloseCircleOutlined />, text: '失败' },
    }
    const config = statusMap[status] || statusMap.pending
    const pct = typeof record.progress === 'number' ? record.progress : 0
    return (
      <Space direction="vertical" size={6} style={{ width: '100%', minWidth: 140 }}>
        <Tag color={config.color} icon={config.icon}>
          {config.text}
        </Tag>
        {(status === 'processing' || status === 'pending') && (
          <Progress
            percent={status === 'pending' ? 0 : pct}
            size="small"
            status={status === 'pending' ? 'normal' : 'active'}
            showInfo
            format={(p) => `${p ?? 0}%`}
          />
        )}
      </Space>
    )
  }

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 80,
      render: (id) => <span className="mono">#{id}</span>,
    },
    {
      title: '文件名',
      dataIndex: 'filename',
      ellipsis: true,
      render: (filename) => (
        <Tooltip title={filename}>
          <span className="mono">{filename}</span>
        </Tooltip>
      ),
    },
    {
      title: '网络配置',
      key: 'network_config',
      width: 180,
      render: (_, record) => (
        record.network_config_name ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
            <span>{record.network_config_name}</span>
            <Tag color="cyan" style={{ margin: 0, background: 'rgba(56, 189, 248, 0.15)', borderColor: '#38bdf8', color: '#38bdf8' }}>{record.network_config_version}</Tag>
          </div>
        ) : (
          <Tag style={{ background: '#21262d', borderColor: '#30363d', color: '#8b949e' }}>扫描模式</Tag>
        )
      ),
    },
    {
      title: '设备 / 解析器',
      key: 'parser_profile',
      width: 320,
      render: (_, record) => {
        if (record.device_parsers && record.device_parsers.length > 0) {
          return (
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              {record.device_parsers.map(dp => (
                <div key={dp.device_name} style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                  <Tag color="orange" style={{ margin: 0, background: 'rgba(210, 153, 34, 0.15)', borderColor: '#d29922', color: '#d29922' }}>{dp.device_name}</Tag>
                  <Tag color="green" style={{ margin: 0, background: 'rgba(63, 185, 80, 0.15)', borderColor: '#3fb950', color: '#3fb950' }}>{[dp.parser_profile_name, dp.parser_profile_version].filter(Boolean).join(' ')}</Tag>
                </div>
              ))}
            </Space>
          )
        }
        return (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', alignItems: 'center' }}>
            <span style={{ fontWeight: 500 }}>{record.parser_profile_name || '-'}</span>
            {record.parser_profile_version && (
              <Tag color="green" style={{ margin: 0, background: 'rgba(63, 185, 80, 0.15)', borderColor: '#3fb950', color: '#3fb950' }}>{record.parser_profile_version}</Tag>
            )}
          </div>
        )
      },
    },
    {
      title: '状态',
      key: 'status',
      width: 200,
      render: renderStatus,
    },
    {
      title: '解析数据量',
      dataIndex: 'parsed_packets',
      width: 120,
      render: (count) => (
        <span className="mono" style={{ color: '#3fb950' }}>
          {count?.toLocaleString() || 0}
        </span>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 180,
      render: (time) => dayjs(time).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 180,
      render: (_, record) => (
        <Space>
          <Button
            type="link"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/tasks/${record.id}`)}
          >
            查看
          </Button>
          <Button
            type="link"
            icon={<LineChartOutlined />}
            onClick={() => navigate(`/tasks/${record.id}/analysis`)}
            disabled={record.status !== 'completed'}
          >
            分析
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div className="fade-in">
      <Card
        title="解析任务列表"
        extra={
          <Button
            icon={<ReloadOutlined />}
            onClick={loadTasks}
            loading={loading}
          >
            刷新
          </Button>
        }
      >
        <Table
          columns={columns}
          dataSource={tasks}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1200 }}
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              setPagination(prev => ({ ...prev, current: page, pageSize }))
            },
          }}
        />
      </Card>
    </div>
  )
}

export default TaskListPage
