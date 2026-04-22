import React, { useMemo } from 'react'
import { Alert, Descriptions, Empty, Space, Table, Tabs, Tag, Typography } from 'antd'

const { Text } = Typography

/**
 * 结构化展示家族 handler diff_spec 的结果。
 *
 * 入参 diff 约定：
 *   {
 *     items_added: [{ key, name, ... }],
 *     items_removed: [{ key, name, ... }],
 *     items_changed: [{ key, name, changes: { <field>: { old, new } | any } }],
 *     meta_changed: { <key>: { old, new } },
 *     summary: { added, removed, changed, meta_changed },
 *   }
 */
function SpecDiffView({ diff, emptyHint = '无变更' }) {
  const safe = diff || {}
  const summary = safe.summary || {}
  const metaChangedEntries = useMemo(
    () => Object.entries(safe.meta_changed || {}),
    [safe.meta_changed],
  )

  const hasAny =
    (summary.added || 0) +
      (summary.removed || 0) +
      (summary.changed || 0) +
      (summary.meta_changed || 0) >
    0

  if (!diff || !diff.summary) {
    return <Alert type="info" message={emptyHint} showIcon />
  }

  const addedColumns = [
    { title: 'Key', dataIndex: 'key', width: 160 },
    { title: '名称', dataIndex: 'name' },
  ]
  const removedColumns = addedColumns
  const changedColumns = [
    { title: 'Key', dataIndex: 'key', width: 160 },
    { title: '名称', dataIndex: 'name', width: 160 },
    {
      title: '字段变更',
      dataIndex: 'changes',
      render: (changes) => {
        if (!changes || !Object.keys(changes).length) {
          return <Text type="secondary">—</Text>
        }
        return (
          <Space direction="vertical" size={2} style={{ width: '100%' }}>
            {Object.entries(changes).map(([k, v]) => {
              const hasPair = v && typeof v === 'object' && ('old' in v || 'new' in v)
              const oldVal = hasPair ? v.old : undefined
              const newVal = hasPair ? v.new : v
              return (
                <div key={k} style={{ fontSize: 12 }}>
                  <Text type="secondary">{k}:</Text>{' '}
                  {hasPair && oldVal !== undefined && (
                    <>
                      <Text delete>{JSON.stringify(oldVal)}</Text>
                      {' → '}
                    </>
                  )}
                  <Text code>{JSON.stringify(newVal)}</Text>
                </div>
              )
            })}
          </Space>
        )
      },
    },
  ]

  return (
    <>
      <Descriptions size="small" bordered column={4} style={{ marginBottom: 12 }}>
        <Descriptions.Item label="新增">{summary.added || 0}</Descriptions.Item>
        <Descriptions.Item label="删除">{summary.removed || 0}</Descriptions.Item>
        <Descriptions.Item label="变更">{summary.changed || 0}</Descriptions.Item>
        <Descriptions.Item label="元信息">{summary.meta_changed || 0}</Descriptions.Item>
      </Descriptions>
      {!hasAny ? (
        <Alert type="success" message="两版本内容完全一致" showIcon />
      ) : (
        <Tabs
          items={[
            {
              key: 'added',
              label: `新增 (${(safe.items_added || []).length})`,
              children:
                (safe.items_added || []).length === 0 ? (
                  <Empty description="无新增项" />
                ) : (
                  <Table
                    size="small"
                    rowKey={(r) => r.key}
                    dataSource={safe.items_added}
                    columns={addedColumns}
                    pagination={{ pageSize: 10 }}
                  />
                ),
            },
            {
              key: 'removed',
              label: `删除 (${(safe.items_removed || []).length})`,
              children:
                (safe.items_removed || []).length === 0 ? (
                  <Empty description="无删除项" />
                ) : (
                  <Table
                    size="small"
                    rowKey={(r) => r.key}
                    dataSource={safe.items_removed}
                    columns={removedColumns}
                    pagination={{ pageSize: 10 }}
                  />
                ),
            },
            {
              key: 'changed',
              label: `变更 (${(safe.items_changed || []).length})`,
              children:
                (safe.items_changed || []).length === 0 ? (
                  <Empty description="无字段变更" />
                ) : (
                  <Table
                    size="small"
                    rowKey={(r) => r.key}
                    dataSource={safe.items_changed}
                    columns={changedColumns}
                    pagination={{ pageSize: 10 }}
                  />
                ),
            },
            {
              key: 'meta',
              label: `元信息 (${metaChangedEntries.length})`,
              children:
                metaChangedEntries.length === 0 ? (
                  <Empty description="元信息无变更" />
                ) : (
                  <Space direction="vertical" size={6} style={{ width: '100%' }}>
                    {metaChangedEntries.map(([k, v]) => (
                      <div key={k} style={{ fontSize: 12 }}>
                        <Tag>{k}</Tag>
                        <Text delete>{JSON.stringify(v?.old)}</Text>
                        {' → '}
                        <Text code>{JSON.stringify(v?.new)}</Text>
                      </div>
                    ))}
                  </Space>
                ),
            },
          ]}
        />
      )}
    </>
  )
}

export default SpecDiffView
