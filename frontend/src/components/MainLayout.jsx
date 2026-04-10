import React, { useMemo } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Typography, Dropdown, Button } from 'antd'
import {
  CloudUploadOutlined,
  UnorderedListOutlined,
  DatabaseOutlined,
  ApiOutlined,
  SwapOutlined,
  FileSearchOutlined,
  TeamOutlined,
  UserOutlined,
  LogoutOutlined,
} from '@ant-design/icons'
import { useAuth } from '../context/AuthContext'

const { Header, Sider, Content } = Layout
const { Title } = Typography

function MainLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout, isAdmin } = useAuth()

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
          { key: '/event-analysis', icon: <FileSearchOutlined />, label: '事件分析' },
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
          { key: '/network-config', icon: <ApiOutlined />, label: '网络配置' },
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

  // 获取当前选中的菜单项
  const getSelectedKey = () => {
    const path = location.pathname
    if (path.startsWith('/tasks/')) return '/tasks'
    if (path.startsWith('/compare')) return '/compare'
    if (path.startsWith('/event-analysis')) return '/event-analysis'
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
        width={240}
        style={{
          background: '#161b22',
          borderRight: '1px solid #30363d',
        }}
      >
        <div style={{
          padding: '24px 20px',
          borderBottom: '1px solid #30363d',
        }}>
          <Title level={4} style={{
            color: '#c9d1d9',
            margin: 0,
            fontSize: '18px',
            fontWeight: 600,
            letterSpacing: '-0.5px',
          }}>
            <DatabaseOutlined style={{ marginRight: 10, color: '#58a6ff' }} />
            TSN日志数据分析平台
          </Title>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[getSelectedKey()]}
          items={menuItems}
          onClick={handleMenuClick}
          style={{
            background: 'transparent',
            border: 'none',
            marginTop: '12px',
          }}
        />
      </Sider>
      <Layout>
        <Header style={{
          background: 'linear-gradient(135deg, #161b22 0%, #21262d 100%)',
          padding: '0 24px',
          borderBottom: '1px solid #30363d',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <div style={{ color: '#8b949e', fontSize: '14px' }}>
            {location.pathname === '/upload' && '网络数据分析 / 上传TSN数据包进行解析'}
            {location.pathname === '/tasks' && '网络数据分析 / 查看所有解析任务'}
            {location.pathname.startsWith('/compare') && 'TSN数据异常检查'}
            {location.pathname.includes('/event-analysis') && '飞机行为事件分析'}
            {location.pathname.includes('/analysis') && !location.pathname.includes('/event-analysis') && '网络数据分析 / 时序数据分析与可视化'}
            {location.pathname.startsWith('/tasks/') && !location.pathname.includes('/analysis') && '网络数据分析 / 解析结果查看'}
            {location.pathname === '/network-config' && '系统配置 / 网络配置'}
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
            <Button type="text" style={{ color: '#c9d1d9' }}>
              <UserOutlined /> {user?.username || '—'}
              <span style={{ marginLeft: 8, color: '#8b949e', fontSize: 12 }}>
                {user?.role === 'admin' ? '管理员' : '用户'}
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
