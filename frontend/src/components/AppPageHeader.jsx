import React from 'react'

/**
 * 统一的功能页顶部区域，风格对齐工具集页面（ModuleHubPage）。
 *
 * Props:
 *  - variant:   'default' | 'lite'  ——
 *               - default: 与深色 shell（.app-page-shell）配合的完整 Hero
 *               - lite:    轻量版，只换标题栏，不需要套 shell；适合高信息密度工作面板
 *  - icon:      顶部圆角图标（ReactNode）
 *  - eyebrow:   小字分类标签
 *  - title:     主标题
 *  - subtitle:  副标题 / 说明
 *  - tags:      [{ text, tone: 'accent'|'neutral' }]
 *  - metrics:   [{ label, value, tone: 'purple'|'green'|'blue'|'gray'|'orange' }]
 *               仅 lite 变体使用，会在标题下方渲染一行紧凑统计
 *  - actions:   右侧操作区
 */
function AppPageHeader({
  variant = 'default',
  icon,
  eyebrow,
  title,
  subtitle,
  tags,
  metrics,
  actions,
}) {
  const className = `app-page-header${variant === 'lite' ? ' app-page-header-lite' : ''}`
  return (
    <div className={className}>
      <div className="app-page-header-row">
        <div className="app-page-header-left">
          {icon && <div className="app-page-header-icon">{icon}</div>}
          <div className="app-page-header-text">
            {eyebrow && <div className="app-page-eyebrow">{eyebrow}</div>}
            {title && <h1 className="app-page-title">{title}</h1>}
            {subtitle && <div className="app-page-subtitle">{subtitle}</div>}
            {Array.isArray(tags) && tags.length > 0 && (
              <div className="app-page-header-tags">
                {tags.map((t, i) => (
                  <span
                    key={i}
                    className={`app-page-tag${t.tone === 'neutral' ? ' neutral' : ''}`}
                  >
                    {t.text}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
        {actions && <div className="app-page-header-actions">{actions}</div>}
      </div>

      {variant === 'lite' && Array.isArray(metrics) && metrics.length > 0 && (
        <div className="app-page-header-metrics">
          {metrics.map((m, i) => (
            <div key={i} className="app-page-header-metric">
              <span className="app-page-header-metric-label">{m.label}</span>
              <span className={`app-page-header-metric-value${m.tone ? ` accent-${m.tone}` : ''}`}>
                {m.value}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default AppPageHeader
