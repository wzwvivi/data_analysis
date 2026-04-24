import React, { useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, Col, Layout, Row, Space, Tag, Typography } from 'antd'
import { useAuth } from '../context/AuthContext'
import {
  AimOutlined,
  ApartmentOutlined,
  ArrowRightOutlined,
  CloudUploadOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  LineChartOutlined,
  RocketOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  SwapOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { DOCS } from '../content/docs/manifest'
import '../styles/help.css'
import packageJson from '../../package.json'

const { Content, Footer } = Layout
const { Title, Paragraph, Text } = Typography

const MODULE_ICONS = {
  upload: <CloudUploadOutlined />,
  tasks: <DatabaseOutlined />,
  'network-config': <SafetyCertificateOutlined />,
  'device-protocol': <ApartmentOutlined />,
  'fms-event-analysis': <FileSearchOutlined />,
  'fcc-event-analysis': <FileSearchOutlined />,
  'auto-flight-analysis': <LineChartOutlined />,
  compare: <SwapOutlined />,
  workbench: <AimOutlined />,
  'workbench-compare': <SwapOutlined />,
  'flight-assistant': <FileSearchOutlined />,
  'platform-data': <DatabaseOutlined />,
  configurations: <SettingOutlined />,
  users: <TeamOutlined />,
}

const HIGHLIGHT_STATS = [
  { value: '15+', label: '业务模块', hint: '覆盖上传、解析、事件、异常、配置全链路' },
  { value: '2GB', label: '单次上传上限', hint: '典型 1GB PCAP 数秒排队进入解析' },
  { value: '长期', label: '解析结果留存', hint: '解析结果默认永久保留，共享原始数据默认 20 天后清理' },
  { value: 'RBAC', label: '页面级权限', hint: '按角色与页面双维度管控访问' },
]

const CAPABILITIES = [
  {
    icon: <CloudUploadOutlined />,
    title: 'TSN 数据一体化解析',
    desc: '从上传、协议版本绑定、端口筛选到解析任务调度，全程在平台内完成，告别脚本化操作。',
  },
  {
    icon: <FileSearchOutlined />,
    title: '多维事件与异常分析',
    desc: '飞管、飞控、自动飞行三条事件分析管线并行，配合 TSN 异常检查快速定位任务间差异。',
  },
  {
    icon: <SafetyCertificateOutlined />,
    title: '配置与协议版本治理',
    desc: '网络配置、设备协议全部版本化，支持草稿、审批、发布三态流转，解析口径永久可追溯。',
  },
  {
    icon: <AimOutlined />,
    title: '架次工作台联查',
    desc: '按架次维度聚合跨任务数据，支持下钻、横向对比与结论沉淀，缩短日常复盘路径。',
  },
]

const WORKFLOW_STEPS = [
  { icon: <CloudUploadOutlined />, title: '上传解析', desc: '选择协议版本与端口范围，提交原始数据' },
  { icon: <DatabaseOutlined />, title: '任务追踪', desc: '在任务中心实时查看状态、错误与结果入口' },
  { icon: <FileSearchOutlined />, title: '深度分析', desc: '进入事件分析或 TSN 异常检查定位问题' },
  { icon: <AimOutlined />, title: '联查复盘', desc: '工作台按架次聚合，沉淀结论与发布材料' },
]

// 常用入口：面向已经熟悉平台的老用户，提供直达任务页面的快捷方式；首次使用用户不建议从这里开始。
const QUICK_START_LINKS = [
  { key: 'upload', title: '上传解析', desc: '直接进入上传解析，绑定协议后启动任务', target: '/upload', requiresAuth: true },
  { key: 'tasks', title: '任务中心', desc: '前往任务中心筛选、复盘与下载结果', target: '/tasks', requiresAuth: true },
  { key: 'modules', title: '工具集', desc: '进入模块选择页面，按角色查看可用工具', target: '/modules', requiresAuth: true },
]

const MODULE_SECTIONS = [
  {
    key: 'common',
    title: '常用入口',
    desc: '高频使用模块，建议优先熟悉。',
    docKeys: ['upload', 'tasks', 'workbench'],
  },
  {
    key: 'analysis',
    title: '深度分析',
    desc: '事件诊断、性能评估与差异定位能力。',
    docKeys: ['fms-event-analysis', 'fcc-event-analysis', 'auto-flight-analysis', 'compare', 'workbench-compare', 'flight-assistant'],
  },
  {
    key: 'governance',
    title: '配置与管理',
    desc: '保障解析口径一致、权限可控、过程可追溯。',
    docKeys: ['network-config', 'device-protocol', 'platform-data', 'configurations', 'users'],
  },
]

const ADMIN_DOC_KEYS = new Set(['platform-data', 'configurations', 'users'])

function LandingPage() {
  const navigate = useNavigate()
  const { user } = useAuth()

  const docMap = useMemo(() => DOCS.reduce((acc, doc) => {
    acc[doc.key] = doc
    return acc
  }, {}), [])

  const moduleSections = useMemo(() => (
    MODULE_SECTIONS.map((section) => ({
      ...section,
      docs: section.docKeys.map((docKey) => docMap[docKey]).filter(Boolean),
    }))
  ), [docMap])

  // 统一的受保护跳转：未登录先去 /login 并记录目标地址，登录后自动跳回目标页；已登录直接跳转。
  const goProtected = useCallback((target) => {
    if (user) {
      navigate(target)
    } else {
      navigate('/login', { state: { from: target } })
    }
  }, [navigate, user])

  const ctaText = user ? '进入工具集' : '开始使用'
  const ctaTarget = user ? '/modules' : '/login'

  return (
    <Layout className="landing-layout">
      <header className="landing-topbar">
        <div className="landing-topbar-inner">
          <div className="landing-brand">
            <div className="landing-brand-logo"><DatabaseOutlined /></div>
            <div>
              <div className="landing-brand-name">网络数据分析平台</div>
              <div className="landing-brand-sub">Network Data Analysis Platform</div>
            </div>
          </div>
          <Space size={12}>
            <Button type="text" onClick={() => goProtected('/help/overview')}>产品介绍</Button>
            <Button type="text" onClick={() => goProtected('/help/quickstart')}>快速开始</Button>
            <Button type="text" onClick={() => goProtected('/help/changelog')}>版本记录</Button>
            <Button type="primary" onClick={() => navigate(ctaTarget)}>
              {ctaText}
            </Button>
          </Space>
        </div>
      </header>

      <Content className="landing-content animate-fade-in">
        <section className="landing-hero glass-card shadow-premium">
          <div className="landing-hero-bg bg-mesh-gradient opacity-40 blur-[100px]" aria-hidden="true" />
          <div className="landing-hero-inner">
            <Tag color="purple" className="landing-release-tag border-purple-500/30 bg-purple-500/10 text-purple-400">
              <ThunderboltOutlined style={{ marginRight: 6 }} />
              v{packageJson.version} 正式发布
            </Tag>
            <Title className="landing-title">
              <span className="gradient-text">统一的数据链路</span>
              <br />
              让每一次飞行数据都可追溯
            </Title>
            <Paragraph className="landing-subtitle">
              网络数据分析平台面向试验数据处理与复盘场景，提供从数据接入、任务调度、事件诊断到架次联查的
              一体化工作流，以版本化配置与页面级权限体系，保障分析结论可靠、可复用、可协同。
            </Paragraph>
            <Space size={12} wrap>
              <Button
                type="primary"
                size="large"
                onClick={() => navigate(ctaTarget)}
                icon={<RocketOutlined />}
              >
                {ctaText}
              </Button>
              <Button size="large" onClick={() => goProtected('/help/quickstart')} icon={<ArrowRightOutlined />}>
                先看快速开始
              </Button>
            </Space>
            <Paragraph className="landing-hero-tip">
              {user
                ? '已登录。点击“进入工具集”可直接进入模块选择页面；如需查看说明，可从顶部进入产品介绍或快速开始。'
                : '首次使用建议先阅读 产品介绍 或 快速开始，登录后会自动跳回文档；阅读结束再回到首页点击“开始使用”进入工具集。'}
            </Paragraph>

            <div className="landing-stats">
              {HIGHLIGHT_STATS.map((s) => (
                <div className="landing-stat" key={s.label}>
                  <div className="landing-stat-value">{s.value}</div>
                  <div className="landing-stat-label">{s.label}</div>
                  <div className="landing-stat-hint">{s.hint}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="landing-section animate-slide-up" style={{ animationDelay: '200ms' }}>
          <div className="landing-section-head">
            <Tag className="landing-section-tag border-purple-500/30 bg-purple-500/10 text-purple-400">核心能力</Tag>
            <Title level={2} className="landing-section-title">四大能力，覆盖数据链路关键环节</Title>
            <Paragraph type="secondary" className="landing-section-sub">
              平台围绕飞行数据分析的真实工作流设计，将分散的工具整合为可治理、可扩展的统一平台。
            </Paragraph>
          </div>
          <Row gutter={[20, 20]}>
            {CAPABILITIES.map((item) => (
              <Col xs={24} md={12} key={item.title}>
                <Card className="landing-capability-card" bordered={false}>
                  <div className="landing-capability-icon">{item.icon}</div>
                  <Title level={4} className="landing-capability-title">{item.title}</Title>
                  <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                    {item.desc}
                  </Paragraph>
                </Card>
              </Col>
            ))}
          </Row>
        </section>

        <section className="landing-section animate-slide-up" style={{ animationDelay: '300ms' }}>
          <div className="landing-section-head">
            <Tag className="landing-section-tag border-purple-500/30 bg-purple-500/10 text-purple-400">典型工作流</Tag>
            <Title level={2} className="landing-section-title">从上传到复盘，只需四步</Title>
            <Paragraph type="secondary" className="landing-section-sub">
              每一步都有清晰的页面入口与数据交接，避免在多个工具之间反复切换。
            </Paragraph>
          </div>
          <div className="landing-flow">
            {WORKFLOW_STEPS.map((step, idx) => (
              <div className="landing-flow-item" key={step.title}>
                <div className="landing-flow-index">0{idx + 1}</div>
                <div className="landing-flow-icon">{step.icon}</div>
                <div className="landing-flow-title">{step.title}</div>
                <div className="landing-flow-desc">{step.desc}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="landing-section animate-slide-up" style={{ animationDelay: '400ms' }}>
          <div className="landing-section-head">
            <Tag className="landing-section-tag border-purple-500/30 bg-purple-500/10 text-purple-400">模块一览</Tag>
            <Title level={2} className="landing-section-title">按任务场景分组进入模块文档</Title>
            <Paragraph type="secondary" className="landing-section-sub">
              支持从常用入口到深度分析逐步探索；管理员模块会显示权限提示。
            </Paragraph>
          </div>
          <div className="landing-module-sections">
            {moduleSections.map((section) => (
              <div key={section.key} className="landing-module-group">
                <div className="landing-module-group-head">
                  <Title level={4} className="landing-module-group-title">{section.title}</Title>
                  <Paragraph type="secondary" className="landing-module-group-desc">{section.desc}</Paragraph>
                </div>
                <Row gutter={[16, 16]}>
                  {section.docs.map((doc) => (
                    <Col xs={24} md={12} lg={8} key={doc.key}>
                      <Card
                        hoverable
                        className="landing-module-card"
                        onClick={() => goProtected(`/help/${doc.key}`)}
                        bordered={false}
                      >
                        <Space align="start" size={14}>
                          <div className="landing-module-icon">{MODULE_ICONS[doc.key] || <UserOutlined />}</div>
                          <div>
                            <Space size={8} align="center" wrap>
                              <Text strong className="landing-module-title">{doc.title}</Text>
                              {ADMIN_DOC_KEYS.has(doc.key) ? <Tag color="default">需管理员权限</Tag> : null}
                            </Space>
                            <Paragraph type="secondary" className="landing-module-desc">
                              {doc.summary}
                            </Paragraph>
                          </div>
                        </Space>
                      </Card>
                    </Col>
                  ))}
                </Row>
              </div>
            ))}
          </div>
        </section>

        <section className="landing-section landing-section-quick animate-slide-up" style={{ animationDelay: '500ms' }}>
          <div className="landing-section-head">
            <Tag className="landing-section-tag border-purple-500/30 bg-purple-500/10 text-purple-400">常用入口</Tag>
            <Title level={3} className="landing-section-title">适合已使用用户的快捷跳转</Title>
            <Paragraph type="secondary" className="landing-section-sub">
              已经熟悉平台的用户可以直接跳到常用页面；第一次使用的用户建议先通过上方的“产品介绍”或“快速开始”了解整体流程。
            </Paragraph>
          </div>
          <Row gutter={[16, 16]}>
            {QUICK_START_LINKS.map((item) => (
              <Col xs={24} md={8} key={item.key}>
                <Card className="landing-quick-card" bordered={false}>
                  <Text strong className="landing-quick-title">{item.title}</Text>
                  <Paragraph type="secondary" className="landing-quick-desc">
                    {item.desc}
                  </Paragraph>
                  <Button
                    type="link"
                    className="landing-quick-action"
                    onClick={() => (item.requiresAuth ? goProtected(item.target) : navigate(item.target))}
                  >
                    立即进入
                  </Button>
                </Card>
              </Col>
            ))}
          </Row>
        </section>

        <section className="landing-cta">
          <div className="landing-cta-inner">
            <div>
              <Title level={2} className="landing-cta-title">准备好让数据分析更高效？</Title>
              <Paragraph type="secondary" className="landing-cta-sub">
                登录平台，几分钟内完成首次上传与解析，开启跨模块协同的新工作方式。
              </Paragraph>
            </div>
            <Space size={12}>
              <Button
                type="primary"
                size="large"
                onClick={() => navigate(ctaTarget)}
                icon={<RocketOutlined />}
              >
                {ctaText}
              </Button>
              <Button size="large" onClick={() => goProtected('/help/quickstart')}>
                阅读快速开始
              </Button>
            </Space>
          </div>
        </section>
      </Content>

      <Footer className="landing-footer">
        <div className="landing-footer-inner">
          <div className="landing-footer-brand">
            <div className="landing-brand-logo sm"><DatabaseOutlined /></div>
            <div>
              <div className="landing-brand-name">网络数据分析平台</div>
              <div className="landing-footer-copy">面向飞行试验数据的统一分析与治理平台</div>
            </div>
          </div>
          <div className="landing-footer-meta">
            <span>v{packageJson.version}</span>
            <span>·</span>
            <span>Internal Release</span>
            <span>·</span>
            <span>文档与说明以站内帮助中心为准</span>
          </div>
        </div>
      </Footer>
    </Layout>
  )
}

export default LandingPage
