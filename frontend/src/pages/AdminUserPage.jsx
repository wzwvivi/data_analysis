import React, { useCallback, useEffect, useState } from 'react'
import { Card, Form, Input, Button, Select, Table, Tag, message, Popconfirm, Tooltip } from 'antd'
import { ReloadOutlined, DeleteOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { authApi } from '../services/api'
import { useAuth } from '../context/AuthContext'

function AdminUserPage() {
  const { user: currentUser } = useAuth()
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [deletingId, setDeletingId] = useState(null)
  const [form] = Form.useForm()

  const loadUsers = useCallback(async () => {
    setLoading(true)
    try {
      const res = await authApi.listUsers()
      setUsers(res.data || [])
    } catch {
      message.error('加载用户列表失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadUsers()
  }, [loadUsers])

  const handleCreate = async () => {
    try {
      const values = await form.validateFields()
      setCreating(true)
      await authApi.createUser({
        username: values.username,
        password: values.password,
        role: values.role,
      })
      message.success('用户创建成功')
      form.resetFields()
      form.setFieldsValue({ role: 'user' })
      loadUsers()
    } catch (e) {
      if (e?.errorFields) return
      message.error(e.response?.data?.detail || '创建用户失败')
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (record) => {
    setDeletingId(record.id)
    try {
      await authApi.deleteUser(record.id)
      message.success('已删除用户')
      loadUsers()
    } catch (e) {
      message.error(e.response?.data?.detail || '删除用户失败')
    } finally {
      setDeletingId(null)
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '用户名', dataIndex: 'username', width: 180 },
    {
      title: '角色',
      dataIndex: 'role',
      width: 120,
      render: (v) => (v === 'admin' ? <Tag color="gold">管理员</Tag> : <Tag>普通用户</Tag>),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 180,
      render: (v) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '—'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      fixed: 'right',
      render: (_, record) => {
        const isSelf = currentUser?.id === record.id
        if (isSelf) {
          return (
            <Tooltip title="不能删除当前登录账号">
              <Button type="link" danger size="small" icon={<DeleteOutlined />} disabled>
                删除
              </Button>
            </Tooltip>
          )
        }
        return (
          <Popconfirm
            title="确定删除该用户？"
            description="删除后该账号将无法登录"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true, loading: deletingId === record.id }}
            onConfirm={() => handleDelete(record)}
          >
            <Button
              type="link"
              danger
              size="small"
              icon={<DeleteOutlined />}
              loading={deletingId === record.id}
            >
              删除
            </Button>
          </Popconfirm>
        )
      },
    },
  ]

  return (
    <div className="fade-in">
      <Card
        title="用户管理"
        extra={(
          <Button icon={<ReloadOutlined />} onClick={loadUsers} loading={loading}>
            刷新用户
          </Button>
        )}
        style={{ marginBottom: 24 }}
      >
        <div style={{ color: '#8b949e', marginBottom: 16 }}>
          仅管理员可创建或删除账号。不能删除当前登录用户及最后一个管理员。
        </div>
        <Form
          form={form}
          layout="inline"
          initialValues={{ role: 'user' }}
          onFinish={handleCreate}
          style={{ marginBottom: 16, rowGap: 8 }}
        >
          <Form.Item
            name="username"
            label="用户名"
            rules={[
              { required: true, message: '请输入用户名' },
              { min: 1, max: 64, message: '用户名长度需在 1-64 之间' },
            ]}
          >
            <Input placeholder="请输入用户名" style={{ width: 220 }} maxLength={64} />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[
              { required: true, message: '请输入密码' },
              { min: 6, max: 128, message: '密码长度需在 6-128 之间' },
            ]}
          >
            <Input.Password placeholder="请输入密码" style={{ width: 240 }} maxLength={128} />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true, message: '请选择角色' }]}>
            <Select
              style={{ width: 140 }}
              options={[
                { label: '普通用户', value: 'user' },
                { label: '管理员', value: 'admin' },
              ]}
            />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={creating}>
              添加用户
            </Button>
          </Form.Item>
        </Form>

        <Table
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={users}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          scroll={{ x: 760 }}
        />
      </Card>
    </div>
  )
}

export default AdminUserPage
