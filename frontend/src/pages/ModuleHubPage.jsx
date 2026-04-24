import React, { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, Col, Empty, Row, Space, Tag, Typography } from 'antd'
import {
  AimOutlined,
  ApartmentOutlined,
  AppstoreOutlined,
  CloudUploadOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  LineChartOutlined,
  LogoutOutlined,
  SettingOutlined,
  SwapOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { useAuth } from '../context/AuthContext'
import { getVisibleModuleSections } from '../config/moduleRegistry'
import '../styles/help.css'

const { Title, Paragraph, Text } = Typography

const ICON_MAP = {
  appstore: <AppstoreOutlined />,
  dashboard: <DashboardOutlined />,
  upload: <CloudUploadOutlined />,
  tasks: <DatabaseOutlined />,
  workbench: <AimOutlined />,
  search: <FileSearchOutlined />,
  linechart: <LineChartOutlined />,
  swap: <SwapOutlined />,
  assistant: <FileSearchOutlined />,
  network: <DatabaseOutlined />,
  protocol: <ApartmentOutlined />,
  database: <DatabaseOutlined />,
  setting: <SettingOutlined />,
  team: <TeamOutlined />,
}

function ModuleHubPage() {
  const navigate = useNavigate()
  const { user, logout, isAdmin, hasPageAccess, publicConfig } = useAuth()

  const onLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  const sections = useMemo(() => getVisibleModuleSections({
    isAdmin,
    hasPageAccess,
    publicConfig,
  }), [isAdmin, hasPageAccess, publicConfig])

  const totalModules = useMemo(
    () => sections.reduce((count, section) => count + section.modules.length, 0),
    [sections],
  )

  const handleOpenModule = (module) => {
    if (module.externalUrl) {
      window.open(module.externalUrl, '_blank', 'noopener,noreferrer')
      return
    }
    if (module.path) navigate(module.path)
  }

  return (
    <div className="module-hub-layout">
      <header className="module-hub-topbar">
        <div className="module-hub-topbar-inner">
          <div className="module-hub-brand">
            <div className="module-hub-brand-logo"><DatabaseOutlined /></div>
            <div>
              <div className="module-hub-brand-name">网络数据分析平台</div>
              <div className="module-hub-brand-sub">选择要使用的工具</div>
            </div>
          </div>
          <Space size={12}>
            <Button type="text" onClick={() => navigate('/')}>
              返回官网首页
            </Button>
            <Button type="default" icon={<LogoutOutlined />} onClick={onLogout}>
              退出登录
            </Button>
          </Space>
        </div>
      </header>

      <div className="module-hub-page animate-fade-in">
      <Card className="module-hub-header glass-card shadow-premium">
        <Tag className="border-purple-500/30 bg-purple-500/10 text-purple-400" style={{ marginBottom: 10 }}>开始使用</Tag>
        <Title level={3} style={{ marginBottom: 6, color: '#f8fafc' }}>
          工具集
        </Title>
        <Paragraph style={{ marginBottom: 0, color: '#94a3b8' }}>
          {user ? `欢迎，${user.username}。` : '欢迎使用平台。'}
          {' '}当前账号可访问 {totalModules} 个工具，点击即可进入对应功能页面。
        </Paragraph>
      </Card>

      {sections.length === 0 ? (
        <Card>
          <Empty description="当前账号暂无可访问模块，请联系管理员配置权限。" />
        </Card>
      ) : (
        <div className="module-hub-sections">
          {sections.map((section, idx) => (
            <Card 
              key={section.key} 
              className="module-hub-section-card animate-slide-up"
              style={{ animationDelay: `${(idx + 1) * 100}ms` }}
            >
              <div className="module-hub-section-head">
                <Title level={4} className="module-hub-section-title">{section.title}</Title>
                <Paragraph type="secondary" className="module-hub-section-desc">{section.desc}</Paragraph>
              </div>
              <Row gutter={[16, 16]}>
                {section.modules.map((module) => (
                  <Col xs={24} md={12} xl={8} key={module.key}>
                    <Card
                      hoverable
                      className="module-hub-module-card"
                      bordered={false}
                      onClick={() => handleOpenModule(module)}
                    >
                      <Space align="start" size={14}>
                        <div className="module-hub-icon">
                          {ICON_MAP[module.icon] || <AppstoreOutlined />}
                        </div>
                        <div>
                          <Space size={8} wrap>
                            <Text strong className="module-hub-module-title">{module.title}</Text>
                            {module.adminOnly ? <Tag color="default">Admin</Tag> : null}
                            {module.externalUrl ? <Tag color="processing">外部服务</Tag> : null}
                          </Space>
                          <Paragraph type="secondary" className="module-hub-module-desc">
                            {module.summary}
                          </Paragraph>
                          <Button type="link" className="module-hub-module-action">
                            进入工具
                          </Button>
                        </div>
                      </Space>
                    </Card>
                  </Col>
                ))}
              </Row>
            </Card>
          ))}
        </div>
      )}
      </div>
    </div>
  )
}

export default ModuleHubPage
