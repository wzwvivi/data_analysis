import React, { useMemo, useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Typography, Dropdown, Button, Modal, Form, Input, message } from 'antd'
import {
  CloudUploadOutlined,
  UnorderedListOutlined,
  DatabaseOutlined,
  SwapOutlined,
  FileSearchOutlined,
  TeamOutlined,
  UserOutlined,
  LogoutOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import { useAuth } from '../context/AuthContext'

const { Header, Sider, Content } = Layout
const { Title } = Typography

function MainLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout, isAdmin, hasPageAccess } = useAuth()
  const [collapsed, setCollapsed] = useState(true)
  const [pwdVisible, setPwdVisible] = useState(false)
  const [pwdLoading, setPwdLoading] = useState(false)
  const [pwdForm] = Form.useForm()

  const menuItems = useMemo(() => {
    const items = []
    const networkChildren = []
    if (hasPageAccess('upload')) networkChildren.push({ key: '/upload', icon: <CloudUploadOutlined />, label: '上传解析' })
    if (hasPageAccess('tasks')) networkChildren.push({ key: '/tasks', icon: <UnorderedListOutlined />, label: '任务列表' })
    if (networkChildren.length > 0) {
      items.push({ type: 'group', label: '网络数据分析', children: networkChildren })
    }

    const analysisChildren = []
    if (hasPageAccess('event-analysis')) analysisChildren.push({ key: '/event-analysis', icon: <FileSearchOutlined />, label: '飞管事件分析' })
    if (hasPageAccess('fcc-event-analysis')) analysisChildren.push({ key: '/fcc-event-analysis', icon: <FileSearchOutlined />, label: '飞控事件分析' })
    if (hasPageAccess('auto-flight-analysis')) analysisChildren.push({ key: '/auto-flight-analysis', icon: <FileSearchOutlined />, label: '自动飞行性能分析' })
    if (analysisChildren.length > 0) {
      items.push({ type: 'group', label: '飞机行为事件分析', children: analysisChildren })
    }

    const compareChildren = []
    if (hasPageAccess('compare')) compareChildren.push({ key: '/compare', icon: <SwapOutlined />, label: '异常检查' })
    if (compareChildren.length > 0) {
      items.push({ type: 'group', label: 'TSN数据异常检查', children: compareChildren })
    }

    if (isAdmin) {
      items.push({ type: 'divider' })
      items.push({
        type: 'group',
        label: '系统配置',
        children: [
          { key: '/admin/protocol-manager', icon: <FileTextOutlined />, label: '协议管理' },
          { key: '/admin/platform-data', icon: <CloudUploadOutlined />, label: '平台共享数据' },
          { key: '/admin/users', icon: <TeamOutlined />, label: '用户管理' },
        ],
      })
    }
    return items
  }, [isAdmin, hasPageAccess])

  const handleMenuClick = ({ key }) => {
    navigate(key)
  }

  const getSelectedKey = () => {
    const path = location.pathname
    if (path.startsWith('/tasks/')) return '/tasks'
    if (path.startsWith('/compare')) return '/compare'
    if (path.startsWith('/auto-flight-analysis')) return '/auto-flight-analysis'
    if (path.startsWith('/fcc-event-analysis')) return '/fcc-event-analysis'
    if (path.startsWith('/event-analysis')) return '/event-analysis'
    if (path.startsWith('/admin/protocol-manager')) return '/admin/protocol-manager'
    if (path.startsWith('/admin/platform-data')) return '/admin/platform-data'
    if (path.startsWith('/admin/users')) return '/admin/users'
    return path
  }

  const onLogout = () => {
    logout()
    navigate('/login')
  }

  const handleChangePassword = async () => {
    try {
      const values = await pwdForm.validateFields()
      if (values.newPassword !== values.confirmPassword) {
        message.error('两次输入的新密码不一致')
        return
      }
      setPwdLoading(true)
      const { authApi } = await import('../services/api')
      await authApi.changePassword(values.oldPassword, values.newPassword)
      message.success('密码修改成功，请妥善保管')
      setPwdVisible(false)
      pwdForm.resetFields()
    } catch (e) {
      if (e?.errorFields) return
      message.error(e?.response?.data?.detail || '修改密码失败')
    } finally {
      setPwdLoading(false)
    }
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        trigger={null}
        width={240}
        collapsedWidth={64}
        onMouseEnter={() => setCollapsed(false)}
        onMouseLeave={() => setCollapsed(true)}
        style={{
          background: 'rgba(18, 18, 23, 0.94)',
          backdropFilter: 'blur(12px)',
          borderRight: '1px solid rgba(70, 70, 82, 0.36)',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        {/* Sidebar bottom ambient glow */}
        <div style={{
          position: 'absolute',
          bottom: 0,
          left: '50%',
          transform: 'translateX(-50%)',
          width: '160px',
          height: '120px',
          background: 'radial-gradient(circle, rgba(139, 92, 246, 0.06) 0%, transparent 70%)',
          filter: 'blur(36px)',
          pointerEvents: 'none',
        }} />

        <div style={{
          padding: collapsed ? '20px 12px' : '20px 20px',
          borderBottom: '1px solid rgba(63, 63, 70, 0.4)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: collapsed ? 'center' : 'flex-start',
          transition: 'all 0.2s ease',
        }}>
          <div style={{
            width: collapsed ? 36 : 32,
            height: collapsed ? 36 : 32,
            borderRadius: 10,
            background: 'linear-gradient(135deg, #5b21b6 0%, #6d28d9 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            boxShadow: '0 0 10px rgba(109, 40, 217, 0.22)',
            transition: 'all 0.2s ease',
          }}>
            <DatabaseOutlined style={{ 
              fontSize: collapsed ? 18 : 16,
              color: '#e4e4e7',
              transition: 'all 0.2s ease',
            }} />
          </div>
          {!collapsed && (
            <Title level={4} style={{
              color: '#e4e4e7',
              margin: 0,
              marginLeft: 12,
              fontSize: '16px',
              fontWeight: 600,
              letterSpacing: '-0.02em',
              whiteSpace: 'nowrap',
            }}>
              网络数据处理
            </Title>
          )}
        </div>
        <Menu
          mode="inline"
          selectedKeys={[getSelectedKey()]}
          items={menuItems}
          onClick={handleMenuClick}
          inlineCollapsed={collapsed}
          style={{
            background: 'transparent',
            border: 'none',
            marginTop: '8px',
          }}
        />
      </Sider>
      <Layout>
        <Header style={{
          background: 'rgba(18, 18, 23, 0.82)',
          backdropFilter: 'blur(12px)',
          WebkitBackdropFilter: 'blur(12px)',
          padding: '0 32px',
          borderBottom: '1px solid rgba(70, 70, 82, 0.36)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <div style={{ 
            color: '#71717a', 
            fontSize: '12px',
            fontWeight: 500,
            letterSpacing: '0.005em',
          }}>
              {location.pathname === '/upload' && '网络数据分析 / 上传TSN数据包进行解析'}
              {location.pathname === '/tasks' && '网络数据分析 / 查看所有解析任务'}
              {location.pathname.startsWith('/compare') && 'TSN数据异常检查'}
              {location.pathname.includes('/fcc-event-analysis') && '飞机行为事件分析 / 飞控事件分析'}
              {location.pathname.includes('/auto-flight-analysis') && '飞机行为事件分析 / 自动飞行性能分析'}
              {location.pathname.includes('/event-analysis') && !location.pathname.includes('/fcc-event-analysis') && !location.pathname.includes('/auto-flight-analysis') && '飞机行为事件分析 / 飞管事件分析'}
              {location.pathname.includes('/analysis') && !location.pathname.includes('/event-analysis') && '网络数据分析 / 时序数据分析与可视化'}
              {location.pathname.startsWith('/tasks/') && !location.pathname.includes('/analysis') && '网络数据分析 / 解析结果查看'}
              {location.pathname.startsWith('/admin/protocol-manager') && '系统配置 / 协议管理'}
              {location.pathname.startsWith('/admin/platform-data') && '系统配置 / 平台共享数据'}
              {location.pathname.startsWith('/admin/users') && '系统配置 / 用户管理'}
          </div>
          <Dropdown
            menu={{
              items: [
                { key: 'change-password', label: '修改密码', icon: <UserOutlined /> },
                { type: 'divider' },
                { key: 'logout', label: '退出登录', icon: <LogoutOutlined /> },
              ],
              onClick: ({ key }) => {
                if (key === 'change-password') {
                  setPwdVisible(true)
                }
                if (key === 'logout') onLogout()
              },
            }}
            placement="bottomRight"
          >
            <Button type="text" style={{ 
              color: '#d4d4d8',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              height: 38,
              borderRadius: 10,
              padding: '0 14px',
            }}>
              <div style={{
                width: 26,
                height: 26,
                borderRadius: 8,
                background: 'linear-gradient(135deg, #5b21b6 0%, #6d28d9 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 12,
                fontWeight: 700,
                color: '#e4e4e7',
              }}>
                {(user?.username || 'U').charAt(0).toUpperCase()}
              </div>
              <span style={{ fontWeight: 500 }}>{user?.username || '—'}</span>
              <span className="pill-badge" style={{ fontSize: 8, padding: '2px 8px', marginLeft: 2, opacity: 0.85 }}>
                {user?.role === 'admin' ? 'Admin' : 'User'}
              </span>
            </Button>
          </Dropdown>
        </Header>
        <Content style={{
          margin: '24px',
          minHeight: 'calc(100vh - 112px)',
        }}>
          <Outlet />
        </Content>
      </Layout>
      <Modal
        title="修改密码"
        open={pwdVisible}
        onCancel={() => {
          setPwdVisible(false)
          pwdForm.resetFields()
        }}
        onOk={handleChangePassword}
        confirmLoading={pwdLoading}
        okText="确认修改"
        cancelText="取消"
      >
        <Form form={pwdForm} layout="vertical">
          <Form.Item
            name="oldPassword"
            label="当前密码"
            rules={[{ required: true, message: '请输入当前密码' }]}
          >
            <Input.Password maxLength={128} />
          </Form.Item>
          <Form.Item
            name="newPassword"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, max: 128, message: '新密码长度需在 6-128 之间' },
            ]}
          >
            <Input.Password maxLength={128} />
          </Form.Item>
          <Form.Item
            name="confirmPassword"
            label="确认新密码"
            rules={[{ required: true, message: '请再次输入新密码' }]}
          >
            <Input.Password maxLength={128} />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  )
}

export default MainLayout
