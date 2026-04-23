import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
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
  CheckCircleFilled,
  ExclamationCircleFilled,
  CloseCircleFilled,
  ReloadOutlined,
  ThunderboltOutlined,
  FileTextOutlined,
  CopyOutlined,
  WarningFilled,
  FileDoneOutlined,
  DownloadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import { deviceProtocolApi } from '../../services/api'

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

function copyToClipboard(text) {
  try {
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(text)
      return true
    }
    return false
  } catch {
    return false
  }
}

function StatusHero({ hasReport, errorCount, warningCount }) {
  let variant = 'hero-green'
  let icon = <CheckCircleFilled />
  let title = '可直接激活'
  let desc = 'Bundle 已落盘 / 体检无阻断项，管理员可立即激活此版本。'

  if (!hasReport) {
    variant = 'hero-yellow'
    icon = <ExclamationCircleFilled />
    title = '等待生成体检报告…'
    desc = '正在生成 device_bundle 并校验 spec，请稍候。'
  } else if (errorCount > 0) {
    variant = 'hero-red'
    icon = <CloseCircleFilled />
    title = `存在 ${errorCount} 项阻断错误`
    desc = '激活前需解决错误，或提交强制激活并填写理由。'
  } else if (warningCount > 0) {
    variant = 'hero-yellow'
    icon = <ExclamationCircleFilled />
    title = `${warningCount} 项警告需确认`
    desc = '无阻断错误，但有若干需管理员确认的提示项。'
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

/**
 * 设备协议激活闸门面板 —— 仅当 version.availability_status === 'PendingCode' 渲染。
 *
 * 数据来源（GET /api/device-protocol/versions/{id}/activation-report）：
 * {
 *   report: {
 *     ok, errors: [], warnings: [], error_count, warning_count,
 *     artifacts: [{ kind:'device_bundle', path, sha256, bytes, stats:{...}, generated_at }],
 *     summary: {...}, checked_at
 *   }
 * }
 */
function DeviceActivationPanel({ version, canWrite, isAdmin, onActivated }) {
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
      const res = await deviceProtocolApi.getActivationReport(version.id)
      setData(res.data)
    } catch (err) {
      message.error(err?.response?.data?.detail || '加载体检报告失败')
    } finally {
      setLoading(false)
    }
  }, [version.id])

  useEffect(() => { loadReport() }, [loadReport])

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      const res = await deviceProtocolApi.refreshActivationReport(version.id)
      setData(res.data)
      message.success('已重新生成 device_bundle 并重跑体检')
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
      await deviceProtocolApi.activateVersion(version.id, {
        force: !!force,
        reason: force ? forceReason.trim() : undefined,
      })
      message.success('设备协议版本已激活')
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

  const report = data?.report || null
  const hasReport = Boolean(report)
  const errors = report?.errors || []
  const warnings = report?.warnings || []
  const errorCount = report?.error_count ?? errors.length
  const warningCount = report?.warning_count ?? warnings.length
  const artifacts = report?.artifacts || []

  const bundleArtifact = useMemo(
    () => artifacts.find((a) => a.kind === 'device_bundle') || null,
    [artifacts],
  )

  const bundleTag = bundleArtifact?.stats
    ? (
        <Tooltip
          title={`labels=${bundleArtifact.stats.labels || 0} / bnr_fields=${bundleArtifact.stats.bnr_fields || 0} / discrete_bits=${bundleArtifact.stats.discrete_bits || 0} / bcd_pattern=${bundleArtifact.stats.bcd_pattern_count || 0} / port_override=${bundleArtifact.stats.port_override_count || 0}`}
        >
          <Tag color="purple">
            {bundleArtifact.stats.labels || 0}L · {bundleArtifact.stats.bnr_fields || 0}bnr · {bundleArtifact.stats.bcd_pattern_count || 0}bcd
          </Tag>
        </Tooltip>
      )
    : null

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
        <Text strong style={{ color: '#e4e4e7' }}>设备协议产物已落盘</Text>
        <Tooltip title="device_bundle.json 是 parser 运行期消费的版本化快照；前端不做内联预览，请通过下载按钮审阅。">
          <Tag color="purple" style={{ marginLeft: 4 }}>运行期将从此 bundle 读取 label 定义</Tag>
        </Tooltip>
      </Space>
      {artifacts.map((a) => (
        <div key={a.path} className="artifact-row mono" style={{
          display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
          padding: '6px 0', fontSize: 12,
        }}>
          <FileTextOutlined style={{ color: '#a78bfa', fontSize: 14 }} />
          <Text code style={{ flex: 1, minWidth: 260, fontSize: 12, wordBreak: 'break-all' }}>
            {a.path}
          </Text>
          <Tooltip title={`SHA256: ${a.sha256 || '-'}`}>
            <Tag color="default" style={{ margin: 0 }}>
              sha256 {a.sha256?.slice(0, 10) || '-'}…
            </Tag>
          </Tooltip>
          {a.bytes != null ? <Tag>{Math.round(a.bytes / 1024)} KB</Tag> : null}
          <Tooltip title={formatTime(a.generated_at)}>
            <Text type="secondary" style={{ fontSize: 11 }}>
              {formatRelative(a.generated_at) || '-'}
            </Text>
          </Tooltip>
          {a.kind === 'device_bundle' ? bundleTag : null}
          <Tooltip title="复制路径">
            <Button
              size="small"
              type="text"
              icon={<CopyOutlined />}
              onClick={() => {
                if (copyToClipboard(a.path)) message.success('已复制路径')
              }}
            />
          </Tooltip>
          {a.kind === 'device_bundle' ? (
            <Tooltip title="下载 bundle.json 查看内容">
              <Button
                size="small"
                type="text"
                icon={<DownloadOutlined />}
                href={deviceProtocolApi.downloadBundleUrl(version.id)}
                target="_blank"
                rel="noreferrer"
              />
            </Tooltip>
          ) : null}
        </div>
      ))}
    </div>
  ) : (
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 14 }}
      message="尚未生成设备协议产物"
      description="非 arinc429 family 或产物生成失败时此列表为空。可点击『刷新体检』重新生成。"
    />
  )

  const renderMsgRow = (text, idx, sev) => (
    <div
      key={`${sev}-${idx}`}
      style={{
        padding: '6px 10px',
        marginBottom: 6,
        background: sev === 'error' ? 'rgba(255,77,79,0.08)' : 'rgba(250,173,20,0.08)',
        border: `1px solid ${sev === 'error' ? 'rgba(255,77,79,0.3)' : 'rgba(250,173,20,0.3)'}`,
        borderRadius: 6,
        color: '#e4e4e7',
        fontSize: 13,
        lineHeight: 1.5,
      }}
    >
      {sev === 'error' ? <CloseCircleFilled style={{ color: '#ff6868', marginRight: 6 }} /> : <ExclamationCircleFilled style={{ color: '#e3b959', marginRight: 6 }} />}
      <span style={{ wordBreak: 'break-word' }}>{text}</span>
    </div>
  )

  const collapseItems = [
    {
      key: 'errors',
      label: (
        <Space>
          <CloseCircleFilled style={{ color: '#ff6868' }} />
          <Text strong>阻断错误</Text>
          <Tag color={errorCount > 0 ? 'error' : 'default'}>{errorCount}</Tag>
        </Space>
      ),
      children: errors.length
        ? errors.map((m, i) => renderMsgRow(m, i, 'error'))
        : <Empty description="无错误" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
    },
    {
      key: 'warnings',
      label: (
        <Space>
          <ExclamationCircleFilled style={{ color: '#e3b959' }} />
          <Text strong>警告</Text>
          <Tag color={warningCount > 0 ? 'warning' : 'default'}>{warningCount}</Tag>
        </Space>
      ),
      children: warnings.length
        ? warnings.map((m, i) => renderMsgRow(m, i, 'warning'))
        : <Empty description="无警告" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
    },
  ]

  return (
    <Card
      size="small"
      title={
        <Space>
          <ThunderboltOutlined style={{ color: '#a78bfa' }} />
          <span>激活闸门</span>
          <Tag color="gold">PendingCode</Tag>
          <Text type="secondary" style={{ fontSize: 12 }}>
            管理员审阅 bundle 与体检后点击「激活」→ Available，用户即可在上传页选择。
          </Text>
        </Space>
      }
      bordered
      loading={loading}
    >
      <StatusHero
        hasReport={hasReport}
        errorCount={errorCount}
        warningCount={warningCount}
      />

      {artifactBlock}

      <Space wrap style={{ margin: '10px 0 14px' }} size={10}>
        {canWrite ? (
          <Button
            icon={<ReloadOutlined spin={refreshing} />}
            loading={refreshing || loading}
            onClick={handleRefresh}
          >
            刷新体检（重新生成 bundle）
          </Button>
        ) : null}

        {isAdmin ? (
          <>
            <Popconfirm
              title={`激活 ${version.version_name}？`}
              description="激活后用户即可在上传解析时选择该设备协议版本。"
              disabled={errorCount > 0}
              onConfirm={() => handleActivate(false)}
              okText="确认激活"
              cancelText="取消"
            >
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                disabled={errorCount > 0}
                loading={activating}
                style={{ minWidth: 200, fontWeight: 600 }}
              >
                {errorCount > 0 ? '存在阻断错误，无法激活' : `激活 ${version.version_name} → Available`}
              </Button>
            </Popconfirm>

            {errorCount > 0 ? (
              <Button danger icon={<WarningFilled />} onClick={() => setForceOpen(true)}>
                强制激活…
              </Button>
            ) : null}
          </>
        ) : (
          <Alert
            type="info"
            showIcon
            message="仅 device_team / admin 可激活此版本"
            style={{ marginBottom: 0, padding: '4px 12px' }}
          />
        )}
      </Space>

      <Collapse
        defaultActiveKey={errorCount > 0 ? ['errors'] : (warningCount > 0 ? ['warnings'] : [])}
        items={collapseItems}
        bordered={false}
        style={{ background: 'transparent' }}
      />

      <Modal
        title={(
          <Space>
            <WarningFilled style={{ color: '#ff6868' }} />
            <span>强制激活（跳过 {errorCount} 项错误）</span>
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
          message={`当前体检存在 ${errorCount} 项错误`}
          description="强制激活意味着运行期 parser 消费该 bundle 时可能遇到未覆盖的 label。仅在设备团队已确认可接受的前提下使用。此操作会记入审计字段。"
        />
        <Paragraph style={{ marginBottom: 6, fontSize: 13, color: '#d4d4d8' }}>
          强制激活理由 <Text type="danger">*</Text>
        </Paragraph>
        <Input.TextArea
          rows={3}
          value={forceReason}
          onChange={(e) => setForceReason(e.target.value)}
          placeholder="必填：请描述为何可以跳过这些错误（如『缺失的 label 在当前机型不会出现』等）"
          style={{ marginBottom: 12 }}
        />
        <Checkbox
          checked={forceConfirmed}
          onChange={(e) => setForceConfirmed(e.target.checked)}
        >
          我已理解并为此操作负责（将记录到审计字段）
        </Checkbox>
      </Modal>
    </Card>
  )
}

export default DeviceActivationPanel
