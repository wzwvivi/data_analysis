import React, { useMemo, useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Typography, Dropdown, Button } from 'antd'
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
  const { user, logout, isAdmin } = useAuth()
  const [collapsed, setCollapsed] = useState(true)

  const menuItems = useMemo(() => {
    const items = [
      {
        type: 'group',
        label: '网络数据分析',
        children: [
          { key: '/upload', icon: <CloudUploadOutlined />, label: '上传解析' },
          { key: '/tasks', icon: <UnorderedListOutlined />, label: '任务列表' },
        ],
      },
      {
        type: 'group',
        label: '飞机行为事件分析',
        children: [
          { key: '/event-analysis', icon: <FileSearchOutlined />, label: '飞管事件分析' },
          { key: '/fcc-event-analysis', icon: <FileSearchOutlined />, label: '飞控事件分析' },
          { key: '/auto-flight-analysis', icon: <FileSearchOutlined />, label: '自动飞行性能分析' },
        ],
      },
      {
        type: 'group',
        label: 'TSN数据异常检查',
        children: [
          { key: '/compare', icon: <SwapOutlined />, label: '异常检查' },
        ],
      },
    ]
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
  }, [isAdmin])

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
              items: [{ key: 'logout', label: '退出登录', icon: <LogoutOutlined /> }],
              onClick: ({ key }) => {
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
    </Layout>
  )
}

export default MainLayout
