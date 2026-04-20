import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Typography, Dropdown, Button, Modal, Form, Input, message, Breadcrumb, Badge, List, Empty, Tag, Spin, Tooltip } from 'antd'
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
  SafetyCertificateOutlined,
  BellOutlined,
  CheckOutlined,
  ApartmentOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { useAuth } from '../context/AuthContext'
import { notificationApi } from '../services/api'

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

  const [notifOpen, setNotifOpen] = useState(false)
  const [notifLoading, setNotifLoading] = useState(false)
  const [notifItems, setNotifItems] = useState([])
  const [unreadCount, setUnreadCount] = useState(0)
  const notifTimerRef = useRef(null)

  const loadNotifications = useCallback(async (silent = false) => {
    try {
      if (!silent) setNotifLoading(true)
      const res = await notificationApi.list({ limit: 20 })
      setNotifItems(res.data?.items || [])
      setUnreadCount(res.data?.unread_count || 0)
    } catch {
      // ignore
    } finally {
      if (!silent) setNotifLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!user) return
    loadNotifications(true)
    notifTimerRef.current = setInterval(() => loadNotifications(true), 60_000)
    return () => {
      if (notifTimerRef.current) clearInterval(notifTimerRef.current)
    }
  }, [user, loadNotifications])

  const handleNotifClick = async (n) => {
    try {
      if (!n.read_at) {
        await notificationApi.markRead(n.id)
      }
    } catch {
      // ignore
    }
    setNotifOpen(false)
    loadNotifications(true)
    if (n.link) {
      const to = n.link.startsWith('/') ? n.link : `/${n.link}`
      navigate(to)
    }
  }

  const handleMarkAllRead = async () => {
    try {
      await notificationApi.markAllRead()
      loadNotifications(true)
    } catch (e) {
      message.error(e?.response?.data?.detail || '标记失败')
    }
  }

  const menuItems = useMemo(() => {
    const items = []
    const networkChildren = []
    if (hasPageAccess('upload')) networkChildren.push({ key: '/upload', icon: <CloudUploadOutlined />, label: '上传解析' })
    if (hasPageAccess('tasks')) networkChildren.push({ key: '/tasks', icon: <UnorderedListOutlined />, label: '任务列表' })
    if (hasPageAccess('network-config')) networkChildren.push({ key: '/network-config', icon: <SafetyCertificateOutlined />, label: 'TSN 网络配置' })
    if (hasPageAccess('device-protocol')) networkChildren.push({ key: '/device-protocol', icon: <ApartmentOutlined />, label: '设备协议管理' })
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
    if (path.startsWith('/network-config')) return '/network-config'
    if (path.startsWith('/device-protocol')) return '/device-protocol'
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

  const breadcrumbItems = useMemo(() => {
    const path = location.pathname
    const items = [{ title: '首页', href: '/upload' }]
    const push = (title, href) => items.push({ title, href })

    if (path === '/upload') {
      push('网络数据分析', null); push('上传解析', null)
    } else if (path === '/tasks') {
      push('网络数据分析', null); push('任务中心', null)
    } else if (/^\/tasks\/[^/]+\/analysis$/.test(path)) {
      push('网络数据分析', null); push('任务中心', '/tasks'); push('结果分析', null)
    } else if (/^\/tasks\/[^/]+\/event-analysis$/.test(path)) {
      push('网络数据分析', null); push('任务中心', '/tasks'); push('事件分析', null)
    } else if (/^\/tasks\/[^/]+$/.test(path)) {
      push('网络数据分析', null); push('任务中心', '/tasks'); push('解析结果', null)
    } else if (path.startsWith('/network-config/drafts')) {
      push('网络数据分析', null); push('TSN 网络配置', '/network-config'); push('草稿编辑', null)
    } else if (path.startsWith('/network-config/change-requests')) {
      push('网络数据分析', null); push('TSN 网络配置', '/network-config'); push('变更请求', null)
    } else if (path.startsWith('/network-config')) {
      push('网络数据分析', null); push('TSN 网络配置', null)
    } else if (path.startsWith('/device-protocol/drafts')) {
      push('网络数据分析', null); push('设备协议管理', '/device-protocol'); push('草稿编辑', null)
    } else if (path.startsWith('/device-protocol/change-requests')) {
      push('网络数据分析', null); push('设备协议管理', '/device-protocol'); push('审批流', null)
    } else if (path.startsWith('/device-protocol/versions')) {
      push('网络数据分析', null); push('设备协议管理', '/device-protocol'); push('版本详情', null)
    } else if (path.startsWith('/device-protocol')) {
      push('网络数据分析', null); push('设备协议管理', null)
    } else if (path.startsWith('/compare')) {
      push('TSN数据异常检查', null)
    } else if (path.startsWith('/fcc-event-analysis/task/')) {
      push('飞机行为事件分析', null); push('飞控事件分析', '/fcc-event-analysis'); push('任务详情', null)
    } else if (path.startsWith('/fcc-event-analysis')) {
      push('飞机行为事件分析', null); push('飞控事件分析', null)
    } else if (path.startsWith('/auto-flight-analysis/task/')) {
      push('飞机行为事件分析', null); push('自动飞行性能分析', '/auto-flight-analysis'); push('任务详情', null)
    } else if (path.startsWith('/auto-flight-analysis')) {
      push('飞机行为事件分析', null); push('自动飞行性能分析', null)
    } else if (path.startsWith('/event-analysis/task/')) {
      push('飞机行为事件分析', null); push('飞管事件分析', '/event-analysis'); push('任务详情', null)
    } else if (path.startsWith('/event-analysis')) {
      push('飞机行为事件分析', null); push('飞管事件分析', null)
    } else if (path.startsWith('/admin/protocol-manager')) {
      push('系统配置', null); push('协议管理', null)
    } else if (path.startsWith('/admin/platform-data')) {
      push('系统配置', null); push('平台共享数据', null)
    } else if (path.startsWith('/admin/users')) {
      push('系统配置', null); push('用户管理', null)
    }

    return items.map((it, idx) => ({
      key: `${idx}-${it.title}`,
      title: it.href ? (
        <a
          onClick={(e) => { e.preventDefault(); navigate(it.href) }}
          style={{ color: '#a1a1aa', cursor: 'pointer' }}
        >
          {it.title}
        </a>
      ) : (
        <span style={{ color: idx === items.length - 1 ? '#d4d4d8' : '#71717a' }}>{it.title}</span>
      ),
    }))
  }, [location.pathname, navigate])

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
          <Breadcrumb
            items={breadcrumbItems}
            separator="/"
            style={{
              fontSize: 12,
              fontWeight: 500,
              letterSpacing: '0.005em',
              color: '#71717a',
            }}
          />
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Dropdown
            open={notifOpen}
            onOpenChange={(open) => {
              setNotifOpen(open)
              if (open) loadNotifications()
            }}
            placement="bottomRight"
            trigger={['click']}
            dropdownRender={() => (
              <div style={{
                width: 380,
                background: 'rgba(24, 24, 27, 0.96)',
                border: '1px solid rgba(70, 70, 82, 0.4)',
                borderRadius: 10,
                boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
                backdropFilter: 'blur(12px)',
                overflow: 'hidden',
              }}>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '10px 14px',
                  borderBottom: '1px solid rgba(63,63,70,0.4)',
                }}>
                  <span style={{ color: '#e4e4e7', fontWeight: 600, fontSize: 13 }}>
                    站内通知
                    {unreadCount > 0 ? (
                      <Tag color="processing" style={{ marginLeft: 8 }}>{unreadCount} 未读</Tag>
                    ) : null}
                  </span>
                  <Button
                    type="link"
                    size="small"
                    icon={<CheckOutlined />}
                    onClick={handleMarkAllRead}
                    disabled={unreadCount === 0}
                  >
                    全部标为已读
                  </Button>
                </div>
                <div style={{ maxHeight: 420, overflowY: 'auto' }}>
                  {notifLoading ? (
                    <div style={{ padding: 24, textAlign: 'center' }}><Spin /></div>
                  ) : notifItems.length === 0 ? (
                    <div style={{ padding: 24 }}>
                      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通知" />
                    </div>
                  ) : (
                    <List
                      dataSource={notifItems}
                      renderItem={(n) => (
                        <List.Item
                          style={{
                            padding: '10px 14px',
                            cursor: 'pointer',
                            background: n.read_at ? 'transparent' : 'rgba(91, 33, 182, 0.08)',
                            borderBottom: '1px solid rgba(63,63,70,0.25)',
                          }}
                          onClick={() => handleNotifClick(n)}
                        >
                          <div style={{ width: '100%' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                              <span style={{ color: '#e4e4e7', fontSize: 13, fontWeight: 600 }}>
                                {n.title}
                              </span>
                              {!n.read_at ? (
                                <span style={{
                                  width: 8, height: 8, borderRadius: '50%',
                                  background: '#a855f7', flexShrink: 0,
                                }} />
                              ) : null}
                            </div>
                            {n.body ? (
                              <div style={{ color: '#a1a1aa', fontSize: 12, marginBottom: 4, lineHeight: 1.5 }}>
                                {n.body}
                              </div>
                            ) : null}
                            <div style={{ color: '#71717a', fontSize: 11 }}>
                              {n.created_at ? dayjs(n.created_at).format('YYYY-MM-DD HH:mm') : ''}
                            </div>
                          </div>
                        </List.Item>
                      )}
                    />
                  )}
                </div>
              </div>
            )}
          >
            <Tooltip title="站内通知" placement="bottom">
              <Button
                type="text"
                style={{
                  color: '#d4d4d8',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  height: 38,
                  width: 38,
                  borderRadius: 10,
                  padding: 0,
                }}
              >
                <Badge count={unreadCount} overflowCount={99} size="small" offset={[-2, 2]}>
                  <BellOutlined style={{ fontSize: 16, color: '#d4d4d8' }} />
                </Badge>
              </Button>
            </Tooltip>
          </Dropdown>

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
          </div>
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
