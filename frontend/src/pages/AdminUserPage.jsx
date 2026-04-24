import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Card, Form, Input, Button, Select, Table, Tag, message, Popconfirm, Tooltip, Tabs, Modal } from 'antd'
import { ReloadOutlined, DeleteOutlined, KeyOutlined, TeamOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { authApi, roleConfigApi, protocolApi } from '../services/api'
import { useAuth } from '../context/AuthContext'
import { ROLE_LABELS, ROLE_OPTIONS } from '../constants/roles'
import AppPageHeader from '../components/AppPageHeader'

function AdminUserPage() {
  const { user: currentUser } = useAuth()
  const [users, setUsers] = useState([])
  const [legacyUsers, setLegacyUsers] = useState([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [deletingId, setDeletingId] = useState(null)
  const [savingRoleId, setSavingRoleId] = useState(null)
  const [roles, setRoles] = useState([])
  const [resetPwdUser, setResetPwdUser] = useState(null)
  const [resetPwdLoading, setResetPwdLoading] = useState(false)
  const [resetPwdForm] = Form.useForm()
  const [versions, setVersions] = useState([])
  const [rolePortRole, setRolePortRole] = useState('data_manager_tsn')
  const [rolePortVersionId, setRolePortVersionId] = useState(null)
  const [allPorts, setAllPorts] = useState([])
  const [selectedPorts, setSelectedPorts] = useState([])
  const [loadingRolePorts, setLoadingRolePorts] = useState(false)
  const [savingRolePorts, setSavingRolePorts] = useState(false)
  const [form] = Form.useForm()

  const loadUsers = useCallback(async () => {
    setLoading(true)
    try {
      const [allRes, legacyRes] = await Promise.all([
        authApi.listUsers(),
        authApi.listLegacyRoleUsers().catch(() => ({ data: { users: [] } })),
      ])
      setUsers(allRes.data || [])
      setLegacyUsers(legacyRes.data?.users || [])
    } catch {
      message.error('加载用户列表失败')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadRoles = useCallback(async () => {
    try {
      const res = await authApi.listRoles()
      const fromApi = res.data?.roles || []
      setRoles(fromApi)
    } catch {
      setRoles(ROLE_OPTIONS.map(o => ({ key: o.value, name: o.label, description: '' })))
    }
  }, [])

  const loadVersions = useCallback(async () => {
    try {
      const res = await protocolApi.listVersions()
      const items = res.data?.items || []
      setVersions(items)
      if (items.length > 0 && !rolePortVersionId) {
        setRolePortVersionId(items[0].id)
      }
    } catch {
      setVersions([])
    }
  }, [rolePortVersionId])

  useEffect(() => {
    loadUsers()
    loadRoles()
    loadVersions()
  }, [loadUsers, loadRoles, loadVersions])

  const roleOptions = useMemo(() => {
    if (roles.length > 0) {
      return roles.map(r => ({ value: r.key, label: r.name || ROLE_LABELS[r.key] || r.key }))
    }
    return ROLE_OPTIONS
  }, [roles])

  const editableRoleOptions = useMemo(
    () => roleOptions.filter(o => o.value !== 'admin'),
    [roleOptions],
  )

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
      form.setFieldsValue({ role: roleOptions.find(o => o.value === 'user') ? 'user' : roleOptions[0]?.value })
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

  const handleUpdateRole = async (record, role) => {
    if (!role || role === record.role) return
    setSavingRoleId(record.id)
    try {
      await authApi.updateUserRole(record.id, role)
      message.success('角色更新成功')
      loadUsers()
    } catch (e) {
      message.error(e.response?.data?.detail || '更新角色失败')
    } finally {
      setSavingRoleId(null)
    }
  }

  const handleResetPassword = async () => {
    if (!resetPwdUser) return
    try {
      const values = await resetPwdForm.validateFields()
      setResetPwdLoading(true)
      await authApi.resetPassword(resetPwdUser.id, values.newPassword)
      message.success(`已重置 ${resetPwdUser.username} 的密码`)
      setResetPwdUser(null)
      resetPwdForm.resetFields()
    } catch (e) {
      if (e?.errorFields) return
      message.error(e.response?.data?.detail || '重置密码失败')
    } finally {
      setResetPwdLoading(false)
    }
  }

  const loadRolePorts = useCallback(async () => {
    if (!rolePortRole || !rolePortVersionId) return
    setLoadingRolePorts(true)
    try {
      const res = await roleConfigApi.getRolePorts(rolePortRole, rolePortVersionId)
      setAllPorts(res.data?.all_ports || [])
      setSelectedPorts(res.data?.ports || [])
    } catch (e) {
      setAllPorts([])
      setSelectedPorts([])
      message.error(e.response?.data?.detail || '加载角色端口权限失败')
    } finally {
      setLoadingRolePorts(false)
    }
  }, [rolePortRole, rolePortVersionId])

  useEffect(() => {
    loadRolePorts()
  }, [loadRolePorts])

  const handleSaveRolePorts = async () => {
    if (!rolePortRole || !rolePortVersionId) return
    setSavingRolePorts(true)
    try {
      await roleConfigApi.setRolePorts(rolePortRole, rolePortVersionId, selectedPorts)
      message.success('角色端口权限已保存')
    } catch (e) {
      message.error(e.response?.data?.detail || '保存角色端口权限失败')
    } finally {
      setSavingRolePorts(false)
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '用户名', dataIndex: 'username', width: 180 },
    {
      title: '角色',
      dataIndex: 'role',
      width: 240,
      render: (v, record) => {
        if (record.id === currentUser?.id) {
          return <Tag color="gold">{ROLE_LABELS[v] || v}</Tag>
        }
        return (
          <Select
            size="small"
            style={{ width: 220 }}
            value={v}
            options={roleOptions}
            loading={savingRoleId === record.id}
            onChange={(newRole) => handleUpdateRole(record, newRole)}
          />
        )
      },
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
      width: 180,
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
          <div style={{ display: 'flex', gap: 8 }}>
            <Button
              type="link"
              size="small"
              icon={<KeyOutlined />}
              onClick={() => setResetPwdUser(record)}
            >
              重置密码
            </Button>
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
          </div>
        )
      },
    },
  ]

  return (
    <div className="app-page-shell fade-in">
      <div className="app-page-shell-inner">
        <AppPageHeader
          icon={<TeamOutlined />}
          eyebrow="平台运维"
          title="用户与权限"
          subtitle="管理平台账号、分配精细化角色、配置角色可见端口。不能删除当前登录用户及最后一个管理员。"
          tags={[{ text: '仅管理员' }]}
        />
        <div className="app-page-body">
      <Card>
        <Tabs
          defaultActiveKey="users"
          items={[
            {
              key: 'users',
              label: '用户管理',
              children: (
                <>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                    <div style={{ color: '#a1a1aa' }}>
                      仅管理员可创建/删除用户、重置密码、调整角色。不能删除当前登录用户及最后一个管理员。
                    </div>
                    <Button icon={<ReloadOutlined />} onClick={loadUsers} loading={loading}>
                      刷新用户
                    </Button>
                  </div>
                  {legacyUsers.length > 0 && (
                    <div style={{ marginBottom: 12, color: '#faad14' }}>
                      当前仍有 {legacyUsers.length} 个历史 `user` 角色账号，建议逐个分配到精细化角色。
                    </div>
                  )}

                  <Form
                    form={form}
                    layout="inline"
                    initialValues={{ role: roleOptions.find(o => o.value === 'user') ? 'user' : roleOptions[0]?.value }}
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
                      <Select style={{ width: 260 }} options={roleOptions} />
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
                    scroll={{ x: 980 }}
                  />
                </>
              ),
            },
            {
              key: 'role-ports',
              label: '角色端口权限',
              children: (
                <div>
                  <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
                    <Select
                      style={{ width: 320 }}
                      value={rolePortRole}
                      options={editableRoleOptions}
                      onChange={setRolePortRole}
                      placeholder="选择角色"
                    />
                    <Select
                      style={{ width: 260 }}
                      value={rolePortVersionId}
                      options={versions.map(v => ({
                        value: v.id,
                        label: `${v.protocol_name || 'TSN ICD'} / ${v.version || ''}`,
                      }))}
                      onChange={setRolePortVersionId}
                      placeholder="选择协议版本"
                    />
                    <Button icon={<ReloadOutlined />} onClick={loadRolePorts} loading={loadingRolePorts}>
                      刷新
                    </Button>
                    <Button type="primary" onClick={handleSaveRolePorts} loading={savingRolePorts}>
                      保存端口权限
                    </Button>
                  </div>
                  <div style={{ color: '#a1a1aa', marginBottom: 10 }}>
                    说明：管理员角色默认可见全部端口；其他角色按此配置限制可见端口。
                  </div>
                  <Select
                    mode="multiple"
                    style={{ width: '100%' }}
                    placeholder="请选择该角色可见端口"
                    value={selectedPorts}
                    options={allPorts.map(p => ({ value: p, label: `端口 ${p}` }))}
                    onChange={setSelectedPorts}
                    loading={loadingRolePorts}
                    optionFilterProp="label"
                  />
                </div>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={resetPwdUser ? `重置密码：${resetPwdUser.username}` : '重置密码'}
        open={!!resetPwdUser}
        onCancel={() => {
          setResetPwdUser(null)
          resetPwdForm.resetFields()
        }}
        onOk={handleResetPassword}
        confirmLoading={resetPwdLoading}
        okText="确认重置"
        cancelText="取消"
      >
        <Form form={resetPwdForm} layout="vertical">
          <Form.Item
            name="newPassword"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, max: 128, message: '密码长度需在 6-128 之间' },
            ]}
          >
            <Input.Password maxLength={128} />
          </Form.Item>
          <Form.Item
            name="confirmPassword"
            label="确认新密码"
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('newPassword') === value) {
                    return Promise.resolve()
                  }
                  return Promise.reject(new Error('两次输入的新密码不一致'))
                },
              }),
            ]}
          >
            <Input.Password maxLength={128} />
          </Form.Item>
        </Form>
      </Modal>
        </div>
      </div>
    </div>
  )
}

export default AdminUserPage
