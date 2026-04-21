import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Checkbox,
  Collapse,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Space,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  CheckCircleTwoTone,
  ExclamationCircleTwoTone,
  CloseCircleTwoTone,
  CheckCircleFilled,
  ExclamationCircleFilled,
  CloseCircleFilled,
  ReloadOutlined,
  ThunderboltOutlined,
  FileTextOutlined,
  CopyOutlined,
  WarningFilled,
  FileDoneOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import { networkConfigApi } from '../../services/api'

dayjs.extend(relativeTime)

const { Text, Paragraph } = Typography

function formatTime(v) {
  if (!v) return '-'
  try {
    return dayjs(v).format('YYYY-MM-DD HH:mm:ss')
  } catch {
    return String(v)
  }
}

function formatRelative(v) {
  if (!v) return ''
  try {
    return dayjs(v).locale('zh-cn').fromNow()
  } catch {
    return ''
  }
}

const SEVERITY_META = {
  green:  { color: 'success', label: '可激活',   icon: <CheckCircleTwoTone twoToneColor="#52c41a" /> },
  yellow: { color: 'warning', label: '需确认',   icon: <ExclamationCircleTwoTone twoToneColor="#faad14" /> },
  red:    { color: 'error',   label: '阻断激活', icon: <CloseCircleTwoTone twoToneColor="#ff4d4f" /> },
}

function SeverityTag({ severity }) {
  const meta = SEVERITY_META[severity] || SEVERITY_META.green
  return <Tag color={meta.color} icon={meta.icon}>{meta.label}</Tag>
}

function copyToClipboard(text) {
  try {
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(text)
      return true
    }
    const el = document.createElement('textarea')
    el.value = text
    document.body.appendChild(el)
    el.select()
    document.execCommand('copy')
    document.body.removeChild(el)
    return true
  } catch {
    return false
  }
}

/**
 * Hero banner that summarises the overall gate status at a glance.
 * Colour follows the highest severity present.
 */
function StatusHero({ summary, redCount, yellowCount, greenCount, hasReport }) {
  let variant = 'hero-green'
  let icon = <CheckCircleFilled />
  let title = '可直接激活'
  let desc = '所有差异项均为安全/信息级别，管理员可立即激活此版本。'

  if (!hasReport) {
    variant = 'hero-yellow'
    icon = <ExclamationCircleFilled />
    title = '等待生成体检报告…'
    desc = '正在分析本版本与基线的差异，请稍候。'
  } else if (redCount > 0) {
    variant = 'hero-red'
    icon = <CloseCircleFilled />
    title = `存在 ${redCount} 项阻断风险`
    desc = '激活前需解决阻断项，或提交强制激活申请并填写理由。'
  } else if (yellowCount > 0) {
    variant = 'hero-yellow'
    icon = <ExclamationCircleFilled />
    title = `${yellowCount} 项需要确认`
    desc = '无阻断项，但有若干需管理员确认的提示项。建议审阅后激活。'
  } else if ((summary.green || 0) === 0 && greenCount === 0) {
    variant = 'hero-green'
    icon = <CheckCircleFilled />
    title = '首次发布 · 无基线差异'
    desc = '未找到可比对的基线版本，可直接激活。'
  }

  return (
    <div className={`activation-hero ${variant}`}>
      <div className="hero-icon">{icon}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="hero-title">{title}</div>
        <div className="hero-desc">{desc}</div>
      </div>
    </div>
  )
}

function SeverityStat({ severity, label, value, hint }) {
  const sev = `sev-${severity}`
  return (
    <div className={`severity-stat ${sev}`}>
      <div className="severity-stat-label">
        {severity === 'green' && <CheckCircleFilled style={{ color: '#7fdb85' }} />}
        {severity === 'yellow' && <ExclamationCircleFilled style={{ color: '#e3b959' }} />}
        {severity === 'red' && <CloseCircleFilled style={{ color: '#ff6868' }} />}
        <span>{label}</span>
      </div>
      <div className={`severity-stat-value ${sev}`}>{value}</div>
      {hint ? <div style={{ fontSize: 11, color: '#71717a' }}>{hint}</div> : null}
    </div>
  )
}

/**
 * 激活闸门面板 —— 仅当 version.availability_status === 'PendingCode' 时渲染。
 *
 * Props:
 *   version:   { id, availability_status, version, protocol_name, ... }
 *   canWrite:  network_team / admin 可刷新体检
 *   isAdmin:   admin 才能点击激活
 *   onActivated: () => void  激活成功回调（父组件 reload 数据）
 */
function ActivationPanel({ version, canWrite, isAdmin, onActivated }) {
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [activating, setActivating] = useState(false)
  const [data, setData] = useState(null)

  const [forceOpen, setForceOpen] = useState(false)
  const [forceConfirmed, setForceConfirmed] = useState(false)
  const [forceReason, setForceReason] = useState('')

  const loadReport = useCallback(async () => {
    setLoading(true)
    try {
      const res = await networkConfigApi.getActivationReport(version.id)
      setData(res.data)
    } catch (err) {
      message.error(err?.response?.data?.detail || '加载体检报告失败')
    } finally {
      setLoading(false)
    }
  }, [version.id])

  useEffect(() => {
    loadReport()
  }, [loadReport])

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      const res = await networkConfigApi.refreshActivationReport(version.id)
      setData(res.data)
      message.success('已重新生成代码产物并重跑体检')
    } catch (err) {
      message.error(err?.response?.data?.detail || '刷新失败')
    } finally {
      setRefreshing(false)
    }
  }

  const handleActivate = async (force) => {
    if (force && !forceReason.trim()) {
      message.warning('请填写强制激活理由')
      return
    }
    setActivating(true)
    try {
      await networkConfigApi.activateVersion(version.id, {
        force: !!force,
        reason: force ? forceReason.trim() : undefined,
      })
      message.success('协议版本已激活')
      setForceOpen(false)
      setForceReason('')
      setForceConfirmed(false)
      if (onActivated) onActivated()
    } catch (err) {
      message.error(err?.response?.data?.detail || '激活失败')
    } finally {
      setActivating(false)
    }
  }

  const summary = data?.report?.summary || { green: 0, yellow: 0, red: 0 }
  const items = data?.report?.items || []
  const redCount = summary.red || 0
  const yellowCount = summary.yellow || 0
  const greenCount = summary.green || 0
  const artifacts = data?.artifacts || []
  const hasReport = Boolean(data?.report)

  const itemsBySeverity = useMemo(() => {
    const map = { red: [], yellow: [], green: [] }
    for (const it of items) {
      const sev = it.severity || 'green'
      ;(map[sev] || map.green).push(it)
    }
    return map
  }, [items])

  const renderItem = (it, idx) => (
    <div
      key={`${it.kind}-${it.port || 'x'}-${it.field_name || ''}-${idx}`}
      className={`report-item sev-${it.severity || 'green'}`}
    >
      <div className="report-item-title">
        <SeverityTag severity={it.severity} />
        <Tag color="default">{it.kind}</Tag>
        {it.port != null ? <Tag color="blue">端口 {it.port}</Tag> : null}
        {it.protocol_family ? <Tag color="geekblue">{it.protocol_family}</Tag> : null}
        {it.field_name ? <Tag>{it.field_name}</Tag> : null}
      </div>
      <div className="report-item-message">{it.message}</div>
      {it.suggested_action ? (
        <div className="report-item-hint">
          <Text type="secondary" style={{ fontSize: 12 }}>建议：</Text>
          <Text style={{ fontSize: 12, color: '#c4b5fd' }}>{it.suggested_action}</Text>
        </div>
      ) : null}
      {it.matched_parser_keys?.length ? (
        <div className="report-item-hint" style={{ marginTop: 2 }}>
          命中 parser：{it.matched_parser_keys.join(', ')}
        </div>
      ) : null}
    </div>
  )

  const collapseItems = [
    {
      key: 'red',
      label: (
        <Space>
          <CloseCircleFilled style={{ color: '#ff6868' }} />
          <Text strong>阻断项</Text>
          <Tag color={redCount > 0 ? 'error' : 'default'}>{redCount}</Tag>
        </Space>
      ),
      children: itemsBySeverity.red.length
        ? itemsBySeverity.red.map(renderItem)
        : <Empty description="无阻断项" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
    },
    {
      key: 'yellow',
      label: (
        <Space>
          <ExclamationCircleFilled style={{ color: '#e3b959' }} />
          <Text strong>需确认</Text>
          <Tag color={yellowCount > 0 ? 'warning' : 'default'}>{yellowCount}</Tag>
        </Space>
      ),
      children: itemsBySeverity.yellow.length
        ? itemsBySeverity.yellow.map(renderItem)
        : <Empty description="无黄项" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
    },
    {
      key: 'green',
      label: (
        <Space>
          <CheckCircleFilled style={{ color: '#7fdb85' }} />
          <Text strong>可直接激活</Text>
          <Tag color={greenCount > 0 ? 'success' : 'default'}>{greenCount}</Tag>
        </Space>
      ),
      children: itemsBySeverity.green.length
        ? itemsBySeverity.green.map(renderItem)
        : <Empty description="无绿项" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
    },
  ]

  const artifactBlock = artifacts.length ? (
    <div style={{
      marginBottom: 14,
      padding: '12px 14px',
      border: '1px solid rgba(139, 92, 246, 0.28)',
      borderRadius: 10,
      background: 'linear-gradient(135deg, rgba(139,92,246,0.06), rgba(24,24,27,0.4))',
    }}>
      <Space align="center" size={10} style={{ marginBottom: 10 }}>
        <FileDoneOutlined style={{ fontSize: 18, color: '#c4b5fd' }} />
        <Text strong style={{ color: '#e4e4e7' }}>代码产物已落盘</Text>
        <Tooltip title="Tier 2 自动生成的 TSN 层级元数据，管理员请在服务器/git 中审阅；前端不提供内联代码预览">
          <Tag color="purple" style={{ marginLeft: 4 }}>请在后端/Git 审阅</Tag>
        </Tooltip>
      </Space>
      {artifacts.map((a) => (
        <div key={a.path} className="artifact-row mono" style={{ fontSize: 12 }}>
          <FileTextOutlined style={{ color: '#a78bfa', fontSize: 14 }} />
          <Text code style={{ flex: 1, minWidth: 200, fontSize: 12, wordBreak: 'break-all' }}>
            {a.path}
          </Text>
          <Tooltip title={`SHA256: ${a.sha256 || '-'}`}>
            <Tag color="default" style={{ margin: 0 }}>
              sha256 {a.sha256?.slice(0, 10) || '-'}…
            </Tag>
          </Tooltip>
          <Tooltip title={formatTime(a.generated_at)}>
            <Text type="secondary" style={{ fontSize: 11 }}>
              {formatRelative(a.generated_at) || '-'}
            </Text>
          </Tooltip>
          {a.stats ? (
            a.kind === 'bundle' ? (
              <Tooltip title={`schema=v${a.stats.schema_version || 1} / ports=${a.stats.ports || 0} / families=${a.stats.families || 0} / rules=${a.stats.event_rules_default_v1 || 0}`}>
                <Tag color="purple">
                  {a.stats.ports || 0}p · {a.stats.families || 0}f · {a.stats.event_rules_default_v1 || 0}r
                </Tag>
              </Tooltip>
            ) : (
              <Tooltip title={`families=${a.stats.families} / ports_with_family=${a.stats.ports_with_family}`}>
                <Tag>{a.stats.families}f · {a.stats.ports_with_family}p</Tag>
              </Tooltip>
            )
          ) : null}
          <Tooltip title="复制文件路径到剪贴板">
            <Button
              size="small"
              type="text"
              icon={<CopyOutlined />}
              onClick={() => {
                if (copyToClipboard(a.path)) message.success('已复制路径')
              }}
            />
          </Tooltip>
        </div>
      ))}
    </div>
  ) : null

  return (
    <div>
      <StatusHero
        summary={summary}
        redCount={redCount}
        yellowCount={yellowCount}
        greenCount={greenCount}
        hasReport={hasReport}
      />

      {artifactBlock}

      <div style={{
        display: 'flex',
        gap: 12,
        flexWrap: 'wrap',
        marginBottom: 14,
      }}>
        <SeverityStat
          severity="green"
          label="可激活"
          value={greenCount}
          hint="与基线兼容的安全变更"
        />
        <SeverityStat
          severity="yellow"
          label="需确认"
          value={yellowCount}
          hint="建议审阅后激活"
        />
        <SeverityStat
          severity="red"
          label="阻断项"
          value={redCount}
          hint={redCount > 0 ? '激活前需解决' : '无阻断项'}
        />
        <div className="severity-stat" style={{ minWidth: 200, flex: '1 1 240px', borderLeft: '3px solid #8b5cf6' }}>
          <div className="severity-stat-label">
            <FileDoneOutlined style={{ color: '#c4b5fd' }} />
            <span>体检信息</span>
          </div>
          <div style={{ fontSize: 12, color: '#d4d4d8', marginTop: 4 }}>
            <Tooltip title={formatTime(data?.report_generated_at)}>
              <span>生成于 {formatRelative(data?.report_generated_at) || '-'}</span>
            </Tooltip>
          </div>
          <div style={{ fontSize: 11, color: '#71717a' }}>
            {data?.report?.base_version_label
              ? `对比基线 ${data.report.base_version_label}`
              : '无基线版本（首次发布）'}
          </div>
        </div>
      </div>

      <Space wrap style={{ marginBottom: 14 }} size={10}>
        {canWrite ? (
          <Button
            icon={<ReloadOutlined spin={refreshing} />}
            loading={refreshing || loading}
            onClick={handleRefresh}
          >
            刷新体检
          </Button>
        ) : null}

        {isAdmin ? (
          <>
            <Popconfirm
              title={`激活版本 ${version.version}？`}
              description="激活后终端用户即可在上传解析 / 事件分析时选择此版本。"
              disabled={redCount > 0}
              onConfirm={() => handleActivate(false)}
              okText="确认激活"
              cancelText="取消"
            >
              <Button
                type="primary"
                size="middle"
                icon={<ThunderboltOutlined />}
                disabled={redCount > 0}
                loading={activating}
                style={{
                  minWidth: 180,
                  fontWeight: 600,
                }}
              >
                {redCount > 0 ? '存在阻断项，无法激活' : `激活 ${version.version} → Available`}
              </Button>
            </Popconfirm>

            {redCount > 0 ? (
              <Button
                danger
                icon={<WarningFilled />}
                onClick={() => setForceOpen(true)}
              >
                强制激活…
              </Button>
            ) : null}
          </>
        ) : (
          <Alert
            type="info"
            showIcon
            message="仅管理员可激活此版本"
            style={{ marginBottom: 0, padding: '4px 12px' }}
          />
        )}
      </Space>

      {items.length === 0 && !loading ? (
        <Empty description="无任何差异项（首次发布或与基线版本完全一致）" />
      ) : (
        <Collapse
          defaultActiveKey={redCount > 0 ? ['red'] : (yellowCount > 0 ? ['yellow'] : ['green'])}
          items={collapseItems}
          bordered={false}
          style={{ background: 'transparent' }}
        />
      )}

      <Modal
        title={(
          <Space>
            <WarningFilled style={{ color: '#ff6868' }} />
            <span>强制激活（跳过 {redCount} 项阻断）</span>
          </Space>
        )}
        open={forceOpen}
        onCancel={() => setForceOpen(false)}
        onOk={() => handleActivate(true)}
        okButtonProps={{ danger: true, disabled: !forceConfirmed || !forceReason.trim() }}
        okText="确认强制激活"
        cancelText="取消"
        confirmLoading={activating}
        destroyOnClose
        width={560}
      >
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 14 }}
          message={`当前体检存在 ${redCount} 项阻断风险`}
          description="强制激活意味着端用户可能看到解析不完整的端口。仅在设备团队已确认代码 MR 已合入、或业务上可接受的前提下使用。此操作会记入审计字段。"
        />
        <Paragraph style={{ marginBottom: 6, fontSize: 13, color: '#d4d4d8' }}>
          强制激活理由 <Text type="danger">*</Text>
        </Paragraph>
        <Input.TextArea
          rows={3}
          value={forceReason}
          onChange={(e) => setForceReason(e.target.value)}
          placeholder="必填：请描述为何可以跳过阻断项（如『MCU parser MR!1234 已合入』、『客户已接受此端口先行上线』等）"
          style={{ marginBottom: 12 }}
        />
        <Checkbox
          checked={forceConfirmed}
          onChange={(e) => setForceConfirmed(e.target.checked)}
        >
          我已理解并为此操作负责（会记录到审计字段）
        </Checkbox>
      </Modal>
    </div>
  )
}

export default ActivationPanel
