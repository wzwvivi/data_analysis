import React, { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AimOutlined,
  ApartmentOutlined,
  AppstoreOutlined,
  ArrowRightOutlined,
  CloseOutlined,
  CloudUploadOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  LineChartOutlined,
  LogoutOutlined,
  SearchOutlined,
  SettingOutlined,
  SwapOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { useAuth } from '../context/AuthContext'
import { MODULE_GROUPS, getVisibleModuleSections } from '../config/moduleRegistry'
import '../styles/help.css'

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

const ALL_GROUPS = 'ALL'

function ModuleHubPage() {
  const navigate = useNavigate()
  const { user, logout, isAdmin, hasPageAccess, publicConfig } = useAuth()
  const [selectedGroup, setSelectedGroup] = useState(ALL_GROUPS)
  const [searchText, setSearchText] = useState('')

  const onLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  const sections = useMemo(() => getVisibleModuleSections({
    isAdmin,
    hasPageAccess,
    publicConfig,
  }), [isAdmin, hasPageAccess, publicConfig])

  const allModules = useMemo(
    () => sections.flatMap((s) => s.modules.map((m) => ({ ...m, groupTitle: s.title }))),
    [sections],
  )

  const filteredModules = useMemo(() => {
    let list = allModules
    if (selectedGroup !== ALL_GROUPS) {
      list = list.filter((m) => m.group === selectedGroup)
    }
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase()
      list = list.filter((m) =>
        m.title.toLowerCase().includes(q) ||
        (m.summary || '').toLowerCase().includes(q),
      )
    }
    return list
  }, [allModules, selectedGroup, searchText])

  const visibleGroups = useMemo(
    () => MODULE_GROUPS.filter((g) => sections.some((s) => s.key === g.key)),
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
    <div className="tools-hub-wrapper">
      <header className="tools-hub-topbar">
        <div className="tools-hub-topbar-inner">
          <div className="tools-hub-brand">
            <div className="tools-hub-brand-logo"><DatabaseOutlined /></div>
            <div>
              <div className="tools-hub-brand-name">网络数据分析平台</div>
              <div className="tools-hub-brand-sub">Tool Repository</div>
            </div>
          </div>
          <div className="tools-hub-topbar-actions">
            <button type="button" className="tools-hub-topbar-btn" onClick={() => navigate('/')}>
              返回官网首页
            </button>
            <button type="button" className="tools-hub-topbar-btn danger" onClick={onLogout}>
              <LogoutOutlined style={{ marginRight: 6 }} />
              退出登录
            </button>
          </div>
        </div>
      </header>

      <div className="tools-hub-bg-decor tools-hub-bg-decor-tl" />
      <div className="tools-hub-bg-decor tools-hub-bg-decor-br" />

      <div className="tools-hub-container animate-fade-in">
        {/* Header Section */}
        <div className="tools-hub-header">
          <div className="tools-hub-header-title-wrap">
            <div className="tools-hub-header-accent" />
            <h1 className="tools-hub-title">
              工具<span className="tools-hub-title-accent">集</span>
            </h1>
            <div className="tools-hub-subtitle-row">
              <p className="tools-hub-subtitle">Network Data Analysis Toolkit</p>
              <div className="tools-hub-subtitle-divider" />
              <span className="tools-hub-version-tag">v1.0</span>
            </div>
            <p className="tools-hub-welcome">
              {user ? `欢迎，${user.username}。` : '欢迎使用平台。'}
              {' '}当前账号可访问 {allModules.length} 个工具，点击卡片即可进入对应功能页面。
            </p>
          </div>

          {/* Modern Search */}
          <div className="tools-hub-search-wrap">
            <SearchOutlined className="tools-hub-search-icon" />
            <input
              type="text"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              placeholder="搜索工具名称或描述..."
              className="tools-hub-search-input"
            />
            {searchText && (
              <button
                type="button"
                onClick={() => setSearchText('')}
                className="tools-hub-search-clear"
              >
                <CloseOutlined />
              </button>
            )}
            <div className="tools-hub-search-underline" />
          </div>
        </div>

        {/* Filter Segmented Control */}
        {visibleGroups.length > 0 && (
          <div className="tools-hub-filter">
            <button
              type="button"
              onClick={() => setSelectedGroup(ALL_GROUPS)}
              className={`tools-hub-filter-btn${selectedGroup === ALL_GROUPS ? ' active' : ''}`}
            >
              <span>所有</span>
            </button>
            {visibleGroups.map((group) => (
              <button
                key={group.key}
                type="button"
                onClick={() => setSelectedGroup(group.key)}
                className={`tools-hub-filter-btn${selectedGroup === group.key ? ' active' : ''}`}
              >
                <span>{group.title}</span>
              </button>
            ))}
          </div>
        )}

        {/* Tools Grid */}
        {filteredModules.length === 0 ? (
          <div className="tools-hub-empty">
            <div className="tools-hub-empty-icon">
              <AppstoreOutlined />
            </div>
            <h3 className="tools-hub-empty-title">未能找到相关工具</h3>
            <p className="tools-hub-empty-desc">请尝试调整搜索关键词或选择不同的分组重新查询。</p>
            <button
              type="button"
              onClick={() => { setSearchText(''); setSelectedGroup(ALL_GROUPS) }}
              className="tools-hub-empty-btn"
            >
              清除所有筛选条件
            </button>
          </div>
        ) : (
          <div className="tools-hub-grid">
            {filteredModules.map((module, idx) => (
              <div
                key={module.key}
                className="tools-hub-card"
                style={{ animationDelay: `${idx * 50}ms` }}
                onClick={() => handleOpenModule(module)}
              >
                <div className="tools-hub-card-glow" />

                {/* Top: Icon & Badge */}
                <div className="tools-hub-card-top">
                  <div className="tools-hub-card-icon">
                    {ICON_MAP[module.icon] || <AppstoreOutlined />}
                    <div className="tools-hub-card-icon-overlay" />
                  </div>
                  <div className="tools-hub-card-badges">
                    {module.adminOnly ? (
                      <span className="tools-hub-card-badge admin">Admin</span>
                    ) : module.externalUrl ? (
                      <span className="tools-hub-card-badge external">External</span>
                    ) : (
                      <span className="tools-hub-card-badge active">Active</span>
                    )}
                    <span className="tools-hub-card-version">{module.groupTitle}</span>
                  </div>
                </div>

                {/* Content */}
                <div className="tools-hub-card-body">
                  <h3 className="tools-hub-card-title">{module.title}</h3>
                  <p className="tools-hub-card-desc">
                    {module.summary || '该模块由系统集成，点击即可进入对应功能。'}
                  </p>
                </div>

                {/* Bottom: CTA */}
                <div className="tools-hub-card-bottom">
                  <div className="tools-hub-card-bottom-left">
                    <div className="tools-hub-card-dot" />
                    <span className="tools-hub-card-bottom-label">Internal Hub</span>
                  </div>
                  <div className="tools-hub-card-cta">
                    <span>进入工具</span>
                    <div className="tools-hub-card-cta-arrow">
                      <ArrowRightOutlined />
                    </div>
                  </div>
                </div>

                {/* Bottom border glow */}
                <div className="tools-hub-card-border-glow" />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default ModuleHubPage
