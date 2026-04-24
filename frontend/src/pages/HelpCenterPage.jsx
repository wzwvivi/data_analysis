import React, { useEffect, useMemo, useState } from 'react'
import { Button, Card, Col, Empty, Row, Space, Typography } from 'antd'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { AppstoreOutlined, FileTextOutlined, HomeOutlined, PrinterOutlined } from '@ant-design/icons'
import DocSidebar from '../components/help/DocSidebar'
import DocRenderer from '../components/help/DocRenderer'
import DocSearch from '../components/help/DocSearch'
import DocTOC from '../components/help/DocTOC'
import { DOC_MAP, DOCS, getDocGroups } from '../content/docs/manifest'
import '../styles/help.css'

const { Title, Paragraph } = Typography

function slugifyHeading(text) {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^\w\u4e00-\u9fa5\s-]/g, '')
    .replace(/\s+/g, '-')
}

function extractHeadings(raw) {
  const lines = raw.split('\n')
  const headings = []
  for (const line of lines) {
    const match = line.match(/^(#{1,3})\s+(.+)$/)
    if (!match) continue
    const level = match[1].length
    const text = match[2].trim()
    headings.push({ id: slugifyHeading(text), level, text })
  }
  return headings
}

function HelpCenterPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { moduleKey } = useParams()
  const isPublicDocs = location.pathname.startsWith('/docs')
  const docBasePath = isPublicDocs ? '/docs' : '/help'
  const groups = useMemo(() => getDocGroups(), [])
  const docs = useMemo(() => DOCS, [])
  const currentKey = moduleKey || 'overview'
  const currentDoc = DOC_MAP[currentKey] || DOC_MAP.overview
  const headings = useMemo(() => extractHeadings(currentDoc.raw), [currentDoc.raw])
  const [activeHeading, setActiveHeading] = useState('')

  useEffect(() => {
    const hash = location.hash ? decodeURIComponent(location.hash.slice(1)) : ''
    if (!hash) {
      window.scrollTo({ top: 0, behavior: 'smooth' })
      return
    }
    const target = document.getElementById(hash)
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [location.hash, currentKey])

  useEffect(() => {
    const elements = headings
      .map((heading) => document.getElementById(heading.id))
      .filter(Boolean)
    if (!elements.length) return undefined

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) {
          setActiveHeading(visible[0].target.id)
        }
      },
      { rootMargin: '-30% 0px -60% 0px', threshold: 0.1 },
    )

    elements.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [headings, currentKey])

  const handleOpenDoc = (docKey) => {
    navigate(`${docBasePath}/${docKey}`)
  }

  return (
    <div className="help-center-page">
      <Card className="help-center-header no-print">
        <div className="help-center-header-inner">
          <div>
            <Title level={3} style={{ marginBottom: 4 }}>
              帮助中心
            </Title>
            <Paragraph type="secondary" style={{ marginBottom: 0 }}>
              网络数据分析平台使用文档（中文为主，保留必要英文术语）
            </Paragraph>
          </div>
          <Space size={8} wrap>
            <Button icon={<HomeOutlined />} onClick={() => navigate('/')}>
              返回首页
            </Button>
            <Button type="primary" icon={<AppstoreOutlined />} onClick={() => navigate('/modules')}>
              进入工具集
            </Button>
          </Space>
        </div>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={6} xl={5} className="no-print">
          <Card>
            <DocSearch docs={docs} onOpenDoc={handleOpenDoc} />
            <div style={{ marginTop: 16 }}>
              <DocSidebar groups={groups} currentKey={currentDoc.key} onSelect={handleOpenDoc} />
            </div>
          </Card>
        </Col>

        <Col xs={24} lg={12} xl={13}>
          <Card className="doc-main-card">
            <div className="doc-title-row">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <FileTextOutlined />
                <span>{currentDoc.title}</span>
              </div>
              <Button className="no-print" icon={<PrinterOutlined />} onClick={() => window.print()}>
                打印
              </Button>
            </div>
            {currentDoc ? (
              <DocRenderer raw={currentDoc.raw} />
            ) : (
              <Empty description="未找到文档" />
            )}

            {currentDoc ? (
              <div className="doc-bottom-cta no-print">
                <div className="doc-bottom-cta-text">
                  <div className="doc-bottom-cta-title">阅读完成？</div>
                  <div className="doc-bottom-cta-sub">
                    可以返回首页再点击“开始使用”，或直接进入工具集按角色选择可用模块。
                  </div>
                </div>
                <Space size={8} wrap>
                  <Button icon={<HomeOutlined />} onClick={() => navigate('/')}>
                    返回首页
                  </Button>
                  <Button
                    type="primary"
                    icon={<AppstoreOutlined />}
                    onClick={() => navigate('/modules')}
                  >
                    我已了解，进入工具集
                  </Button>
                </Space>
              </div>
            ) : null}
          </Card>
        </Col>

        <Col xs={24} lg={6} xl={6} className="no-print">
          <Card>
            <DocTOC headings={headings} activeKey={activeHeading} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default HelpCenterPage
