import React from 'react'
import { Anchor, Typography } from 'antd'

const { Text } = Typography

function DocTOC({ headings, activeKey }) {
  if (!headings.length) {
    return (
      <div className="doc-toc-empty">
        <Text type="secondary">当前文档暂无目录</Text>
      </div>
    )
  }

  return (
    <div>
      <div className="doc-toc-title">本页目录</div>
      <Anchor
        affix={false}
        getCurrentAnchor={() => (activeKey ? `#${activeKey}` : '')}
        items={headings.map((item) => ({
          key: item.id,
          href: `#${item.id}`,
          title: <span className={`doc-toc-item doc-toc-level-${item.level}`}>{item.text}</span>,
        }))}
      />
    </div>
  )
}

export default DocTOC
